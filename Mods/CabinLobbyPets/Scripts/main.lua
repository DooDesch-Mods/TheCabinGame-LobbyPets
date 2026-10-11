local directory = debug.getinfo(1, "S").source:sub(2):match("^(.*[/\\])")
local save = assert(loadfile(directory .. "pet-save.lua"))()
local marker = -2713701
local records, failures, removals = {}, {}, {}
local statics, system, ai, nativeValid
local hook, pending = false, false
local lastPawn, lastData, lastSent = nil, nil, 0
local ticks = 0
local cats = {
    [1] = "/Game/Animal_pack_ultra_2/Materials/M_Cat_v1_material.M_Cat_v1_material",
    [2] = "/Game/Cabin_Lobby_Content/Pet_Content/Pets/Cat/Skins/M_HauntedKitty.M_HauntedKitty",
    [4] = "/Game/Animal_pack_ultra_2/Materials/M_Cat_v2_material.M_Cat_v2_material",
}
local dogs = {
    [3] = "/Game/Animal_pack_ultra_2/Materials/M_Hellenic_hound_material.M_Hellenic_hound_material",
    [5] = "/Game/Cabin_Lobby_Content/Pet_Content/Pets/Dog/Mats/M_HauntedDog.M_HauntedDog",
    [6] = "/Game/Animal_pack_ultra_2/Materials/M_Hellenic_hound_material.M_Hellenic_hound_material",
}

local function log(level, message)
    print("[CabinLobbyPets] " .. level .. ": " .. message .. "\n")
end

local function guard(operation, callback)
    local ok, cause = pcall(callback)
    if not ok then
        cause = tostring(cause)
        if failures[operation] ~= cause then log("error", operation .. ": " .. cause) end
        failures[operation] = cause
    elseif failures[operation] then
        log("info", operation .. " recovered")
        failures[operation] = nil
    end
end

local function valid(object)
    return object and object:IsValid() and nativeValid(system, object)
end

local function asset(path)
    local object = StaticFindObject(path)
    if not object or not object:IsValid() then object = LoadAsset(path) end
    assert(object and object:IsValid(), "required pet asset missing: " .. path)
    return object
end

local function destroy(pet)
    if valid(pet) then
        local key = pet:GetAddress()
        if removals[key] then return end
        local name = pet:GetFullName()
        pet:K2_DestroyActor()
        removals[key] = {actor = pet, name = name, started = ticks}
        log("info", "removal requested: " .. name)
    end
end

local function setPet(record, kind, id, garage)
    local current = record[kind]
    if current and current.id == id and valid(current.actor) then return end
    if id == 0 then
        if current then destroy(current.actor) end
        record[kind] = nil
        return
    end
    local actor = current and current.actor
    if not valid(actor) then
        local species = kind == "cat" and "Cat" or "Dog"
        local prefix = "/Game/Cabin_Lobby_Content/Pet_Content/Pets/" .. species .. "/"
        local spawn = garage[kind == "cat" and "CatSpawn" or "DogSpawn"]:K2_GetComponentLocation()
        spawn.Y = spawn.Y + record.offset
        actor = ai:SpawnAIFromClass(garage, asset(prefix .. species .. "_Pet_Character." .. species .. "_Pet_Character_C"), asset(prefix .. "BT_" .. species .. "Pet.BT_" .. species .. "Pet"), spawn, {Pitch = 0, Yaw = 0, Roll = 0}, true, nil)
        assert(valid(actor), "pet spawn returned no actor: " .. species)
        actor:SetReplicates(true)
        actor:SetReplicateMovement(true)
        record[kind] = {actor = actor, id = -1}
        log("info", "spawned " .. actor:GetFullName() .. " for " .. record.pawn:GetFullName())
    end
    local material = asset((kind == "cat" and cats or dogs)[id])
    actor:Set_Skin_E(material)
    record[kind] = {actor = actor, id = id, material = material}
    log("info", "selected " .. kind .. " skin=" .. id .. " for " .. record.pawn:GetFullName())
end

local function receive(context, actor, random, mode, vector)
    if mode:get() ~= marker then return end
    guard("receive pet selection", function()
        local pawn = context:get()
        if not valid(pawn) or not pawn:HasAuthority() then return end
        local garage = FindFirstOf("Lobby_Garage_BP_C")
        if not valid(garage) or not garage:HasAuthority() then
            log("info", "pet selection ignored outside the lobby")
            return
        end
        assert(not actor:get():IsValid() and not random:get(), "pet payload target must be empty")
        local value = vector:get()
        assert(value.Z == 1 and (value.X == 0 or cats[value.X]) and (value.Y == 0 or dogs[value.Y]), "invalid pet selection payload")
        local pc = pawn.Controller
        assert(valid(pc) and pc.Pawn:GetAddress() == pawn:GetAddress(), "pet payload has no owning controller")
        if pc:IsLocalController() then return end
        local key = pawn:GetAddress()
        local record = records[key]
        if not record then
            local index = 1
            for _ in pairs(records) do index = index + 1 end
            record = {pawn = pawn, pc = pc, offset = index * 75}
            records[key] = record
            log("info", "received pet selection from " .. pawn:GetFullName())
        end
        setPet(record, "cat", value.X, garage)
        setPet(record, "dog", value.Y, garage)
    end)
end

local function update()
    ticks = ticks + 1
    statics = statics or asset("/Script/Engine.Default__GameplayStatics")
    system = system or asset("/Script/Engine.Default__KismetSystemLibrary")
    ai = ai or asset("/Script/AIModule.Default__AIBlueprintHelperLibrary")
    nativeValid = nativeValid or asset("/Script/Engine.KismetSystemLibrary:IsValid")
    for key, removal in pairs(removals) do
        guard("remove " .. removal.name, function()
            if not valid(removal.actor) then
                removals[key] = nil
                log("info", "removed " .. removal.name)
            else
                assert(ticks - removal.started < 5, "pet destruction not acknowledged after 5 seconds")
            end
        end)
    end
    if not hook then
        local path = "/Game/CabinGameContent/PlayerContent/Cabin_Player.Cabin_Player_C:AdditionalActorRep_E"
        local functionObject = StaticFindObject(path)
        if functionObject and functionObject:IsValid() then
            RegisterHook(path, receive)
            hook = true
            log("info", "pet selection receiver registered")
        end
    end
    local garage = FindFirstOf("Lobby_Garage_BP_C")
    for key, record in pairs(records) do
        if not valid(garage) or not valid(record.pawn) or not valid(record.pc) or record.pc.Pawn:GetAddress() ~= key then
            destroy(record.cat and record.cat.actor)
            destroy(record.dog and record.dog.actor)
            records[key] = nil
        elseif ticks % 15 == 0 then
            -- Native skin multicast is repeated for players who join after spawning.
            for _, kind in ipairs({"cat", "dog"}) do
                local pet = record[kind]
                if pet and valid(pet.actor) then pet.actor:Set_Skin_E(pet.material) end
            end
        end
    end
    if not valid(garage) then
        lastPawn, lastData = nil, nil
        return
    end
    local pc = statics:GetPlayerController(garage, 0)
    if not valid(pc) or not pc:IsLocalController() or not valid(pc.Pawn) then return end
    if pc:HasAuthority() then return end
    local file, cause = io.open(system:GetProjectSavedDirectory():ToString() .. "SaveGames/LobbyData.sav", "rb")
    assert(file, "cannot read local pet selection: " .. tostring(cause))
    local data = assert(file:read("a"))
    assert(file:close(), "cannot close local pet save")
    if data ~= lastData or pc.Pawn:GetAddress() ~= lastPawn or ticks - lastSent >= 15 then
        local cat, dog = save.decode(data)
        pc.Pawn:AdditionalActorRep_E(nil, false, marker, {X = cat, Y = dog, Z = 1})
        if data ~= lastData or pc.Pawn:GetAddress() ~= lastPawn then
            log("info", "pet selection sent to host; cat=" .. cat .. "; dog=" .. dog)
        end
        lastPawn, lastData, lastSent = pc.Pawn:GetAddress(), data, ticks
    end
end

LoopAsync(1000, function()
    if pending then return end
    pending = true
    ExecuteInGameThread(function()
        guard("update lobby pets", update)
        pending = false
    end)
end)
log("info", "loaded; waiting for lobby")
