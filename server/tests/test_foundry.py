import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import configblock as cb
import foundry
import machine_store as ms

# A small fake template, standing in for build/retronix.bin (task 2.4: "a
# small fake template file is fine, you do not need the real ROM"). It must
# be long enough to hold the block at the Altair offset plus the block's
# full reserved length, with room on both sides to prove template equality
# outside the block.
TEMPLATE_LEN = cb.TEMPLATE_BLOCK_OFFSET[cb.PLATFORM_ALTAIR] + cb.BLOCK_RESERVED_LEN + 64
FAKE_TEMPLATE = bytes(i & 0xFF for i in range(TEMPLATE_LEN))


def run_cli(argv) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = foundry.main(argv)
    return code, out.getvalue()


class FoundryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.machines_dir = root / "machines"
        self.volumes_file = root / "volumes.json"
        self.volumes_file.write_text(json.dumps({
            "library": {"path": "volumes/library", "kind": "shared"},
            "scratch": {"path": "volumes/scratch", "kind": "owned"},
        }))
        self.template_path = root / "template.bin"
        self.template_path.write_bytes(FAKE_TEMPLATE)
        self.out_dir = root / "mint"
        self.common = ["--machines-dir", str(self.machines_dir),
                       "--volumes-file", str(self.volumes_file)]

    def tearDown(self):
        self.tmp.cleanup()

    def new_profile(self, machine_id_hint="1001", drive="A=library", cpu=None, ram_kb=None):
        args = self.common + ["new", "--make", "MITS", "--model", "Altair 8800",
                              "--platform", "altair-m2sio",
                              "--rom-template", str(self.template_path)]
        if drive:
            args += ["--drive", drive]
        code, _ = run_cli(args)
        self.assertEqual(code, 0)

    def mint(self, machine_id):
        return run_cli(self.common + ["mint", str(machine_id), "--out-dir", str(self.out_dir)])


class NewListShowTests(FoundryFixture):
    def test_new_assigns_id_and_writes_probe_profile(self):
        code, out = run_cli(self.common + ["new", "--make", "MITS", "--model", "Altair 8800",
                                           "--platform", "altair-m2sio"])
        self.assertEqual(code, 0)
        self.assertIn("1001", out)
        profile = ms.load_profile(self.machines_dir, 1001)
        self.assertIsNotNone(profile)
        self.assertEqual(profile["state"], "probe")
        self.assertIsNone(profile["mint"]["block_checksum"])

    def test_list_surfaces_needs_remint(self):
        self.new_profile()
        profile = ms.load_profile(self.machines_dir, 1001)
        profile["needs_remint"] = True
        ms.save_profile(self.machines_dir, profile)
        code, out = run_cli(self.common + ["list"])
        self.assertEqual(code, 0)
        self.assertIn("needs-remint", out)

    def test_show_distinguishes_declared_and_observed(self):
        self.new_profile()
        code, out = run_cli(self.common + ["show", "1001"])
        self.assertEqual(code, 0)
        self.assertIn("declared", out)
        self.assertIn("observed", out)

    def test_show_unknown_machine_fails_cleanly(self):
        code, out = run_cli(self.common + ["show", "9999"])
        self.assertEqual(code, 1)


class MintTests(FoundryFixture):
    def test_mint_refuses_unknown_machine(self):
        code, _ = self.mint(4242)
        self.assertEqual(code, 1)
        self.assertFalse((self.out_dir / "4242.bin").exists())

    def test_mint_is_byte_deterministic(self):
        self.new_profile()
        self.mint(1001)
        first = (self.out_dir / "1001.bin").read_bytes()
        # Mint again from a profile with identical live fields (re-running
        # mint on an unchanged profile must reproduce the same image).
        self.mint(1001)
        second = (self.out_dir / "1001.bin").read_bytes()
        self.assertEqual(first, second)

    def test_template_equality_outside_the_block(self):
        self.new_profile()
        self.mint(1001)
        minted = (self.out_dir / "1001.bin").read_bytes()
        offset = cb.TEMPLATE_BLOCK_OFFSET[cb.PLATFORM_ALTAIR]
        self.assertEqual(minted[:offset], FAKE_TEMPLATE[:offset])
        self.assertEqual(minted[offset + cb.BLOCK_RESERVED_LEN:],
                         FAKE_TEMPLATE[offset + cb.BLOCK_RESERVED_LEN:])
        self.assertNotEqual(minted[offset:offset + cb.BLOCK_RESERVED_LEN],
                            FAKE_TEMPLATE[offset:offset + cb.BLOCK_RESERVED_LEN])

    def test_stamped_machine_id_matches_profile(self):
        self.new_profile()
        code, _ = run_cli(self.common + ["new", "--make", "x", "--model", "y",
                                         "--platform", "altair-m2sio",
                                         "--rom-template", str(self.template_path)])
        self.assertEqual(code, 0)  # this is machine 1002
        self.mint(1002)
        image = (self.out_dir / "1002.bin").read_bytes()
        offset = cb.TEMPLATE_BLOCK_OFFSET[cb.PLATFORM_ALTAIR]
        block = image[offset:offset + cb.BLOCK_RESERVED_LEN]
        parsed = cb.unpack(block)
        self.assertEqual(parsed["machine_id"], 1002)

    def test_stamped_block_verifies(self):
        self.new_profile()
        self.mint(1001)
        image = bytearray((self.out_dir / "1001.bin").read_bytes())
        offset = cb.TEMPLATE_BLOCK_OFFSET[cb.PLATFORM_ALTAIR]
        block = bytes(image[offset:offset + cb.BLOCK_RESERVED_LEN])
        self.assertTrue(cb.verify_checksum(block))
        mutated = bytearray(block)
        mutated[0] ^= 0xFF
        self.assertFalse(cb.verify_checksum(bytes(mutated)))

    def test_two_profiles_differ_only_inside_the_block(self):
        self.new_profile(drive="A=library")
        run_cli(self.common + ["new", "--make", "x", "--model", "y",
                               "--platform", "altair-m2sio",
                               "--rom-template", str(self.template_path),
                               "--drive", "A=scratch"])
        self.mint(1001)
        self.mint(1002)
        img1 = (self.out_dir / "1001.bin").read_bytes()
        img2 = (self.out_dir / "1002.bin").read_bytes()
        offset = cb.TEMPLATE_BLOCK_OFFSET[cb.PLATFORM_ALTAIR]
        self.assertEqual(img1[:offset], img2[:offset])
        self.assertEqual(img1[offset + cb.BLOCK_RESERVED_LEN:],
                         img2[offset + cb.BLOCK_RESERVED_LEN:])
        self.assertNotEqual(img1[offset:offset + cb.BLOCK_RESERVED_LEN],
                            img2[offset:offset + cb.BLOCK_RESERVED_LEN])
        b1 = cb.unpack(img1[offset:offset + cb.BLOCK_RESERVED_LEN])
        b2 = cb.unpack(img2[offset:offset + cb.BLOCK_RESERVED_LEN])
        self.assertEqual(b1["machine_id"], 1001)
        self.assertEqual(b2["machine_id"], 1002)
        self.assertEqual(b1["map_entries"][0]["name"], "library")
        self.assertEqual(b2["map_entries"][0]["name"], "scratch")

    def test_mint_records_checksum_and_time(self):
        self.new_profile()
        self.mint(1001)
        profile = ms.load_profile(self.machines_dir, 1001)
        self.assertIsNotNone(profile["mint"]["block_checksum"])
        self.assertIsNotNone(profile["mint"]["block_sha256"])
        self.assertIsNotNone(profile["mint"]["minted_at"])
        self.assertIsNotNone(profile["mint"]["stamped"])

    def test_mint_does_not_confer_exactness(self):
        self.new_profile()
        self.mint(1001)
        profile = ms.load_profile(self.machines_dir, 1001)
        self.assertEqual(profile["state"], "probe")
        self.assertFalse(profile["needs_remint"])

    def test_remint_clears_needs_remint_and_stamps_reconciled_values(self):
        self.new_profile()
        self.mint(1001)
        profile = ms.load_profile(self.machines_dir, 1001)
        profile["hardware"]["observed"] = {"cpu": 0, "ram_kb": 63, "console": None,
                                           "rom_version": "0.3.0", "last_seen": 1.0}
        profile["needs_remint"] = True
        ms.save_profile(self.machines_dir, profile)
        self.mint(1001)
        profile = ms.load_profile(self.machines_dir, 1001)
        self.assertFalse(profile["needs_remint"])
        self.assertEqual(profile["hardware"]["declared"]["ram_kb"], 63)
        self.assertEqual(profile["mint"]["rom_version"], "0.3.0")

    def test_template_too_short_is_a_clean_error(self):
        run_cli(self.common + ["new", "--make", "x", "--model", "y",
                               "--platform", "altair-m2sio",
                               "--rom-template", "no-such-template.bin"])
        code, _ = self.mint(1001)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
