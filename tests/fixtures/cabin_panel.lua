local codec = require("cabin_codec")
local store = require("cabin_store")
local M = {}
function M.new(registry, clock)
    local self = {registry=registry, drafts={}, visible=false, serial=0}
    function self:open()
        assert(not self.pending,"settings apply still pending")
        self.drafts, self.error, self.pending = {}, nil, nil
        for _,snapshot in ipairs(registry:list()) do
            self.drafts[snapshot.definition.id] = {snapshot=snapshot,values=codec.copy(snapshot.values),dirty=false,action=""}
        end
        self.visible = true
    end
    function self:edit(id,key,value)
        assert(self.visible and not self.pending,"panel unavailable while applying")
        local draft = assert(self.drafts[id],"mod unavailable")
        draft.values[key], draft.dirty = value, true
        self.error = nil
    end
    function self:defaults(id)
        assert(not self.pending,"settings apply still pending")
        local draft = assert(self.drafts[id],"mod unavailable")
        draft.values = store.defaults(draft.snapshot.definition.fields)
        draft.dirty, draft.action = true, ""
    end
    function self:action(id,key)
        assert(not self.pending,"settings apply still pending")
        local draft = assert(self.drafts[id],"mod unavailable")
        local found = false
        for _,field in ipairs(draft.snapshot.definition.fields) do if field.key == key and field.type == "action" then found = true end end
        assert(found,"unregistered settings action")
        draft.action, draft.dirty = key, true
    end
    function self:cancel()
        self.queue=nil
        if self.pending then
            self.drafts={[self.pending.id]=self.drafts[self.pending.id]}
            self.visible=false
        else self.drafts,self.visible,self.error={},false,nil end
    end
    function self:applyAll()
        assert(not self.pending,"settings apply still pending")
        local queue={}
        for id,draft in pairs(self.drafts) do
            if draft.dirty then
                local ok,cause=pcall(store.validate,draft.snapshot.definition.fields,draft.values)
                if not ok then self.error=tostring(cause);return false end
                queue[#queue+1]=id
            end
        end
        table.sort(queue)
        self.queue=queue
        if #queue>0 then return self:apply(table.remove(queue,1)) end
        self.error=nil
        return true
    end
    function self:apply(id)
        assert(not self.pending,"settings apply still pending")
        local draft = assert(self.drafts[id],"mod unavailable")
        local ok, values = pcall(store.validate,draft.snapshot.definition.fields,draft.values)
        if not ok then self.error = tostring(values); return false end
        self.serial = self.serial + 1
        local token = tostring(clock()) .. ":" .. self.serial
        registry:request(id,token,draft.snapshot.revision,values,draft.action)
        self.pending = {id=id,token=token,since=clock()}
        self.error = nil
        return true
    end
    function self:poll()
        if not self.pending then return end
        local pending = self.pending
        local response = registry:response(pending.id,pending.token)
        if response then
            if response.ok then
                local draft = self.drafts[pending.id]
                draft.values = codec.copy(response.values)
                draft.snapshot.values, draft.snapshot.revision = codec.copy(response.values),response.revision
                draft.dirty, draft.action, self.error = false,"",nil
            else self.error = response.error;self.queue=nil end
            self.pending = nil
            if self.queue and #self.queue>0 then self:apply(table.remove(self.queue,1)) end
        elseif clock()-pending.since >= 10 then
            self.error = "Settings acknowledgement timed out. The save result is unknown."
        end
    end
    return self
end
return M
