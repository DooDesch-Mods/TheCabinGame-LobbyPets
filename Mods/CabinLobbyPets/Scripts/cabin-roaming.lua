local M={}
local function valid(value)return value and value:IsValid()end
function M.update(record,log)
    if not record.inCabin then return end
    local world=record.scene:GetWorld():GetAddress()
    for _,bowl in ipairs(FindAllOf("WaterBowl_BP_C")or{})do
        if valid(bowl)and not bowl:IsActorBeingDestroyed()and bowl:GetWorld():GetAddress()==world then return end
    end
    for _,kind in ipairs({"cat","dog"})do
        local pet=record[kind]and record[kind].actor
        if valid(pet)then
            assert(pet:HasAuthority()and pet:GetWorld():GetAddress()==world,"Cabin pet roaming authority/world differs")
            local controller=pet.Controller
            if valid(controller)then
                local blackboard,brain=controller.Blackboard,controller.BrainComponent
                if valid(blackboard)and valid(brain)then
                    local changed=false
                    for _,name in ipairs({"IsThirsty","IsDrinking"})do
                        local key=FName(name)
                        if blackboard:GetValueAsBool(key)then
                            blackboard:SetValueAsBool(key,false)
                            assert(blackboard:GetValueAsBool(key)==false,"Cabin pet water state readback differs="..name)
                            changed=true
                        end
                    end
                    if changed then
                        -- The lobby tree otherwise waits for a water bowl that this map does not contain.
                        brain:RestartLogic()
                        log("info","Cabin pet returned to original roaming without a water bowl: "..pet:GetFullName())
                    end
                end
            end
        end
    end
end
return M
