import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import configblock as cb


def sample_block(machine_id=1002, map_count=2) -> bytes:
    entries = [
        cb.pack_map_entry(0, cb.MAP_KIND_NETWORK, cb.MAP_FLAG_READONLY, "library"),
        cb.pack_map_entry(2, cb.MAP_KIND_NETWORK, 0x00, "scratch"),
    ][:map_count]
    link = bytes((0x10, 0x03, 0x15, 0x00, 0, 0, 0, 0))
    return cb.pack(machine_id=machine_id, platform_id=cb.PLATFORM_ALTAIR,
                    link=link, map_entries=entries, state=cb.STATE_PROBE)


class LayoutTests(unittest.TestCase):
    """Pins the offsets design.md's table names — task 3.1 checks the
    assembler's CFGBLK constants against these same values."""

    def test_offsets_match_design_table(self):
        self.assertEqual(cb.OFF_MAGIC, 0x000)
        self.assertEqual(cb.OFF_VERSION, 0x004)
        self.assertEqual(cb.OFF_PLATFORM, 0x005)
        self.assertEqual(cb.OFF_MACHINE_ID, 0x006)
        self.assertEqual(cb.OFF_LINK, 0x00A)
        self.assertEqual(cb.OFF_MAP_COUNT, 0x012)
        self.assertEqual(cb.OFF_STATE, 0x013)
        self.assertEqual(cb.OFF_RESERVED, 0x014)
        self.assertEqual(cb.OFF_MAP, 0x020)
        self.assertEqual(cb.OFF_CHECKSUM, 0x160)
        self.assertEqual(cb.LEN_MACHINE_ID, 4)
        self.assertEqual(cb.LEN_LINK, 8)
        self.assertEqual(cb.LEN_RESERVED, 12)
        self.assertEqual(cb.LEN_MAP, 320)
        self.assertEqual(cb.BLOCK_DEFINED_LEN, 0x161)

    def test_map_is_dmap_shaped(self):
        self.assertEqual(cb.DMAPN, 16)
        self.assertEqual(cb.DENTSZ, 20)
        self.assertEqual(cb.DMAPN * cb.DENTSZ, cb.LEN_MAP)


class RoundTripTests(unittest.TestCase):
    def test_pack_unpack_roundtrip(self):
        block = sample_block()
        self.assertEqual(len(block), cb.BLOCK_RESERVED_LEN)
        parsed = cb.unpack(block)
        self.assertEqual(parsed["magic"], cb.MAGIC)
        self.assertEqual(parsed["version"], cb.BLOCK_VERSION)
        self.assertEqual(parsed["platform_id"], cb.PLATFORM_ALTAIR)
        self.assertEqual(parsed["machine_id"], 1002)
        self.assertEqual(parsed["state"], cb.STATE_PROBE)
        self.assertEqual(parsed["map_count"], 2)
        self.assertEqual(parsed["map_entries"][0]["name"], "library")
        self.assertEqual(parsed["map_entries"][0]["drive_index"], 0)
        self.assertEqual(parsed["map_entries"][0]["flags"] & cb.MAP_FLAG_READONLY,
                         cb.MAP_FLAG_READONLY)
        self.assertEqual(parsed["map_entries"][1]["name"], "scratch")
        self.assertEqual(parsed["map_entries"][1]["drive_index"], 2)

    def test_reserved_tail_is_zero(self):
        block = sample_block()
        self.assertEqual(block[cb.BLOCK_DEFINED_LEN:], b"\x00" * (
            cb.BLOCK_RESERVED_LEN - cb.BLOCK_DEFINED_LEN))

    def test_machine_id_little_endian(self):
        block = cb.pack(machine_id=0x000003EA, platform_id=cb.PLATFORM_ALTAIR,
                         link=bytes(8), map_entries=[], state=cb.STATE_PROBE)
        self.assertEqual(block[cb.OFF_MACHINE_ID:cb.OFF_MACHINE_ID + 4],
                         b"\xea\x03\x00\x00")

    def test_empty_map(self):
        block = cb.pack(machine_id=1001, platform_id=cb.PLATFORM_ALTAIR,
                         link=bytes(8), map_entries=[], state=cb.STATE_EXACT)
        parsed = cb.unpack(block)
        self.assertEqual(parsed["map_count"], 0)
        self.assertEqual(parsed["map_entries"], [])


class ChecksumTests(unittest.TestCase):
    def test_defined_block_sums_to_zero(self):
        block = sample_block()
        self.assertTrue(cb.verify_checksum(block))
        self.assertEqual(sum(block[:cb.BLOCK_DEFINED_LEN]) & 0xFF, 0)

    def test_single_byte_mutation_breaks_checksum(self):
        block = bytearray(sample_block())
        for offset in range(cb.BLOCK_DEFINED_LEN):
            mutated = bytearray(block)
            mutated[offset] ^= 0x01
            self.assertFalse(
                cb.verify_checksum(bytes(mutated)),
                f"mutation at offset {offset:#x} did not break the checksum")

    def test_mutation_outside_defined_region_is_not_checked(self):
        # The reserved tail beyond the defined block is not covered by the
        # checksum by design — v2 fields can be added there without
        # invalidating v1 images that predate them.
        block = bytearray(sample_block())
        block[cb.BLOCK_DEFINED_LEN] ^= 0xFF
        self.assertTrue(cb.verify_checksum(bytes(block)))


class ValidationTests(unittest.TestCase):
    def test_rejects_oversize_machine_id(self):
        with self.assertRaises(cb.BlockError):
            cb.pack(machine_id=1 << 32, platform_id=cb.PLATFORM_ALTAIR,
                     link=bytes(8), map_entries=[], state=cb.STATE_PROBE)

    def test_rejects_bad_link_length(self):
        with self.assertRaises(cb.BlockError):
            cb.pack(machine_id=1001, platform_id=cb.PLATFORM_ALTAIR,
                     link=bytes(7), map_entries=[], state=cb.STATE_PROBE)

    def test_rejects_too_many_map_entries(self):
        entries = [cb.pack_map_entry(i % 16, 0, 0, "x") for i in range(17)]
        with self.assertRaises(cb.BlockError):
            cb.pack(machine_id=1001, platform_id=cb.PLATFORM_ALTAIR,
                     link=bytes(8), map_entries=entries, state=cb.STATE_PROBE)

    def test_rejects_overlong_volume_name(self):
        with self.assertRaises(cb.BlockError):
            cb.pack_map_entry(0, 0, 0, "x" * 17)

    def test_unpack_too_short_raises(self):
        with self.assertRaises(cb.BlockError):
            cb.unpack(b"\x00" * 10)


if __name__ == "__main__":
    unittest.main()
