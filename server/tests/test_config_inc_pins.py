"""Pins machine/config.inc's assembler constants against the Python
stamper's (task 3.1). The two files describe the same config block layout
in two languages — this test is what keeps them from drifting apart
silently, the way server/protocol.py and machine/protocol.inc are already
required to agree (ADR-0003).
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import configblock as cb

ROOT = Path(__file__).resolve().parents[2]
CONFIG_INC = ROOT / "machine" / "config.inc"

# Matches a zmac `equ` line: NAME  equ  VALUE[h], with an optional trailing
# comment. Values are either a bare decimal integer or a hex literal with
# the assembler's trailing 'h' suffix (e.g. 0E100h, 020h).
EQU_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+([0-9][0-9A-Fa-f]*[Hh]|\d+)\s*(?:;.*)?$"
)


def parse_equates(path: Path) -> dict[str, int]:
    equates: dict[str, int] = {}
    for line in path.read_text().splitlines():
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        m = EQU_RE.match(line.strip())
        if not m:
            continue
        name, raw = m.groups()
        if raw[-1] in "Hh":
            value = int(raw[:-1], 16)
        else:
            value = int(raw)
        equates[name] = value
    return equates


class ConfigIncPinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eq = parse_equates(CONFIG_INC)

    def test_file_parsed_something(self):
        # A parser that silently matched nothing would make every other
        # assertion in this file vacuously true.
        self.assertGreater(len(self.eq), 15)

    def test_block_version_and_platform_ids(self):
        self.assertEqual(self.eq["CFG_VERSION"], cb.BLOCK_VERSION)
        self.assertEqual(self.eq["CFG_PLAT_ALTAIR"], cb.PLATFORM_ALTAIR)
        self.assertEqual(self.eq["CFG_PLAT_MODEL4"], cb.PLATFORM_MODEL4)
        self.assertEqual(self.eq["CFG_ST_PROBE"], cb.STATE_PROBE)
        self.assertEqual(self.eq["CFG_ST_EXACT"], cb.STATE_EXACT)

    def test_offsets_match_configblock(self):
        self.assertEqual(self.eq["CFG_OFF_MAGIC"], cb.OFF_MAGIC)
        self.assertEqual(self.eq["CFG_LEN_MAGIC"], cb.LEN_MAGIC)
        self.assertEqual(self.eq["CFG_OFF_VERSION"], cb.OFF_VERSION)
        self.assertEqual(self.eq["CFG_LEN_VERSION"], cb.LEN_VERSION)
        self.assertEqual(self.eq["CFG_OFF_PLATFORM"], cb.OFF_PLATFORM)
        self.assertEqual(self.eq["CFG_LEN_PLATFORM"], cb.LEN_PLATFORM)
        self.assertEqual(self.eq["CFG_OFF_MACHID"], cb.OFF_MACHINE_ID)
        self.assertEqual(self.eq["CFG_LEN_MACHID"], cb.LEN_MACHINE_ID)
        self.assertEqual(self.eq["CFG_OFF_LINK"], cb.OFF_LINK)
        self.assertEqual(self.eq["CFG_LEN_LINK"], cb.LEN_LINK)
        self.assertEqual(self.eq["CFG_OFF_MAPCNT"], cb.OFF_MAP_COUNT)
        self.assertEqual(self.eq["CFG_LEN_MAPCNT"], cb.LEN_MAP_COUNT)
        self.assertEqual(self.eq["CFG_OFF_STATE"], cb.OFF_STATE)
        self.assertEqual(self.eq["CFG_LEN_STATE"], cb.LEN_STATE)
        self.assertEqual(self.eq["CFG_OFF_RESVD"], cb.OFF_RESERVED)
        self.assertEqual(self.eq["CFG_LEN_RESVD"], cb.LEN_RESERVED)
        self.assertEqual(self.eq["CFG_OFF_MAP"], cb.OFF_MAP)
        self.assertEqual(self.eq["CFG_LEN_MAP"], cb.LEN_MAP)
        self.assertEqual(self.eq["CFG_OFF_CKSUM"], cb.OFF_CHECKSUM)
        self.assertEqual(self.eq["CFG_LEN_CKSUM"], cb.LEN_CHECKSUM)

    def test_defined_and_reserved_lengths(self):
        self.assertEqual(self.eq["CFGBLKLEN"], cb.BLOCK_DEFINED_LEN)
        self.assertEqual(self.eq["CFGBLKRES"], cb.BLOCK_RESERVED_LEN)

    def test_block_base_matches_template_offset(self):
        # CFGBLK is an absolute CPU address; build/retronix.bin is loaded
        # at address 0 (harness/run_proof.py: `load <image> 0`), so file
        # offset == CPU address for the Altair image, and CFGBLK must equal
        # the stamper's Altair file offset exactly (task 3.1, task 3.7).
        self.assertEqual(self.eq["CFGBLK"], 0xE100)
        self.assertEqual(self.eq["CFGBLK"], cb.TEMPLATE_BLOCK_OFFSET[cb.PLATFORM_ALTAIR])

    def test_map_field_runs_up_to_checksum(self):
        self.assertEqual(self.eq["CFG_OFF_MAP"] + self.eq["CFG_LEN_MAP"],
                         self.eq["CFG_OFF_CKSUM"])

    def test_block_fits_exactly_between_cfgblk_and_the_relocated_body(self):
        # design.md "Where the block lives": CFGBLK at 0E100h, body at
        # 0E300h -- the reserved region must span the gap exactly, with no
        # slack and no overlap.
        self.assertEqual(self.eq["CFGBLK"] + self.eq["CFGBLKRES"], 0xE300)


if __name__ == "__main__":
    unittest.main()
