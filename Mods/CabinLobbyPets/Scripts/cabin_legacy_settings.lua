local codec = require("cabin_codec")
local M = {}

local function bytes(path)
    local file, cause = io.open(path,"rb")
    assert(file,"read " .. path .. ": " .. tostring(cause))
    local data, why = file:read("a")
    local closed, closeCause = file:close()
    assert(data and closed,"read/close " .. path .. ": " .. tostring(why or closeCause))
    return data
end

local function literal(value)
    local kind = type(value)
    if kind == "string" then return string.format("%q",value) end
    if kind == "boolean" then return tostring(value) end
    if kind == "number" then
        assert(value==value and math.abs(value)<math.huge,"non-finite setting")
        return string.format("%.17g",value)
    end
    assert(kind=="table","unsupported extra settings value: " .. kind)
    local entries = {}
    for key,item in pairs(value) do
        entries[#entries+1] = "[" .. literal(key) .. "] = " .. literal(item)
    end
    table.sort(entries)
    return "{\n" .. table.concat(entries,",\n") .. "\n}"
end

function M.start(directory, definition, log, readCurrent, setCurrent)
    if not ModRef or not ModRef.GetSharedVariable or not ModRef.SetSharedVariable then
        log("info","Settings registration skipped: registry transport unavailable")
        return nil
    end
    local path = directory .. "settings.lua"
    local full,header
    local function selected(values)
        local result = {}
        for _,field in ipairs(definition.fields) do result[field.key]=values[field.key] end
        return result
    end
    local format = {copy=codec.copy}
    function format.decode(data)
        -- The original mod already loaded this Lua file; do not execute it twice.
        full=readCurrent()
        assert(type(full)=="table","settings.lua must return a table")
        local lines={}
        for line in (data .. "\n"):gmatch("([^\n]*\n)") do
            if not line:match("^%s*%-%-") and not line:match("^%s*$") then break end
            if not line:match("^%-%- CabinModSettings revision:") then lines[#lines+1]=line end
        end
        header=table.concat(lines)
        return {schema=1,revision=tonumber(data:match("^%-%- CabinModSettings revision: (%d+)")) or 1,values=selected(full)}
    end
    function format.encode(record)
        local values=codec.copy(full)
        for key,value in pairs(record.values) do values[key]=value end
        return "-- CabinModSettings revision: " .. record.revision .. "\n" .. header .. "return " .. literal(values) .. "\n"
    end
    -- Only the file store gets Lua serialization; registry messages keep the V1 codec.
    local environment=setmetatable({require=function(name)
        if name=="cabin_codec" then return format end
        return require(name)
    end},{__index=_G})
    local storage=assert(loadfile(directory .. "cabin_store.lua","t",environment))()
    local store=storage.new(path,definition.fields,log)
    local seenFile=bytes(path)
    local snapshot=storage.validate(definition.fields,selected(readCurrent()))
    local revision=0
    local registry=require("cabin_registry").new(ModRef,log)
    local self={registry=registry}
    function self:read()
        local values=storage.validate(definition.fields,selected(readCurrent()))
        if codec.encode(values)~=codec.encode(snapshot) then
            snapshot=codec.copy(values)
            revision=revision+1
        end
        return codec.copy(snapshot),revision
    end
    local adapter={
        read=function() return self:read() end,
        apply=function(values,action)
            assert(action=="","this mod has no settings actions")
            assert(bytes(path)==seenFile,"settings.lua changed outside the panel; restart the game before Apply")
            local effective=codec.copy(full)
            for key,value in pairs(storage.validate(definition.fields,values)) do effective[key]=value end
            local confirmed=store:save(values)
            for _,field in ipairs(definition.fields) do assert(confirmed[field.key]==effective[field.key],"saved setting differs: " .. field.key) end
            seenFile=bytes(path)
            setCurrent(effective)
            return self:read()
        end,
    }
    registry:register(definition,adapter)
    self.definition=definition
    self.store={save=function(_,values) return adapter.apply(values,"") end}
    function self:observe(name,callback)
        assert(name=="authority host settings" and not self.hostObserver,"duplicate or unsupported Settings observer")
        self.hostObserver=callback
    end
    function self:log(level,message) log(level,message) end
    local published=revision
    local lastError,failures=nil,0
    function self:poll()
        local ok,cause=pcall(function()
            if self.hostObserver then self.hostObserver() end
            self:read()
            registry:poll()
            if published~=revision then registry:publish(definition.id);published=revision end
        end)
        if not ok then
            failures=failures+1;cause=tostring(cause)
            if cause~=lastError or failures%60==0 then log("error","Settings poll: " .. cause .. "; failures=" .. failures) end
            lastError=cause
        elseif lastError then
            log("info","Settings poll recovered after " .. failures .. " failures")
            lastError,failures=nil,0
        end
    end
    log("info","optional Settings registry registered")
    return self
end
return M
