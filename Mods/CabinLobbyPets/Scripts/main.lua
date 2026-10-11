local directory = debug.getinfo(1, "S").source:sub(2):match("^(.*[/\\])")
local save = assert(loadfile(directory .. "pet-save.lua"))()
local settings = assert(loadfile(directory .. "settings.lua"))()
assert(type(settings) == "table" and type(settings.in_cabin) == "boolean", "settings.in_cabin must be boolean")
local marker = -2713701
local records, failures, removals = {}, {}, {}
local statics, system, ai, nativeValid
local hook, pending = false, false
local lastPawn, lastData, lastWorld, lastSent = nil, nil, nil, 0
local ticks = 0
local cats = {
    [1] = "/Game/Animal_pack_ultra_2/Materials/M_Cat_v1_material.M_Cat_v1_material",
    [2] = "/Game/Cabin_Lobby_Content/Pet_Content/Pets/Cat/Skins/M_HauntedKitty.M_HauntedKitty",
    [4] = "/Game/Animal_pack_ultra_2/Materials/M_Cat_v2_material.M_Cat_v2_material",
}
local dogs = {
    [3] = "/Game/Animal_pack_ultra_2/Materials/M_Hellenic_hound_v2_material.M_Hellenic_hound_v2_material",
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

local function sceneFor(pawn)
    for _, class in ipairs({"Lobby_Garage_BP_C", "RealCabin_BP_C"}) do
        for _, actor in ipairs(FindAllOf(class) or {}) do
            if valid(actor) and actor:GetWorld():GetAddress() == pawn:GetWorld():GetAddress() then
                return actor, class == "RealCabin_BP_C"
            end
        end
    end
end

local function spawnPoint(record, kind)
    if not record.inCabin then
        local p = record.scene[kind == "cat" and "CatSpawn" or "DogSpawn"]:K2_GetComponentLocation()
        p.Y = p.Y + record.offset
        return p
    end
    local chair = record.pawn.Chair
    if not valid(chair) or chair:GetWorld():GetAddress() ~= record.scene:GetWorld():GetAddress() then return end
    local mesh = chair.Chair
    if not valid(mesh) then return end
    local p = mesh:K2_GetComponentLocation()
    local forward, right = chair:GetActorForwardVector(), chair:GetActorRightVector()
    local side = kind == "cat" and -40 or 40
    return {X = p.X - forward.X * 65 + right.X * side,
            Y = p.Y - forward.Y * 65 + right.Y * side,
            Z = chair:K2_GetActorLocation().Z + 55}
end

local function setPet(record, kind, id)
    local current = record[kind]
    if current and current.id == id and valid(current.actor) then return end
    if id == 0 then
        if current then destroy(current.actor) end
        record[kind] = nil
        return
    end
    local actor = current and current.actor
    if not valid(actor) then
        local spawn = spawnPoint(record, kind)
        if not spawn then
            if not record.waiting then log("info", "waiting for assigned Cabin chair: " .. record.pawn:GetFullName()) end
            record.waiting = true
            return
        end
        if record.waiting then log("info", "assigned Cabin chair available: " .. record.pawn:GetFullName()) end
        record.waiting = nil
        local species = kind == "cat" and "Cat" or "Dog"
        local prefix = "/Game/Cabin_Lobby_Content/Pet_Content/Pets/" .. species .. "/"
        actor = ai:SpawnAIFromClass(record.scene, asset(prefix .. species .. "_Pet_Character." .. species .. "_Pet_Character_C"), asset(prefix .. "BT_" .. species .. "Pet.BT_" .. species .. "Pet"), spawn, {Pitch = 0, Yaw = 0, Roll = 0}, true, nil)
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

local function selectPets(pawn, pc, cat, dog, scene, inCabin)
    local key = pawn:GetAddress()
    local record = records[key]
    if record and record.scene:GetAddress() ~= scene:GetAddress() then
        destroy(record.cat and record.cat.actor)
        destroy(record.dog and record.dog.actor)
        records[key] = nil
        record = nil
    end
    if not record then
        local index = 1
        for _ in pairs(records) do index = index + 1 end
        record = {pawn = pawn, pc = pc, offset = index * 75, scene = scene, inCabin = inCabin}
        records[key] = record
        log("info", "received pet selection from " .. pawn:GetFullName())
    end
    record.catId, record.dogId = cat, dog
    setPet(record, "cat", cat)
    setPet(record, "dog", dog)
end

local function receive(context, actor, random, mode, vector)
    if mode:get() ~= marker then return end
    guard("receive pet selection", function()
        local pawn = context:get()
        if not valid(pawn) or not pawn:HasAuthority() then return end
        local scene, inCabin = sceneFor(pawn)
        if not scene or not scene:HasAuthority() or (inCabin and not settings.in_cabin) then return end
        assert(not actor:get():IsValid() and not random:get(), "pet payload target must be empty")
        local value = vector:get()
        assert(value.Z == 1 and (value.X == 0 or cats[value.X]) and (value.Y == 0 or dogs[value.Y]), "invalid pet selection payload")
        local pc = pawn.Controller
        assert(valid(pc) and pc.Pawn:GetAddress() == pawn:GetAddress(), "pet payload has no owning controller")
        if pc:IsLocalController() and not inCabin then return end
        selectPets(pawn, pc, value.X, value.Y, scene, inCabin)
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
    for key, record in pairs(records) do
        if not valid(record.scene) or not valid(record.pawn) or not valid(record.pc)
            or not valid(record.pc.Pawn) or record.pc.Pawn:GetAddress() ~= key
            or record.pawn:GetWorld():GetAddress() ~= record.scene:GetWorld():GetAddress() then
            destroy(record.cat and record.cat.actor)
            destroy(record.dog and record.dog.actor)
            records[key] = nil
        else
            setPet(record, "cat", record.catId)
            setPet(record, "dog", record.dogId)
            if ticks % 15 == 0 then
                -- Native skin multicast is repeated for players who join after spawning.
                for _, kind in ipairs({"cat", "dog"}) do
                    local pet = record[kind]
                    if pet and valid(pet.actor) then pet.actor:Set_Skin_E(pet.material) end
                end
            end
        end
    end
    local pc
    for _, candidate in ipairs(FindAllOf("Cabin_PC_C") or {}) do
        if valid(candidate) and candidate:IsLocalController() and valid(candidate.Player)
            and valid(candidate.Player.PlayerController) and candidate.Player.PlayerController:GetAddress() == candidate:GetAddress() then
            pc = candidate
            break
        end
    end
    if not pc or not valid(pc.Pawn) then return end
    local scene, inCabin = sceneFor(pc.Pawn)
    if not scene then
        lastPawn, lastData, lastWorld = nil, nil, nil
        return
    end
    if pc:HasAuthority() and (not inCabin or not settings.in_cabin) then return end
    local file, cause = io.open(system:GetProjectSavedDirectory():ToString() .. "SaveGames/LobbyData.sav", "rb")
    assert(file, "cannot read local pet selection: " .. tostring(cause))
    local data = assert(file:read("a"))
    assert(file:close(), "cannot close local pet save")
    if pc:HasAuthority() then
        local cat, dog = save.decode(data)
        selectPets(pc.Pawn, pc, cat, dog, scene, inCabin)
        return
    end
    local world = pc.Pawn:GetWorld():GetAddress()
    if data ~= lastData or pc.Pawn:GetAddress() ~= lastPawn or world ~= lastWorld or ticks - lastSent >= 15 then
        local cat, dog = save.decode(data)
        pc.Pawn:AdditionalActorRep_E(nil, false, marker, {X = cat, Y = dog, Z = 1})
        if data ~= lastData or pc.Pawn:GetAddress() ~= lastPawn then
            log("info", "pet selection sent to host; cat=" .. cat .. "; dog=" .. dog)
        end
        lastPawn, lastData, lastWorld, lastSent = pc.Pawn:GetAddress(), data, world, ticks
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
log("info", "loaded; Cabin pets=" .. tostring(settings.in_cabin))
