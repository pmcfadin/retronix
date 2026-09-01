"""server/foundry.py — the operator CLI for machine profiles (task 2.4).

`new` / `list` / `show` / `mint`. Splitting write (foundry) from read (the
running server) is ADR-0006 + design.md's "The foundry is a CLI; the server
is a reader": every profile edit happens here, so the server never has to
arbitrate concurrent edits and the store stays diff-able in git. The one
exception — HELLO reconciliation's narrow write of observed facts and
needs_remint — is server/reconcile.py, not this file.

`mint` is copy-then-stamp: no assembler runs on this path (ADR-0006). It
copies the profile's ROM template byte for byte and rewrites only the
reserved config block (server/configblock.py).
"""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import pathlib
import sys

import configblock as cb
import machine_store as ms

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_MACHINES_DIR = pathlib.Path(__file__).parent / "machines"
DEFAULT_VOLUMES_FILE = pathlib.Path(__file__).parent / "volumes.json"
DEFAULT_MINT_DIR = ROOT / "build" / "mint"

DRIVE_LETTERS = cb.DRIVE_LETTERS

# Platform catalog: name -> block platform id, default rom template, default
# link config.
PLATFORM_DEFAULTS = {
    "altair-m2sio": {
        "platform_id": cb.PLATFORM_ALTAIR,
        "rom_template": "build/retronix.bin",
        # port_base is WSTAT (machine/bios.asm); WDATA is port_base+1.
        "link": {"port_base": 0x12, "reset": 0x03, "mode": 0x15, "baud": 0x00},
    },
    "trs80-model4-tr1865": {
        "platform_id": cb.PLATFORM_MODEL4,
        "rom_template": "build/retronix-m4.bin",
        # port_base is the TR1865's base (machine/bios_m4.asm's WRSTP);
        # WBAUDP/WCTLP/WDATAP are port_base+1/+2/+3. reset is the (ignored)
        # value OUT to port_base; baud 0xEE is 9600 both ways (high nibble
        # transmit, low nibble receive); mode 0x6F is 8 data bits, DTR, RTS,
        # not-break -- the init sequence machine/bios_m4.asm's applyblk
        # programs in this order (reset, then baud, then mode), per the M3
        # research (docs/research/trs80-model4-emulation.md). Confirmed
        # against the real template by an end-to-end mint + boot + HELLO.
        "link": {"port_base": 0xE8, "reset": 0x00, "mode": 0x6F, "baud": 0xEE},
    },
}


class FoundryError(Exception):
    """Raised for an operator-facing failure — printed as a message, no
    traceback, from `main`."""


def load_volumes(path: pathlib.Path) -> dict:
    if not path.exists():
        raise FoundryError(f"volumes file not found: {path}")
    return json.loads(path.read_text())


# -- block building, shared by mint --------------------------------------

def pack_link(link: dict) -> bytes:
    return bytes((link.get("port_base", 0) & 0xFF, link.get("reset", 0) & 0xFF,
                  link.get("mode", 0) & 0xFF, link.get("baud", 0) & 0xFF,
                  0, 0, 0, 0))


def build_map_entries(drive_map: dict, volumes: dict) -> list[bytes]:
    entries = []
    for letter in sorted(drive_map):
        if letter.upper() not in DRIVE_LETTERS:
            raise FoundryError(f"drive letter {letter!r} is not A-P")
        vol_name = drive_map[letter]
        vol_spec = volumes.get(vol_name)
        if vol_spec is None:
            raise FoundryError(f"drive map names unknown volume {vol_name!r}")
        flags = cb.MAP_FLAG_READONLY if vol_spec.get("kind") == "shared" else 0x00
        drive_index = DRIVE_LETTERS.index(letter.upper())
        entries.append(cb.pack_map_entry(drive_index, cb.MAP_KIND_NETWORK, flags, vol_name))
    return entries


def build_block(profile: dict, volumes: dict) -> bytes:
    defaults = PLATFORM_DEFAULTS.get(profile["platform"])
    if defaults is None:
        raise FoundryError(f"unknown platform {profile['platform']!r}")
    link = pack_link(profile["link"])
    map_entries = build_map_entries(profile["drive_map"], volumes)
    state = cb.STATE_EXACT if profile.get("state") == "exact" else cb.STATE_PROBE
    return cb.pack(machine_id=profile["machine_id"], platform_id=defaults["platform_id"],
                    link=link, map_entries=map_entries, state=state)


# -- CLI verbs -------------------------------------------------------------

def cmd_new(args, machines_dir: pathlib.Path) -> int:
    defaults = PLATFORM_DEFAULTS.get(args.platform)
    if defaults is None:
        raise FoundryError(f"unknown platform {args.platform!r}; choices: "
                           f"{', '.join(sorted(PLATFORM_DEFAULTS))}")
    machine_id = ms.allocate_machine_id(machines_dir)
    drive_map = dict(entry.split("=", 1) for entry in (args.drive or []))
    profile = ms.new_profile(
        machine_id=machine_id, make=args.make, model=args.model,
        notes=args.notes or "", platform=args.platform,
        rom_template=args.rom_template or defaults["rom_template"],
        link=dict(defaults["link"]), drive_map=drive_map,
        declared={"cpu": args.cpu, "ram_kb": args.ram_kb, "console": args.console})
    ms.save_profile(machines_dir, profile)
    print(f"created machine {machine_id} ({args.make} {args.model}, {args.platform})")
    return 0


def cmd_list(args, machines_dir: pathlib.Path) -> int:
    profiles = ms.list_profiles(machines_dir)
    if not profiles:
        print("no machines in the store")
        return 0
    for prof in profiles:
        flag = " [needs-remint]" if prof["needs_remint"] else ""
        print(f"{prof['machine_id']:>5}  {prof['identity']['make']} "
              f"{prof['identity']['model']}  state={prof['state']}{flag}")
    return 0


def cmd_show(args, machines_dir: pathlib.Path) -> int:
    profile = ms.load_profile(machines_dir, args.machine_id)
    if profile is None:
        raise FoundryError(f"no profile for machine {args.machine_id}")
    flag = " *** NEEDS RE-MINT ***" if profile["needs_remint"] else ""
    print(f"machine {profile['machine_id']}: {profile['identity']['make']} "
          f"{profile['identity']['model']} ({profile['platform']})")
    print(f"  state: {profile['state']}{flag}")
    print(f"  drive map: {profile['drive_map']}")
    print(f"  link: {profile['link']}")
    print("  hardware:")
    print(f"    declared: {profile['hardware']['declared']}")
    print(f"    observed: {profile['hardware']['observed']}")
    print(f"  mint: {profile['mint']}")
    return 0


def cmd_mint(args, machines_dir: pathlib.Path) -> int:
    profile = ms.load_profile(machines_dir, args.machine_id)
    if profile is None:
        raise FoundryError(f"no profile for machine {args.machine_id}; mint refused")
    volumes = load_volumes(pathlib.Path(args.volumes_file))

    template_path = ROOT / profile["rom_template"]
    if not template_path.exists():
        raise FoundryError(f"rom template not found: {template_path}")
    template = template_path.read_bytes()

    defaults = PLATFORM_DEFAULTS.get(profile["platform"])
    if defaults is None:
        raise FoundryError(f"unknown platform {profile['platform']!r}")
    offset = cb.TEMPLATE_BLOCK_OFFSET[defaults["platform_id"]]
    if offset + cb.BLOCK_RESERVED_LEN > len(template):
        raise FoundryError(
            f"template {template_path} ({len(template)} bytes) too short for "
            f"the config block at offset {offset:#x}")

    block = build_block(profile, volumes)
    image = bytearray(template)
    image[offset:offset + cb.BLOCK_RESERVED_LEN] = block

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{profile['machine_id']}.bin"
    out_path.write_bytes(bytes(image))

    # "mint ... stamps the reconciled (observed) values" (design.md): every
    # hardware fact HELLO has actually observed since the last mint becomes
    # the new declared baseline. Fields never observed are left exactly as
    # the operator set them — mint is a foundry-CLI edit, same as `new`.
    observed = profile["hardware"]["observed"]
    for field in ("cpu", "ram_kb", "console"):
        if observed.get(field) is not None:
            profile["hardware"]["declared"][field] = observed[field]

    profile["mint"] = {
        "block_checksum": cb.compute_checksum(block),
        "block_sha256": hashlib.sha256(block).hexdigest(),
        "minted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rom_version": observed.get("rom_version"),
        "stamped": {"link": copy.deepcopy(profile["link"]),
                    "drive_map": copy.deepcopy(profile["drive_map"])},
    }
    profile["needs_remint"] = False
    # Minting does not confer exactness (design.md) — only a subsequent
    # agreeing HELLO does.
    profile["state"] = "probe"
    ms.save_profile(machines_dir, profile)

    print(f"minted machine {profile['machine_id']} -> {out_path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="foundry", description="RetroNix machine foundry")
    ap.add_argument("--machines-dir", default=str(DEFAULT_MACHINES_DIR))
    ap.add_argument("--volumes-file", default=str(DEFAULT_VOLUMES_FILE))
    sub = ap.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="create a profile and assign a machine id")
    p_new.add_argument("--make", required=True)
    p_new.add_argument("--model", required=True)
    p_new.add_argument("--platform", required=True, choices=sorted(PLATFORM_DEFAULTS))
    p_new.add_argument("--notes", default="")
    p_new.add_argument("--rom-template", default=None)
    p_new.add_argument("--drive", action="append", help="LETTER=volume, repeatable")
    p_new.add_argument("--cpu", type=int, default=0)
    p_new.add_argument("--ram-kb", type=int, default=0)
    p_new.add_argument("--console", type=int, default=0)

    sub.add_parser("list", help="list every profile in the store")

    p_show = sub.add_parser("show", help="show one profile in full")
    p_show.add_argument("machine_id", type=int)

    p_mint = sub.add_parser("mint", help="stamp a config block and write boot media")
    p_mint.add_argument("machine_id", type=int)
    p_mint.add_argument("--out-dir", default=str(DEFAULT_MINT_DIR))

    args = ap.parse_args(argv)
    machines_dir = pathlib.Path(args.machines_dir)

    handlers = {"new": cmd_new, "list": cmd_list, "show": cmd_show, "mint": cmd_mint}
    try:
        return handlers[args.command](args, machines_dir)
    except FoundryError as e:
        print(f"foundry: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
