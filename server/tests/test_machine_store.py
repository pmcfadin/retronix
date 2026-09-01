import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import machine_store as ms


def make_profile(machine_id=1001, **overrides):
    p = ms.new_profile(machine_id=machine_id, make="MITS", model="Altair 8800",
                       notes="", platform="altair-m2sio",
                       rom_template="build/retronix.bin",
                       link={"port_base": 16, "reset": 3, "mode": 21, "baud": 0},
                       drive_map={"A": "library"})
    p.update(overrides)
    return p


class StoreFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.machines_dir = Path(self.tmp.name) / "machines"

    def tearDown(self):
        self.tmp.cleanup()


class NewProfileShapeTests(unittest.TestCase):
    def test_born_probe_no_mint(self):
        p = make_profile()
        self.assertEqual(p["state"], "probe")
        self.assertFalse(p["needs_remint"])
        self.assertIsNone(p["mint"]["block_checksum"])
        self.assertIsNone(p["mint"]["stamped"])
        self.assertEqual(p["hardware"]["observed"]["ram_kb"], None)


class LoadSaveTests(StoreFixture):
    def test_roundtrip(self):
        p = make_profile()
        ms.save_profile(self.machines_dir, p)
        loaded = ms.load_profile(self.machines_dir, 1001)
        self.assertEqual(loaded, p)

    def test_missing_profile_is_none(self):
        self.assertIsNone(ms.load_profile(self.machines_dir, 9999))

    def test_missing_profile_creates_no_file(self):
        ms.load_profile(self.machines_dir, 9999)
        self.assertFalse((self.machines_dir / "9999.json").exists())

    def test_save_validates_before_writing(self):
        bad = make_profile()
        del bad["identity"]
        with self.assertRaises(ms.ProfileError):
            ms.save_profile(self.machines_dir, bad)
        self.assertFalse((self.machines_dir / "1001.json").exists())

    def test_malformed_file_raises_clear_message_not_traceback(self):
        self.machines_dir.mkdir(parents=True)
        (self.machines_dir / "1001.json").write_text("{not json")
        with self.assertRaises(ms.ProfileError) as ctx:
            ms.load_profile(self.machines_dir, 1001)
        self.assertIn("1001.json", str(ctx.exception))

    def test_missing_required_key_raises_clear_message(self):
        self.machines_dir.mkdir(parents=True)
        data = make_profile()
        del data["hardware"]
        (self.machines_dir / "1001.json").write_text(json.dumps(data))
        with self.assertRaises(ms.ProfileError) as ctx:
            ms.load_profile(self.machines_dir, 1001)
        self.assertIn("hardware", str(ctx.exception))

    def test_wrong_type_raises_clear_message(self):
        self.machines_dir.mkdir(parents=True)
        data = make_profile()
        data["needs_remint"] = "yes"
        (self.machines_dir / "1001.json").write_text(json.dumps(data))
        with self.assertRaises(ms.ProfileError) as ctx:
            ms.load_profile(self.machines_dir, 1001)
        self.assertIn("needs_remint", str(ctx.exception))


class ListProfilesTests(StoreFixture):
    def test_lists_sorted_by_id(self):
        ms.save_profile(self.machines_dir, make_profile(1002))
        ms.save_profile(self.machines_dir, make_profile(1001))
        ids = [p["machine_id"] for p in ms.list_profiles(self.machines_dir)]
        self.assertEqual(ids, [1001, 1002])

    def test_empty_store_lists_nothing(self):
        self.assertEqual(ms.list_profiles(self.machines_dir), [])

    def test_next_id_marker_is_not_a_profile(self):
        ms.allocate_machine_id(self.machines_dir)
        ms.save_profile(self.machines_dir, make_profile(1001))
        self.assertEqual(len(ms.list_profiles(self.machines_dir)), 1)


class MachineIdAssignmentTests(StoreFixture):
    def test_starts_at_1001(self):
        self.assertEqual(ms.allocate_machine_id(self.machines_dir), 1001)

    def test_sequential_assignment(self):
        first = ms.allocate_machine_id(self.machines_dir)
        second = ms.allocate_machine_id(self.machines_dir)
        self.assertEqual((first, second), (1001, 1002))
        mark = (self.machines_dir / ms.NEXT_ID_FILE).read_text().strip()
        self.assertEqual(mark, "1003")

    def test_mark_advances_before_any_profile_write(self):
        # Simulate a crash between allocation and profile creation: the
        # mark must already have moved.
        ms.allocate_machine_id(self.machines_dir)
        mark = (self.machines_dir / ms.NEXT_ID_FILE).read_text().strip()
        self.assertEqual(mark, "1002")
        self.assertEqual(ms.list_profiles(self.machines_dir), [])

    def test_retired_machine_id_not_recycled(self):
        first = ms.allocate_machine_id(self.machines_dir)
        second = ms.allocate_machine_id(self.machines_dir)
        ms.save_profile(self.machines_dir, make_profile(first))
        ms.save_profile(self.machines_dir, make_profile(second))
        # Retire the highest-numbered machine: delete its profile file.
        (self.machines_dir / f"{second}.json").unlink()
        third = ms.allocate_machine_id(self.machines_dir)
        self.assertEqual(third, second + 1)
        self.assertNotEqual(third, second)

    def test_next_id_never_derived_from_existing_files(self):
        # Files present go up to 1005, but the mark says 1002 next — the
        # mark wins, even though it disagrees with what's on disk.
        self.machines_dir.mkdir(parents=True)
        ms.save_profile(self.machines_dir, make_profile(1005))
        (self.machines_dir / ms.NEXT_ID_FILE).write_text("1002\n")
        self.assertEqual(ms.allocate_machine_id(self.machines_dir), 1002)


class ValidateProfileTests(unittest.TestCase):
    def test_valid_profile_passes(self):
        ms.validate_profile(make_profile())

    def test_bad_drive_letter_rejected(self):
        p = make_profile()
        p["drive_map"] = {"1": "library"}
        with self.assertRaises(ms.ProfileError):
            ms.validate_profile(p)

    def test_bad_state_rejected(self):
        p = make_profile()
        p["state"] = "unsure"
        with self.assertRaises(ms.ProfileError):
            ms.validate_profile(p)

    def test_unsupported_schema_rejected(self):
        p = make_profile()
        p["schema"] = 2
        with self.assertRaises(ms.ProfileError):
            ms.validate_profile(p)


if __name__ == "__main__":
    unittest.main()
