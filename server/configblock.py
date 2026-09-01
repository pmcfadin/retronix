"""RetroNix config block v1 — pack/unpack of the machine's identity block.

One fixed-layout region per ROM template, stamped by the foundry and read by
the BIOS at cold boot (ADR-0006, design.md "Config block v1 layout"). This
module is the single importable source of the field offsets: task 3.1 pins
`machine/config.inc`'s assembler constants against the values here, so the
two must never be edited independently.

The checksum is the wire's rule reused verbatim (see `protocol.checksum`):
two's complement of the 8-bit sum of the defined bytes, so summing the whole
defined block (checksum byte included) yields zero.
"""
from __future__ import annotations

import protocol as p

MAGIC = b"RNXC"
BLOCK_VERSION = 1

# Platform ids (design.md's table).
PLATFORM_ALTAIR = 0x01  # MITS Altair 8800 / M2SIO ACIA
PLATFORM_MODEL4 = 0x02  # TRS-80 Model 4 / TR1865

# Profile state at mint time.
STATE_PROBE = 0x00
STATE_EXACT = 0x01

# -- field offsets, from the block's own base ---------------------------
# design.md's table, verbatim. Every offset and length below is normative;
# do not derive one from another so a table row can be checked against this
# module line by line.
OFF_MAGIC = 0x000
LEN_MAGIC = 4
OFF_VERSION = 0x004
LEN_VERSION = 1
OFF_PLATFORM = 0x005
LEN_PLATFORM = 1
OFF_MACHINE_ID = 0x006
LEN_MACHINE_ID = 4
OFF_LINK = 0x00A
LEN_LINK = 8
OFF_MAP_COUNT = 0x012
LEN_MAP_COUNT = 1
OFF_STATE = 0x013
LEN_STATE = 1
OFF_RESERVED = 0x014
LEN_RESERVED = 12
OFF_MAP = 0x020
LEN_MAP = 320
OFF_CHECKSUM = 0x160
LEN_CHECKSUM = 1

# Bytes 0x000-0x160 inclusive (353 bytes) are defined; the checksum covers
# exactly this range. The template reserves BLOCK_RESERVED_LEN bytes at
# CFGBLK with the tail beyond BLOCK_DEFINED_LEN zero-filled, so a v2 block
# can grow without moving anything.
BLOCK_DEFINED_LEN = OFF_CHECKSUM + LEN_CHECKSUM  # 0x161 = 353
BLOCK_RESERVED_LEN = 512

# -- the cached drive map: DMAP's own shape (machine/bios.asm) ----------
# DMAPN entries of DENTSZ bytes: drive index, kind, flags, name length,
# DNAMEL name bytes. Preloading the retained map is a 320-byte block copy,
# not a parse, because this is exactly what DMAP already looks like.
DMAPN = 16    # CP/M has exactly sixteen drive letters
DENTSZ = 20   # drive, kind, flags, name length, DNAMEL name bytes
DNAMEL = 16   # name field width inside one DENTSZ entry

DRIVE_LETTERS = "ABCDEFGHIJKLMNOP"

# Map-entry "kind" byte — mirrors the HELLO response's own entry kind
# (server/protocol.py doc, machine/protocol.inc): 0 is the only kind
# defined in v0, "network".
MAP_KIND_NETWORK = 0x00

# Read-only flag bit, same encoding as the HELLO response entry flags.
MAP_FLAG_READONLY = 0x01

assert OFF_MAP + LEN_MAP == OFF_CHECKSUM, "map field must run right up to the checksum byte"
assert DMAPN * DENTSZ == LEN_MAP, "DMAPN * DENTSZ must equal the map field's length"


class BlockError(Exception):
    """Raised when a block cannot be packed from, or is malformed for, the
    given inputs — never a bare traceback."""


def pack_map_entry(drive_index: int, kind: int, flags: int, name: str) -> bytes:
    """One DENTSZ-byte cached-map entry."""
    if not 0 <= drive_index < DMAPN:
        raise BlockError(f"drive index {drive_index} outside 0..{DMAPN - 1}")
    raw = name.encode("ascii")
    if len(raw) > DNAMEL:
        raise BlockError(f"volume name {name!r} longer than {DNAMEL} bytes")
    return bytes((drive_index, kind & 0xFF, flags & 0xFF, len(raw))) + raw.ljust(DNAMEL, b"\x00")


def compute_checksum(block: bytes) -> int:
    """The checksum byte's value for a block whose defined bytes up to (but
    not including) OFF_CHECKSUM are already filled in."""
    return p.checksum(bytes(block[:OFF_CHECKSUM]))


def verify_checksum(block: bytes) -> bool:
    """True iff summing the whole defined region (checksum included) is 0."""
    if len(block) < BLOCK_DEFINED_LEN:
        return False
    return sum(block[:BLOCK_DEFINED_LEN]) & 0xFF == 0


def pack(*, machine_id: int, platform_id: int, link: bytes,
          map_entries: list[bytes], state: int) -> bytes:
    """Pack a full CFGBLK: BLOCK_RESERVED_LEN bytes, zero-padded, checksummed.

    `map_entries` is a list of already-packed DENTSZ-byte entries (see
    `pack_map_entry`), at most DMAPN of them.
    """
    if not 0 <= machine_id <= 0xFFFFFFFF:
        raise BlockError(f"machine id {machine_id} out of 32-bit range")
    if not 0 <= platform_id <= 0xFF:
        raise BlockError(f"platform id {platform_id} out of byte range")
    if len(link) != LEN_LINK:
        raise BlockError(f"link config must be {LEN_LINK} bytes, got {len(link)}")
    if len(map_entries) > DMAPN:
        raise BlockError(f"more than {DMAPN} map entries")
    for i, entry in enumerate(map_entries):
        if len(entry) != DENTSZ:
            raise BlockError(f"map entry {i} must be {DENTSZ} bytes, got {len(entry)}")
    if state not in (STATE_PROBE, STATE_EXACT):
        raise BlockError(f"unknown profile state byte {state!r}")

    block = bytearray(BLOCK_RESERVED_LEN)
    block[OFF_MAGIC:OFF_MAGIC + LEN_MAGIC] = MAGIC
    block[OFF_VERSION] = BLOCK_VERSION
    block[OFF_PLATFORM] = platform_id
    block[OFF_MACHINE_ID:OFF_MACHINE_ID + LEN_MACHINE_ID] = machine_id.to_bytes(4, "little")
    block[OFF_LINK:OFF_LINK + LEN_LINK] = link
    block[OFF_MAP_COUNT] = len(map_entries)
    block[OFF_STATE] = state
    # OFF_RESERVED .. +LEN_RESERVED stays zero.
    map_bytes = b"".join(map_entries).ljust(LEN_MAP, b"\x00")
    block[OFF_MAP:OFF_MAP + LEN_MAP] = map_bytes
    block[OFF_CHECKSUM] = compute_checksum(bytes(block))
    return bytes(block)


def unpack(block: bytes) -> dict:
    """Parse a block's defined fields. Raises BlockError if too short.

    Does not itself validate magic/version/checksum — call `verify_checksum`
    and check `magic`/`version` on the result for that; a template's
    unstamped block (all zero, or garbage) is expected to unpack fine and
    simply fail those checks, which is the honest "unreadable" path.
    """
    if len(block) < BLOCK_DEFINED_LEN:
        raise BlockError(f"block shorter than {BLOCK_DEFINED_LEN} defined bytes")
    machine_id = int.from_bytes(block[OFF_MACHINE_ID:OFF_MACHINE_ID + LEN_MACHINE_ID], "little")
    map_count = block[OFF_MAP_COUNT]
    entries = []
    for i in range(min(map_count, DMAPN)):
        raw = block[OFF_MAP + i * DENTSZ: OFF_MAP + (i + 1) * DENTSZ]
        drive_index, kind, flags, name_len = raw[0], raw[1], raw[2], raw[3]
        name = raw[4:4 + name_len].decode("ascii", errors="replace")
        entries.append({"drive_index": drive_index, "kind": kind,
                        "flags": flags, "name": name})
    return {
        "magic": bytes(block[OFF_MAGIC:OFF_MAGIC + LEN_MAGIC]),
        "version": block[OFF_VERSION],
        "platform_id": block[OFF_PLATFORM],
        "machine_id": machine_id,
        "link": bytes(block[OFF_LINK:OFF_LINK + LEN_LINK]),
        "map_count": map_count,
        "state": block[OFF_STATE],
        "map_entries": entries,
        "checksum": block[OFF_CHECKSUM],
    }


# File offset of CFGBLK from the start of each platform's ROM template.
# Altair: build/retronix.bin is assembled from `org 0` (the CP/M page-zero
# vectors) through the monitor body, and the harness loads it at address 0
# (`load <image> 0`), so file offset == CPU address throughout. `org
# 0E000h` holds a jump to the relocated monitor; the block itself sits at
# 0E100h (design.md "Where the block lives", machine/config.inc's CFGBLK),
# so its file offset is 0xE100 — task 3.1 fixed a stale 0x100 here that
# predated the real build and would have stamped into the middle of the
# TPA.
#
# Model 4 (task 4.4, machine/bios_m4.asm): build/retronix-m4.bin is also
# loaded at CPU address 0 (trs80gp's `-rom`), so file offset == address
# there too. The reset vector (3 bytes) is followed by the block at file
# offset 0x100, reserved for CB_RESLEN (512) bytes; the relocator body
# begins right after it, at file offset 0x300, and is copied whole into RAM
# above 4000h before the memory map switches — the block survives that copy
# at RAM address 0x4000+0x100 = 0x4100 (bios_m4.asm's CFGBLK_RT). Proved by
# an isolated relocation-only build (build/probe/m4reloc.asm) before the
# rest of the template was written, and confirmed again end-to-end (mint,
# boot, HELLO) against this exact offset.
TEMPLATE_BLOCK_OFFSET = {
    PLATFORM_ALTAIR: 0xE100,
    PLATFORM_MODEL4: 0x100,
}
