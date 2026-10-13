"""Run the original mod entry and Settings model in separate Lua states."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest
from lupa.lua54 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
NAME=next((ROOT/'Mods').iterdir()).name
ID='cabin_chair_marker' if NAME=='CabinChairMarker' else 'cabin_lobby_pets'
FIELD='enabled' if NAME=='CabinChairMarker' else 'in_cabin'

class Transport:
    def __init__(self,bus):self.bus=bus
    def GetSharedVariable(self,key):return self.bus.get(key)
    def SetSharedVariable(self,key,value):
        if value is None:self.bus.pop(key,None)
        else:self.bus[key]=value

class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dist=ROOT/'dist';self.dist.mkdir(exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(dir=self.dist)
        self.folder=Path(self.temporary.name)
        self.scripts=self.folder/'Scripts'
        shutil.copytree(ROOT/'Mods'/NAME/'Scripts',self.scripts)
        self.path=self.scripts/'settings.lua'
        self.original=self.path.read_bytes()
        self.bus={}

    def tearDown(self):
        self.assertTrue(self.folder.resolve().is_relative_to(self.dist.resolve()))
        self.temporary.cleanup()

    def owner(self,transport=True,directory=None,authority=False):
        vm=LuaRuntime(unpack_returned_tuples=True)
        vm.globals().directory=(directory or self.scripts).as_posix()+'/'
        vm.globals().save_directory=self.folder.as_posix()+'/'
        vm.globals().ModRef=Transport(self.bus) if transport else None
        vm.execute('''
            messages={};function print(message) messages[#messages+1]=message end
            function ExecuteInGameThread(callback) callback() end
            function LoopAsync(delay,callback) tick=callback end
            keyBindings=0
            function RegisterKeyBind(key,callback) keyBindings=keyBindings+1 end
            function RegisterHook(path,callback) received=callback end
            function FindAllOf(class) return {} end
            function FName(name) return name end
            function object(address)
                local o={address=address,valid=true}
                function o:IsValid() return self.valid end;function o:GetAddress() return self.address end
                function o:GetFullName() return "fixture" end
                function o:HasAuthority() return isHost~=false end
                return o
            end
            world=object(7);scene=object(11);pawn=object(23);pc=object(24)
            function scene:GetWorld() return world end;function pawn:GetWorld() return world end
            pc.Pawn=pawn;pc.Player=object(25);pc.Player.PlayerController=pc;pawn.Controller=pc
            function pc:IsLocalController() return true end
            function pawn:AdditionalActorRep_E(actor,random,marker,value) sent=(sent or 0)+1;assert(marker==-2713701 and value.X==0 and value.Y==0 and value.Z==1) end
            library=object(99)
            function library:GetProjectSavedDirectory() return {ToString=function() return save_directory end} end
            nativeValid=setmetatable(object(100),{__call=function(_,system,value) return value:IsValid() end})
            function StaticFindObject(path) if path=="/Script/Engine.KismetSystemLibrary:IsValid" then return nativeValid end return library end
            function LoadAsset(path) return StaticFindObject(path) end
            originalOpen=io.open;petReads=0
            io.open=function(path,mode) if path:find("LobbyData.sav",1,true) then petReads=petReads+1 end return originalOpen(path,mode) end
        ''')
        if authority:
            vm.globals().host_request=(self.folder/'request.dat').as_posix()
            vm.execute('originalGetenv=os.getenv;os.getenv=function(key) if key=="CABIN_REJOIN_PROCESS_ID" then return "authority-fixture" elseif key=="CABIN_REJOIN_HOST_REQUEST_PATH" then return host_request end return originalGetenv(key) end')
        (self.folder/'SaveGames').mkdir(exist_ok=True)
        (self.folder/'SaveGames/LobbyData.sav').write_bytes(b'GVAS')
        vm.execute('function IterateGameDirectories() return {Game={Binaries={Win64={__absolute_path=save_directory}}}} end')
        vm.execute('api=assert(loadfile(directory.."main.lua"))()')
        if transport:
            self.assertIn('CabinModSettingsV1.'+ID+'.snapshot',self.bus,'\n'.join(str(value) for value in vm.globals().messages.values()))
        return vm

    def menu(self):
        vm=LuaRuntime(unpack_returned_tuples=True)
        vm.globals().directory=self.scripts.as_posix()
        vm.globals().fixtures=(ROOT/'tests/fixtures').as_posix()
        vm.globals().ModRef=Transport(self.bus)
        vm.globals().id=ID;vm.globals().field=FIELD
        vm.execute('package.path=fixtures.."/?.lua;"..directory.."/?.lua;"..package.path;function log() end;registry=require("cabin_registry").new(ModRef,log);panel=require("cabin_panel").new(registry,function() return 1 end);panel:open()')
        return vm

    def apply(self,owner,menu,value):
        menu.globals().candidate=value
        menu.execute('panel:edit(id,field,candidate);assert(panel:apply(id))')
        owner.execute('tick()')
        menu.execute('panel:poll()')

    def test_all_shipped_lua_compiles_and_legacy_defaults_register(self):
        vm=self.owner()
        compiler=vm.eval('function(text,name) return assert(load(text,name,"t",{})) end')
        for path in (ROOT/'Mods').rglob('*.lua'):compiler(path.read_text(encoding='utf-8'),str(path))
        menu=self.menu()
        menu.execute('assert(panel.drafts[id].values[field]==true)')
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_cancel_defaults_and_apply_restart(self):
        owner=self.owner();menu=self.menu()
        menu.execute('panel:edit(id,field,false);panel:defaults(id);assert(panel.drafts[id].values[field]==true);panel:cancel();panel:open()')
        self.assertEqual(self.path.read_bytes(),self.original)
        self.apply(owner,menu,False)
        menu.execute('assert(not panel.error and panel.drafts[id].values[field]==false)')
        saved=self.path.read_text(encoding='utf-8')
        for line in self.original.decode('utf-8').splitlines():
            if line.startswith('--'):self.assertIn(line,saved)
            elif line.strip():break
        self.assertFalse((self.scripts/'settings.dat').exists())
        self.bus.clear();self.owner();restarted=self.menu()
        restarted.execute('assert(panel.drafts[id].values[field]==false)')

    def test_write_failure_preserves_file_and_values(self):
        owner=self.owner();menu=self.menu()
        owner.execute('io.open=function(path,mode) if mode=="wb" then return nil,"injected disk full",13 end return originalOpen(path,mode) end')
        self.apply(owner,menu,False)
        menu.execute('assert(panel.error:find("injected disk full",1,true) and panel.drafts[id].snapshot.values[field]==true)')
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_failed_final_readback_rolls_back(self):
        owner=self.owner();menu=self.menu()
        owner.execute('''originalRename=os.rename;reject=false
            os.rename=function(a,b) local ok,cause=originalRename(a,b);if ok and a:sub(-8)==".pending" then reject=true end;return ok,cause end
            io.open=function(path,mode) if reject and path==directory.."settings.lua" and mode=="rb" then reject=false;return nil,"injected readback failure",13 end return originalOpen(path,mode) end''')
        self.apply(owner,menu,False)
        menu.execute('assert(panel.error:find("injected readback failure",1,true))')
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_extra_values_survive_apply_and_manual_edits_are_not_overwritten(self):
        text=self.original.decode('utf-8').replace('return {','return { note="keep",')
        self.path.write_text(text,encoding='utf-8',newline='\n')
        owner=self.owner();menu=self.menu();self.apply(owner,menu,False)
        owner.execute('assert(assert(loadfile(directory.."settings.lua"))().note=="keep")')
        manual=self.path.read_bytes()+b'\n-- manual edit\n'
        self.path.write_bytes(manual)
        menu.execute('panel:open()');self.apply(owner,menu,True)
        menu.execute('assert(panel.error:find("changed outside the panel",1,true))')
        self.assertEqual(self.path.read_bytes(),manual)

    def test_standalone_entry_keeps_original_controls(self):
        owner=self.owner(transport=False)
        owner.execute('tick();assert(#messages>0)')
        if NAME=='CabinChairMarker':owner.execute('assert(keyBindings==0 and api==nil)')
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_mod_specific_controls_and_host_scope(self):
        owner=self.owner();menu=self.menu()
        if NAME=='CabinChairMarker':
            owner.execute('assert(keyBindings==0 and api==nil)')
            menu.execute('panel:edit(id,"style","cross");panel:edit(id,"size",5);panel:edit(id,"seat",false);panel:edit(id,"back",false);assert(panel:apply(id))')
            owner.execute('tick()')
            menu.execute('panel:poll();assert(not panel.error and panel.drafts[id].values.style=="cross" and panel.drafts[id].values.size==5)')
            self.bus.clear();owner=self.owner();menu=self.menu()
            menu.execute('assert(panel.drafts[id].values.style=="cross" and panel.drafts[id].values.size==5 and not panel.drafts[id].values.seat and not panel.drafts[id].values.back)')
            for value in ['"invalid"','0/0','31']:
                menu.execute('panel:edit(id,"'+('style' if value=='"invalid"' else 'size')+'",'+value+');assert(not panel:apply(id) and panel.error);panel:open()')
        else:
            owner.execute('function FindAllOf(class) if class=="Cabin_PC_C" then return {pc} elseif class=="RealCabin_BP_C" then return {scene} end return {} end;tick();before=petReads;assert(before==1,table.concat(messages,"\\n"))')
            self.apply(owner,menu,False)
            owner.execute('assert(petReads==before+1);scene.valid=false;scene=object(12);function scene:GetWorld() return world end;tick();assert(petReads==before+1)')
            owner.execute('isHost=false;tick();assert(sent==1)')

    @unittest.skipUnless(NAME=='CabinLobbyPets','Cabin host settings only')
    def test_rejoin_authority_receives_and_acknowledges_host_value(self):
        owner=self.owner();menu=self.menu();self.apply(owner,menu,False)
        owner.execute('request=require("cabin_host_settings").publish("76561198000000000",function() end);assert(request.mods.cabin_lobby_pets.in_cabin==false);assert(not require("cabin_host_settings").acknowledged(request,"authority-fixture"))')
        self.bus={}
        authority_scripts=self.folder/'AuthorityScripts'
        shutil.copytree(ROOT/'Mods'/NAME/'Scripts',authority_scripts)
        (self.folder/'request.dat').write_text('schema=1\nowner_id=76561198000000000\n')
        authority=self.owner(directory=authority_scripts,authority=True)
        authority.execute('tick();assert(assert(loadfile(directory.."settings.lua"))().in_cabin==false)')
        owner.execute('assert(require("cabin_host_settings").acknowledged(request,"authority-fixture"));assert(not require("cabin_host_settings").acknowledged(request,"another-process"))')

if __name__=='__main__':unittest.main()
