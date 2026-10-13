"""Exercise the shipped pet spawn path across original Cabin game phases."""
import unittest

import test_settings


class SpawnPhaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_settings.SettingsTests('test_all_shipped_lua_compiles_and_legacy_defaults_register')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.vm = self.fixture.owner()
        self.vm.execute('''
            tick()
            local function upvalue(fn, wanted)
                for index=1,32 do
                    local name, value=debug.getupvalue(fn,index)
                    if not name then break end
                    if name==wanted then return value end
                end
                error("product closure unavailable: "..wanted)
            end
            local update=upvalue(tick,"update")
            setPet=upvalue(update,"setPet")
            spawnPoint=upvalue(setPet,"spawnPoint")
            board=object(31);board.GameStarted=false;pawn.GameBoard=nil
            function FindAllOf(class) if class=="GameBoard_BP_C" then return {board} end return {} end
            function board:GetWorld() return world end
            function board:IsActorBeingDestroyed() return self.destroying or false end
            function board:GetClass() return {GetFullName=function()
                return "BlueprintGeneratedClass /Game/CabinGameContent/BoardGameStuff/Board/GameBoard_BP.GameBoard_BP_C"
            end} end
            chair=object(32);pawn.Chair=chair
            function chair:GetWorld() return world end
            function chair:K2_GetActorLocation() return {X=0,Y=60,Z=260} end
            function chair:GetActorForwardVector() return {X=1,Y=0,Z=0} end
            function chair:GetActorRightVector() return {X=0,Y=1,Z=0} end
            chair.Chair=object(33)
            function chair.Chair:K2_GetComponentLocation() return {X=0,Y=90,Z=260} end
            record={pawn=pawn,pc=pc,scene=scene,inCabin=true,offset=75}
            spawned=0
            function library:SpawnAIFromClass(_,_,_,position)
                spawned=spawned+1;requested={X=position.X,Y=position.Y,Z=position.Z}
                local actor=object(40+spawned)
                function actor:SetReplicates(value) assert(value) end
                function actor:SetReplicateMovement(value) assert(value) end
                function actor:Set_Skin_E(_) skins=(skins or 0)+1 end
                return actor
            end
        ''')

    def test_cabin_waits_for_started_owned_board_then_uses_current_chair(self):
        self.vm.execute('''
            setPet(record,"dog",5);setPet(record,"dog",5)
            assert(spawned==0 and record.waiting=="Cabin game start")
            local waiting=0
            for _,message in ipairs(messages) do
                if message:find("waiting for Cabin game start",1,true) then waiting=waiting+1 end
            end
            assert(waiting==1)
            board.destroying=true;board.GameStarted=true;setPet(record,"dog",5)
            assert(spawned==0)
            board.destroying=false
            function board:GetWorld() return object(99) end
            setPet(record,"dog",5);assert(spawned==0)
            function board:GetWorld() return world end
            function board:HasAuthority() return false end
            setPet(record,"dog",5);assert(spawned==0)
            function board:HasAuthority() return true end
            pawn.Chair=nil;setPet(record,"dog",5)
            assert(spawned==0 and record.waiting=="assigned Cabin chair")
            pawn.Chair=chair;setPet(record,"dog",5)
            assert(spawned==1 and requested.X==-65 and requested.Y==130 and requested.Z==315)
            assert(record.waiting==nil and record.dog.id==5 and skins==1)
            board.GameStarted=false;setPet(record,"dog",5)
            assert(spawned==1 and skins==1)
        ''')

    def test_lobby_spawn_does_not_require_board(self):
        self.vm.execute('''
            local point=object(34)
            function point:K2_GetComponentLocation() return {X=7,Y=8,Z=9} end
            scene.DogSpawn=point;pawn.GameBoard=nil
            local lobby={pawn=pawn,pc=pc,scene=scene,inCabin=false,offset=75}
            setPet(lobby,"dog",5)
            assert(spawned==1 and requested.X==7 and requested.Y==83 and requested.Z==9)
        ''')


if __name__ == '__main__':
    unittest.main()
