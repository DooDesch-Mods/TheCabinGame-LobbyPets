local M = {}
local LIMIT = 65536
local function encode(value, depth)
    assert(depth < 16, "record nesting exceeds 15")
    local kind = type(value)
    if kind == "boolean" then return value and "b1" or "b0" end
    if kind == "string" or kind == "number" then
        if kind == "number" then assert(value == value and math.abs(value) < math.huge, "nonfinite number") end
        local bytes = kind == "number" and math.type(value) == "float" and string.format("%.17g",value) or tostring(value)
        return (kind == "string" and "s" or "n") .. #bytes .. ":" .. bytes
    end
    assert(kind == "table", "record type unsupported: " .. kind)
    local keys = {}
    for key in pairs(value) do
        assert(type(key) == "string" or (math.type(key) == "integer" and key > 0), "record key unsupported")
        keys[#keys+1] = key
    end
    table.sort(keys, function(a,b) return type(a) == type(b) and a < b or type(a) < type(b) end)
    local result = {"t", tostring(#keys), ":"}
    for _, key in ipairs(keys) do
        result[#result+1] = encode(key, depth+1)
        result[#result+1] = encode(value[key], depth+1)
    end
    return table.concat(result)
end
function M.encode(value)
    local bytes = encode(value, 0)
    assert(#bytes <= LIMIT, "record exceeds 65536 bytes")
    return bytes
end
function M.decode(bytes)
    assert(type(bytes) == "string" and #bytes <= LIMIT, "record missing or oversized")
    local position = 1
    local function decode(depth)
        assert(depth < 16, "record nesting exceeds 15")
        local tag = bytes:sub(position,position)
        position = position + 1
        if tag == "b" then
            local bit = bytes:sub(position,position)
            assert(bit == "0" or bit == "1", "invalid boolean")
            position = position + 1
            return bit == "1"
        end
        assert(tag == "s" or tag == "n" or tag == "t", "invalid record tag")
        local colon = bytes:find(":",position,true)
        assert(colon and colon-position <= 6, "invalid record length")
        local length = bytes:sub(position,colon-1)
        assert(length:match("^%d+$") and (length == "0" or length:sub(1,1) ~= "0"), "noncanonical record length")
        length = tonumber(length)
        assert(length <= LIMIT, "record length exceeds limit")
        position = colon + 1
        if tag == "t" then
            assert(length <= 512, "record fields exceed 512")
            local value = {}
            for _=1,length do
                local key = decode(depth+1)
                assert(type(key) == "string" or (math.type(key) == "integer" and key > 0), "invalid record key")
                assert(value[key] == nil, "duplicate record key")
                value[key] = decode(depth+1)
            end
            return value
        end
        assert(position+length-1 <= #bytes, "record truncated")
        local value = bytes:sub(position,position+length-1)
        position = position+length
        if tag == "s" then return value end
        value = tonumber(value)
        assert(value and value == value and math.abs(value) < math.huge, "invalid record number")
        return value
    end
    local value = decode(0)
    assert(position == #bytes+1, "record trailing data")
    return value
end
function M.copy(value) return M.decode(M.encode(value)) end
return M
