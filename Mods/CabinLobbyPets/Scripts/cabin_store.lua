local codec = require("cabin_codec")
local M = {}
local function read(path)
    local file, cause, code = io.open(path,"rb")
    if not file then return nil, cause, code end
    local bytes, why = file:read(65537)
    local closed, closeCause = file:close()
    assert(bytes and closed, "settings read/close failed: " .. tostring(why or closeCause))
    assert(#bytes <= 65536, "settings file exceeds 65536 bytes")
    return bytes
end
local function validate(definitions, values)
    assert(type(values) == "table", "settings record must be a table")
    local known, result = {}, {}
    for _, field in ipairs(definitions) do
        if field.type ~= "action" then
            known[field.key] = true
            local value = values[field.key]
            if field.type == "boolean" then
                assert(type(value) == "boolean", field.label .. " must be true or false")
            elseif field.type == "number" then
                assert(type(value) == "number" and value == value and math.abs(value) < math.huge
                    and (field.min == nil or value >= field.min) and (field.max == nil or value <= field.max)
                    and (not field.positive or value > 0),field.label .. " is outside its allowed range")
                if field.integer then assert(math.type(value) == "integer", field.label .. " must be an integer") end
            elseif field.type == "choice" then
                local match = false
                for _, option in ipairs(field.options) do if option.value == value then match = true end end
                assert(match, field.label .. " has an invalid selection")
            else error("unknown settings type: " .. tostring(field.type)) end
            result[field.key] = value
        end
    end
    for key in pairs(values) do assert(known[key], "unknown setting: " .. tostring(key)) end
    return result
end
M.validate = validate
function M.defaults(definitions)
    local values = {}
    for _,field in ipairs(definitions) do if field.type ~= "action" then values[field.key] = field.default end end
    return validate(definitions,values)
end
function M.new(path, definitions, log)
    local self = {path=path, definitions=definitions, revision=0}
    local function decode(bytes)
        local record = codec.decode(bytes)
        assert(record.schema == 1 and math.type(record.revision) == "integer" and record.revision >= 1, "settings schema/revision invalid")
        return validate(definitions,record.values), record.revision
    end
    local bytes, cause, code = read(path)
    if bytes then
        local ok, values, revision = pcall(decode,bytes)
        if ok then self.values, self.revision = values, revision else
            log("error","load " .. path .. ": " .. tostring(values))
            local backup, backupCause = read(path .. ".previous")
            assert(backup,"settings recovery missing: " .. tostring(backupCause))
            self.values, self.revision = decode(backup)
            log("warn","loaded last valid settings backup: " .. path)
            self.recovery = true
        end
    elseif code == 2 then
        local backup, backupCause, backupCode = read(path .. ".previous")
        if backup then
            self.values, self.revision = decode(backup)
            self.recovery = true
            log("warn","primary settings file absent; recovered backup: " .. path)
        elseif backupCode == 2 then
            self.values = M.defaults(definitions)
            log("info","settings file absent; defaults active: " .. path)
        else error("settings backup read failed: " .. tostring(backupCause)) end
    else error("load " .. path .. ": " .. tostring(cause)) end
    function self:read() return codec.copy(self.values), self.revision end
    function self:save(candidate)
        local values = validate(definitions,candidate)
        local encoded = codec.encode({schema=1, revision=self.revision+1, values=values})
        local temporary = path .. ".pending"
        local file, why = io.open(temporary,"wb")
        assert(file,"settings prepare " .. temporary .. ": " .. tostring(why))
        local written, writeCause = file:write(encoded)
        local closed, closeCause = file:close()
        assert(written and closed,"settings prepare/close: " .. tostring(writeCause or closeCause))
        assert(read(temporary) == encoded,"settings temporary readback differs")
        local previous = read(path)
        if previous then
            if not self.recovery then
                local oldBackup = read(path .. ".previous")
                if oldBackup then assert(os.remove(path .. ".previous"),"settings old backup removal failed") end
                local moved, moveCause = os.rename(path,path .. ".previous")
                assert(moved,"settings backup: " .. tostring(moveCause))
            else
                assert(os.remove(path),"invalid settings file replacement failed")
            end
        end
        local moved, moveCause = os.rename(temporary,path)
        if not moved then
            if previous and not self.recovery then
                local restored, restoreCause = os.rename(path .. ".previous",path)
                assert(restored,"settings commit failed: " .. tostring(moveCause) .. "; rollback failed: " .. tostring(restoreCause))
            end
            error("settings commit failed: " .. tostring(moveCause))
        end
        local checked,confirmed,readCause = pcall(read,path)
        if not checked or confirmed~=encoded then
            local originalCause=not checked and tostring(confirmed)
                or confirmed==nil and "settings committed readback failed: " .. tostring(readCause)
                or "settings committed readback differs"
            local restored,restoreCause=pcall(function()
                assert(os.remove(path),"unconfirmed settings removal failed")
                if previous or self.recovery then
                    local returned,returnCause=os.rename(path .. ".previous",path)
                    assert(returned,"settings backup restoration failed: " .. tostring(returnCause))
                end
            end)
            error(originalCause .. (restored and "; last valid settings restored" or "; rollback failed: " .. tostring(restoreCause)))
        end
        self.values, self.revision, self.recovery = values, self.revision+1, false
        return self:read()
    end
    return self
end
return M
