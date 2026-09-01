import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import machine_store as ms
import reconcile as rc

ROM = (0, 3, 0)


def fresh_profile(**overrides):
    p = ms.new_profile(machine_id=1001, make="MITS", model="Altair 8800",
                       notes="", platform="altair-m2sio",
                       rom_template="build/retronix.bin",
                       link={"port_base": 16, "reset": 3, "mode": 21, "baud": 0},
                       drive_map={"A": "library"})
    p.update(overrides)
    return p


def minted(profile, *, rom_version="0.3.0"):
    """A profile as it looks right after `mint` — stamped snapshot taken,
    needs_remint clear, state back to probe until a HELLO agrees."""
    profile = copy.deepcopy(profile)
    profile["mint"] = {
        "block_checksum": 0x42, "block_sha256": "deadbeef",
        "minted_at": "2026-08-31T00:00:00Z", "rom_version": rom_version,
        "stamped": {"link": copy.deepcopy(profile["link"]),
                    "drive_map": copy.deepcopy(profile["drive_map"])},
    }
    profile["needs_remint"] = False
    profile["state"] = "probe"
    return profile


class UnexpectedFactTests(unittest.TestCase):
    def test_unexpected_ram_refines_and_flags_remint(self):
        p = minted(fresh_profile())  # declared ram_kb still 0 (unspecified)
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=1.0)
        self.assertEqual(p["hardware"]["observed"]["ram_kb"], 63)
        self.assertTrue(p["needs_remint"])
        self.assertEqual(p["state"], "probe")

    def test_declared_mismatch_flags_remint(self):
        p = fresh_profile(hardware={
            "declared": {"cpu": 0, "ram_kb": 64, "console": 0},
            "observed": {"cpu": None, "ram_kb": None, "console": None,
                         "rom_version": None, "last_seen": None}})
        p = minted(p)
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=48, now=1.0)
        self.assertTrue(p["needs_remint"])
        self.assertEqual(p["hardware"]["observed"]["ram_kb"], 48)


class ExactnessTests(unittest.TestCase):
    def test_matching_boot_is_exact(self):
        p = fresh_profile(hardware={
            "declared": {"cpu": 0, "ram_kb": 63, "console": 0},
            "observed": {"cpu": None, "ram_kb": None, "console": None,
                         "rom_version": None, "last_seen": None}})
        p = minted(p, rom_version="0.3.0")
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=1.0)
        self.assertFalse(p["needs_remint"])
        self.assertEqual(p["state"], "exact")

    def test_never_minted_profile_cannot_be_exact(self):
        p = fresh_profile(hardware={
            "declared": {"cpu": 0, "ram_kb": 63, "console": 0},
            "observed": {"cpu": None, "ram_kb": None, "console": None,
                         "rom_version": None, "last_seen": None}})
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=1.0)
        self.assertTrue(p["needs_remint"])
        self.assertEqual(p["state"], "probe")

    def test_rom_version_mismatch_flags_remint(self):
        p = fresh_profile(hardware={
            "declared": {"cpu": 0, "ram_kb": 63, "console": 0},
            "observed": {"cpu": None, "ram_kb": None, "console": None,
                         "rom_version": None, "last_seen": None}})
        p = minted(p, rom_version="0.2.0")
        rc.reconcile_hello(p, rom_version=(0, 3, 0), cpu=0, ram_kb=63, now=1.0)
        self.assertTrue(p["needs_remint"])


class DriftTests(unittest.TestCase):
    def test_edited_drive_map_after_mint_is_drift(self):
        p = fresh_profile(hardware={
            "declared": {"cpu": 0, "ram_kb": 63, "console": 0},
            "observed": {"cpu": None, "ram_kb": None, "console": None,
                         "rom_version": None, "last_seen": None}})
        p = minted(p, rom_version="0.3.0")
        # An edit made after minting: drive map now differs from what was
        # stamped.
        p["drive_map"] = {"A": "library", "C": "scratch"}
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=1.0)
        self.assertTrue(p["needs_remint"])

    def test_edited_link_after_mint_is_drift(self):
        p = fresh_profile(hardware={
            "declared": {"cpu": 0, "ram_kb": 63, "console": 0},
            "observed": {"cpu": None, "ram_kb": None, "console": None,
                         "rom_version": None, "last_seen": None}})
        p = minted(p, rom_version="0.3.0")
        p["link"] = {"port_base": 16, "reset": 3, "mode": 21, "baud": 1}
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=1.0)
        self.assertTrue(p["needs_remint"])

    def test_remint_after_drift_clears_and_agreement_becomes_exact(self):
        p = fresh_profile(hardware={
            "declared": {"cpu": 0, "ram_kb": 63, "console": 0},
            "observed": {"cpu": None, "ram_kb": None, "console": None,
                         "rom_version": None, "last_seen": None}})
        p = minted(p, rom_version="0.3.0")
        p["drive_map"] = {"A": "library", "C": "scratch"}
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=1.0)
        self.assertTrue(p["needs_remint"])
        # Re-mint: stamped snapshot catches up with the edited map.
        p["mint"]["stamped"]["drive_map"] = dict(p["drive_map"])
        p["needs_remint"] = False
        p["state"] = "probe"
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=2.0)
        self.assertFalse(p["needs_remint"])
        self.assertEqual(p["state"], "exact")


class IdempotenceTests(unittest.TestCase):
    def test_two_identical_hellos_leave_one_profile(self):
        p = fresh_profile(hardware={
            "declared": {"cpu": 0, "ram_kb": 63, "console": 0},
            "observed": {"cpu": None, "ram_kb": None, "console": None,
                         "rom_version": None, "last_seen": None}})
        p = minted(p, rom_version="0.3.0")
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=5.0)
        after_first = copy.deepcopy(p)
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=5.0)
        self.assertEqual(p, after_first)

    def test_idempotent_while_needs_remint(self):
        p = minted(fresh_profile())
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=5.0)
        after_first = copy.deepcopy(p)
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=5.0)
        self.assertEqual(p, after_first)


class NeverMutatesIdentityTests(unittest.TestCase):
    def test_identity_map_link_mint_untouched(self):
        p = minted(fresh_profile())
        before = copy.deepcopy(p)
        rc.reconcile_hello(p, rom_version=ROM, cpu=0, ram_kb=63, now=1.0)
        self.assertEqual(p["machine_id"], before["machine_id"])
        self.assertEqual(p["identity"], before["identity"])
        self.assertEqual(p["platform"], before["platform"])
        self.assertEqual(p["rom_template"], before["rom_template"])
        self.assertEqual(p["link"], before["link"])
        self.assertEqual(p["drive_map"], before["drive_map"])
        self.assertEqual(p["mint"], before["mint"])
        self.assertEqual(p["hardware"]["declared"], before["hardware"]["declared"])


if __name__ == "__main__":
    unittest.main()
