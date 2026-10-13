local codec = require("cabin_codec")
local M = {version=1}
local PREFIX = "CabinModSettingsV1."
function M.new(transport, log)
    local registry = {version=1, registrations={}}
    local function get(key) return transport:GetSharedVariable(PREFIX .. key) end
    local function set(key,value) transport:SetSharedVariable(PREFIX .. key,value) end
    function registry:register(definition, adapter)
        assert(type(definition.id) == "string" and definition.id:match("^[a-z][a-z0-9_]*$"),"invalid stable mod ID")
        assert(type(definition.name) == "string" and type(definition.fields) == "table", "mod metadata missing")
        assert(type(adapter.read) == "function" and type(adapter.apply) == "function", "mod read/apply functions missing")
        assert(not self.registrations[definition.id],"duplicate local mod registration")
        local id = definition.id
        self.registrations[id] = {definition=codec.copy(definition),adapter=adapter}
        local index = get("index") or ""
        local present = false
        for value in index:gmatch("([^\n]+)\n") do if value == id then present = true end end
        if not present then set("index",index .. id .. "\n") end
        set(id .. ".request",nil)
        set(id .. ".response",nil)
        self:publish(id)
    end
    function registry:publish(id)
        local entry = assert(self.registrations[id],"mod not locally registered")
        local values, revision = entry.adapter.read()
        set(id .. ".snapshot",codec.encode({definition=entry.definition,values=values,revision=revision}))
    end
    function registry:list()
        local result = {}
        for id in (get("index") or ""):gmatch("([^\n]+)\n") do
            local bytes = get(id .. ".snapshot")
            if bytes then result[#result+1] = codec.decode(bytes) end
        end
        table.sort(result,function(a,b) return a.definition.name < b.definition.name end)
        return result
    end
    function registry:request(id, token, revision, values, action)
        assert(not get(id .. ".request"), "previous settings request still pending")
        assert(type(token) == "string" and #token > 0,"request token required")
        set(id .. ".response",nil)
        set(id .. ".request",codec.encode({token=token,revision=revision,values=values,action=action or ""}))
    end
    function registry:response(id,token)
        local bytes = get(id .. ".response")
        if not bytes then return nil end
        local response = codec.decode(bytes)
        assert(response.token == token,"settings acknowledgement belongs to another request")
        return response
    end
    function registry:poll()
        for id,entry in pairs(self.registrations) do
            local bytes = get(id .. ".request")
            if bytes then
                local token = "malformed"
                local ok, result = pcall(function()
                    local request = codec.decode(bytes)
                    token = request.token
                    assert(type(token) == "string","request token missing")
                    local _,revision = entry.adapter.read()
                    assert(request.revision == revision,"settings changed; reload this view")
                    local values,newRevision = entry.adapter.apply(request.values,request.action)
                    return {token=token,ok=true,values=values,revision=newRevision}
                end)
                if not ok then
                    log("error","apply " .. id .. ": " .. tostring(result))
                    result = {token=token,ok=false,error=tostring(result)}
                end
                set(id .. ".response",codec.encode(result))
                set(id .. ".request",nil)
                self:publish(id)
            end
        end
    end
    return registry
end
return M
