local function fstring(value)
    return string.pack("<i4", #value + 1) .. value .. "\0"
end

local tag = fstring("Chosen_Pet_Skins") .. fstring("MapProperty") .. string.pack("<i4", 2)
    .. fstring("IntProperty") .. string.pack("<i4", 0)
    .. fstring("IntProperty") .. string.pack("<i4", 0)
local allowed = {[1] = {[1] = true, [2] = true, [4] = true}, [2] = {[3] = true, [5] = true, [6] = true}}

local function decode(data)
    assert(data:sub(1, 4) == "GVAS", "LobbyData is not an Unreal save")
    local start = data:find(tag, 1, true)
    if not start then
        assert(not data:find("Chosen_Pet_Skins", 1, true), "unsupported pet map schema")
        return 0, 0
    end
    local size, flags, position = string.unpack("<i4B", data, start + #tag)
    assert(flags == 0, "unsupported pet property flags: " .. flags)
    assert(size >= 8 and size <= 24 and position + size - 1 <= #data, "invalid pet map payload size: " .. size)
    local removed, count
    removed, count, position = string.unpack("<i4i4", data, position)
    assert(removed == 0 and count >= 0 and count <= 2 and size == 8 + count * 8, "invalid pet map entry count")
    local pets = {}
    for _ = 1, count do
        local kind, skin
        kind, skin, position = string.unpack("<i4i4", data, position)
        assert(allowed[kind] and (skin == 0 or allowed[kind][skin]) and pets[kind] == nil, "invalid or duplicate selected pet")
        pets[kind] = skin
    end
    return pets[1] or 0, pets[2] or 0
end

return {decode = decode}
