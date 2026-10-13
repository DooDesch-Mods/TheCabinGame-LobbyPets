local codec=require("cabin_codec")
local storage=require("cabin_store")
local M={}
local IDS={cabin_fast_turns=true,cabin_short_events=true,cabin_lobby_pets=true}
local serial=0
local function path()
    local directory=IterateGameDirectories().Game.Binaries.Win64.__absolute_path
    assert(type(directory)=="string" and directory~="","executable directory unavailable for host settings")
    return directory .. "/CabinSmallModsHost.dat"
end
local function read(file)
    local handle,cause,code=io.open(file,"rb")
    if not handle then assert(code==2,"host settings read " .. file .. ": " .. tostring(cause));return end
    local bytes=handle:read(65537)
    assert(handle:close(),"host settings close failed")
    assert(bytes and #bytes<=65536,"host settings record too large or unreadable")
    return bytes
end
local function write(file,bytes)
    local handle,cause=io.open(file .. ".pending","wb")
    assert(handle,"host settings prepare " .. file .. ": " .. tostring(cause))
    local saved,why=handle:write(bytes);local closed,closeCause=handle:close()
    assert(saved and closed,"host settings write/close: " .. tostring(why or closeCause))
    assert(read(file .. ".pending")==bytes,"host settings temporary readback differs")
    local previous=read(file)
    if previous then
        if read(file .. ".previous") then assert(os.remove(file .. ".previous"),"host settings old backup removal failed") end
        assert(os.rename(file,file .. ".previous"),"host settings backup failed")
    end
    local committed,why=os.rename(file .. ".pending",file)
    if not committed then
        if previous then assert(os.rename(file .. ".previous",file),"host settings rollback failed: " .. tostring(why)) end
        error("host settings commit failed: " .. tostring(why))
    end
    assert(read(file)==bytes,"host settings committed readback differs")
end
function M.publish(owner,log)
    local registry=require("cabin_registry").new(ModRef,log)
    local mods={}
    for _,snapshot in ipairs(registry:list()) do
        if IDS[snapshot.definition.id] then
            mods[snapshot.definition.id]=storage.validate(snapshot.definition.fields,snapshot.values)
        end
    end
    if next(mods)==nil then return end
    serial=serial+1
    local previous=read(path())
    local sequence=previous and codec.decode(previous).sequence or 0
    assert(math.type(sequence)=="integer" and sequence>=0,"host settings sequence invalid")
    local request={schema=1,owner=owner,sequence=sequence+1,token=tostring(os.time()) .. ":" .. (sequence+1) .. ":" .. serial,mods=mods}
    write(path(),codec.encode(request))
    log("info","host mod settings published token=" .. request.token .. "; authority acknowledgements pending")
    return request
end
function M.acknowledged(request,identity)
    if not request then return true end
    for id,values in pairs(request.mods) do
        local bytes=read(path() .. "." .. id .. ".ack")
        if not bytes then return false,"authority host settings acknowledgement absent: " .. id end
        local ack=codec.decode(bytes)
        if ack.token~=request.token or ack.identity~=identity then return false,"authority host settings acknowledgement pending: " .. id end
        assert(ack.owner==request.owner and codec.encode(ack.values)==codec.encode(values),"authority host settings acknowledgement differs: " .. id)
    end
    return true
end
function M.start(mod)
    if not os.getenv("CABIN_REJOIN_PROCESS_ID") then return end
    local token
    mod:observe("authority host settings",function()
        local bytes=read(path())
        if not bytes then return end
        local request=codec.decode(bytes)
        assert(request.schema==1 and type(request.owner)=="string" and type(request.token)=="string","authority host settings schema invalid")
        local original=assert(read(assert(os.getenv("CABIN_REJOIN_HOST_REQUEST_PATH"))),"original Rejoin host request missing")
        assert(original:match("\nowner_id=([0-9]+)\r?\n")==request.owner,"authority host settings owner differs from original Rejoin request")
        if token==request.token then return end
        local values=request.mods[mod.definition.id]
        if not values then return end
        local saved=mod.store:save(storage.validate(mod.definition.fields,values))
        local ack={token=request.token,owner=request.owner,identity=assert(os.getenv("CABIN_REJOIN_PROCESS_ID")),values=saved}
        write(path() .. "." .. mod.definition.id .. ".ack",codec.encode(ack))
        token=request.token
        mod:log("info","authority host settings saved and acknowledged: " .. mod.definition.id .. " token=" .. token)
    end)
end
return M
