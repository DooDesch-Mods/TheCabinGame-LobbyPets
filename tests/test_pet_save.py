"""Check the native integer pet map, including the store's None value."""
from pathlib import Path
import struct
import unittest

from lupa.lua54 import LuaError, LuaRuntime


ROOT = Path(__file__).resolve().parents[1]


def fstring(value):
    data = value.encode("ascii") + b"\0"
    return struct.pack("<i", len(data)) + data


TAG = (fstring("Chosen_Pet_Skins") + fstring("MapProperty")
       + struct.pack("<i", 2) + fstring("IntProperty")
       + struct.pack("<i", 0) + fstring("IntProperty") + struct.pack("<i", 0))


def saved_map(entries, *, flags=0, removed=0, count=None, size=None):
    payload = struct.pack("<ii", removed, len(entries) if count is None else count)
    payload += b"".join(struct.pack("<ii", kind, skin) for kind, skin in entries)
    return b"GVAS" + TAG + struct.pack("<iB", len(payload) if size is None else size, flags) + payload


class PetSaveTests(unittest.TestCase):
    def setUp(self):
        self.vm = LuaRuntime(encoding=None, unpack_returned_tuples=True)
        module = self.vm.execute((ROOT / "Mods/CabinLobbyPets/Scripts/pet-save.lua").read_bytes())
        self.decode = module[b"decode"]

    def test_native_none_in_either_group_and_mixed_selection(self):
        for entries, expected in [([(1, 0)], (0, 0)), ([(2, 0)], (0, 0)),
                                  ([(1, 0), (2, 0)], (0, 0)),
                                  ([(1, 0), (2, 3)], (0, 3)),
                                  ([(2, 0), (1, 4)], (4, 0))]:
            with self.subTest(entries=entries):
                self.assertEqual(self.decode(saved_map(entries)), expected)

    def test_existing_skins_empty_map_and_absent_property(self):
        for cat in (1, 2, 4):
            for dog in (3, 5, 6):
                self.assertEqual(self.decode(saved_map([(1, cat), (2, dog)])), (cat, dog))
        self.assertEqual(self.decode(saved_map([])), (0, 0))
        self.assertEqual(self.decode(b"GVAS"), (0, 0))

    def test_negative_unknown_and_wrong_group_ids_fail(self):
        for entries in [[(1, -1)], [(2, -1)], [(1, 3)], [(2, 1)],
                        [(1, 7)], [(2, 7)], [(0, 0)], [(3, 0)]]:
            with self.subTest(entries=entries):
                with self.assertRaisesRegex(LuaError, "invalid or duplicate selected pet"):
                    self.decode(saved_map(entries))

    def test_none_does_not_hide_duplicate_groups(self):
        for entries in [[(1, 0), (1, 1)], [(1, 1), (1, 0)],
                        [(1, 0), (1, 0)], [(2, 0), (2, 3)], [(2, 0), (2, 0)]]:
            with self.subTest(entries=entries):
                with self.assertRaisesRegex(LuaError, "invalid or duplicate selected pet"):
                    self.decode(saved_map(entries))

    def test_malformed_map_stays_an_error(self):
        cases = [(saved_map([(1, 0)], flags=1), "unsupported pet property flags"),
                 (saved_map([(1, 0)], removed=1), "invalid pet map entry count"),
                 (saved_map([(1, 0)], count=0), "invalid pet map entry count"),
                 (saved_map([(1, 0)], size=7), "invalid pet map payload size"),
                 (saved_map([(1, 0)])[:-1], "invalid pet map payload size"),
                 (b"GVASChosen_Pet_Skins", "unsupported pet map schema"),
                 (b"NOPE", "LobbyData is not an Unreal save")]
        for data, cause in cases:
            with self.subTest(cause=cause):
                with self.assertRaisesRegex(LuaError, cause):
                    self.decode(data)


if __name__ == "__main__":
    unittest.main()
