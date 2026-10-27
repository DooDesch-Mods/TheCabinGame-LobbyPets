"""Keep Cabin pets out of a lobby-only water task without changing lobby pets."""
import unittest
from pathlib import Path
import test_settings

class CabinRoamingTests(unittest.TestCase):
    def test_missing_bowl_recovers_only_current_cabin_pet_once(self):
        vm=test_settings.LuaRuntime()
        vm.globals().module=str(Path(__file__).resolve().parents[1]/'Mods/CabinLobbyPets/Scripts/cabin-roaming.lua')
        vm.execute('''
        local function object(id)
            return {IsValid=function()return true end,GetAddress=function()return id end}
        end
        local world=object(1)
        local scene=object(2);function scene:GetWorld()return world end
        local pet=object(3)
        function pet:GetWorld()return world end
        function pet:HasAuthority()return true end
        function pet:GetFullName()return "fixture Cabin cat"end
        local board=object(4);local values={IsThirsty=true,IsDrinking=true}
        function FName(name)return name end
        function board:GetValueAsBool(key)return values[key]end
        function board:SetValueAsBool(key,value)values[key]=value end
        local restarts,logs=0,0
        local brain=object(5);function brain:RestartLogic()restarts=restarts+1 end
        pet.Controller=object(6);pet.Controller.Blackboard=board;pet.Controller.BrainComponent=brain
        local bowl=object(7)
        function bowl:IsActorBeingDestroyed()return false end
        function bowl:GetWorld()return world end
        local bowls={}
        function FindAllOf(kind)assert(kind=="WaterBowl_BP_C");return bowls end
        local update=assert(loadfile(module))().update
        local record={scene=scene,cat={actor=pet},inCabin=false}
        local function log()logs=logs+1 end
        update(record,log);assert(restarts==0 and values.IsThirsty)
        record.inCabin=true;bowls={bowl}
        update(record,log);assert(restarts==0 and values.IsThirsty)
        bowls={};update(record,log)
        assert(restarts==1 and logs==1 and not values.IsThirsty and not values.IsDrinking)
        update(record,log);assert(restarts==1 and logs==1)
        ''')

if __name__=='__main__':unittest.main()
