"""RetroNix machine profile store: one JSON file per machine.

Layout and schema: design.md "Profile JSON schema (v1)". `server/machines/`
holds machine profiles and nothing else — volume definitions live in their
own file (see `retronix_server.load_volumes`). Every write here — `new`,
`save_profile` — is a foundry-CLI operation; the running server calls only
`load_profile` and the narrow `save_profile` a HELLO reconciliation performs
(server/reconcile.py), which touches nothing this module doesn't already
allow (the whole profile, written back whole).
"""
from __future__ import annotations

import json
import pathlib
import time

SCHEMA_VERSION = 1
NEXT_ID_START = 1001
NEXT_ID_FILE = ".next-id"

STATES = ("probe", "exact")


class ProfileError(Exception):
    """Raised on a malformed profile — always a clear message, never a
    bare traceback from a missing/mistyped key."""


def profile_path(machines_dir: pathlib.Path, machine_id: int) -> pathlib.Path:
    return machines_dir / f"{machine_id}.json"


def new_profile(*, machine_id: int, make: str, model: str, notes: str,
                platform: str, rom_template: str, link: dict,
                drive_map: dict | None = None,
                declared: dict | None = None) -> dict:
    """The schema-v1 shape a freshly `new`-ed profile carries: state
    `probe`, no mint state, `needs_remint` clear (design.md's example)."""
    return {
        "schema": SCHEMA_VERSION,
        "machine_id": machine_id,
        "identity": {"make": make, "model": model, "notes": notes},
        "platform": platform,
        "rom_template": rom_template,
        "link": dict(link),
        "drive_map": dict(drive_map or {}),
        "state": "probe",
        "hardware": {
            "declared": dict(declared or {"cpu": 0, "ram_kb": 0, "console": 0}),
            "observed": {"cpu": None, "ram_kb": None, "console": None,
                         "rom_version": None, "last_seen": None},
        },
        "mint": {"block_checksum": None, "block_sha256": None,
                 "minted_at": None, "rom_version": None, "stamped": None},
        "needs_remint": False,
    }


def _require(cond: bool, msg: str, context: str) -> None:
    if not cond:
        raise ProfileError(f"{context}: {msg}" if context else msg)


def _kind(*types: type):
    """A predicate: value is an instance of one of `types`."""
    return lambda v: isinstance(v, types)


def _optional(*types: type):
    """A predicate: value is None, or an instance of one of `types` —
    `hardware.observed.*` and `mint.*` are unset until something (a HELLO,
    a mint) actually sets them."""
    return lambda v: v is None or isinstance(v, types)


# One row per required field: a dotted path from the profile's root, the
# predicate its value must satisfy, and the type description that goes in
# the error message ("`path` must be `want`"). Order matters — a container
# is checked before anything nested inside it, so by the time a child row
# runs, every ancestor in its path is already known to be the right shape
# and `_get_path` can walk straight to it. `drive_map`'s own entries have
# dynamic keys (drive letters), not a fixed field list, so they stay a
# small loop of their own below rather than a table row.
_PROFILE_SCHEMA: list[tuple[str, object, str]] = [
    ("machine_id", _kind(int), "an int"),
    ("identity", _kind(dict), "an object"),
    ("identity.make", _kind(str), "a string"),
    ("identity.model", _kind(str), "a string"),
    ("identity.notes", _kind(str), "a string"),
    ("platform", _kind(str), "a string"),
    ("rom_template", _kind(str), "a string"),
    ("link", _kind(dict), "an object"),
    ("link.port_base", _kind(int), "an int"),
    ("link.reset", _kind(int), "an int"),
    ("link.mode", _kind(int), "an int"),
    ("link.baud", _kind(int), "an int"),
    ("drive_map", _kind(dict), "an object"),
    ("state", lambda v: v in STATES, f"one of {STATES}"),
    ("hardware", _kind(dict), "an object"),
    ("hardware.declared", _kind(dict), "an object"),
    ("hardware.declared.cpu", _kind(int), "an int"),
    ("hardware.declared.ram_kb", _kind(int), "an int"),
    ("hardware.declared.console", _kind(int), "an int"),
    ("hardware.observed", _kind(dict), "an object"),
    ("hardware.observed.cpu", _optional(int), "an int or null"),
    ("hardware.observed.ram_kb", _optional(int), "an int or null"),
    ("hardware.observed.console", _optional(int), "an int or null"),
    ("hardware.observed.rom_version", _optional(str), "a string or null"),
    ("hardware.observed.last_seen", _optional(int, float), "a number or null"),
    ("mint", _kind(dict), "an object"),
    ("mint.block_checksum", _optional(int), "an int or null"),
    ("mint.block_sha256", _optional(str), "a string or null"),
    ("mint.minted_at", _optional(str), "a string or null"),
    ("mint.rom_version", _optional(str), "a string or null"),
    ("mint.stamped", _optional(dict), "an object or null"),
    ("needs_remint", _kind(bool), "a bool"),
]


def _get_path(data: dict, path: str):
    """Walk a dotted path of dict keys. Only reached for a node whose
    ancestors the schema table has already confirmed are dicts (or raised
    before getting here) — the isinstance check is just a defensive
    backstop against a future reordering of the table."""
    node = data
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def validate_profile(data: object, *, context: str = "") -> dict:
    """Raise ProfileError with a clear message on anything malformed;
    otherwise return `data` unchanged (for chaining)."""
    _require(isinstance(data, dict), "profile is not a JSON object", context)
    _require(data.get("schema") == SCHEMA_VERSION,
              f"unsupported schema {data.get('schema')!r} (want {SCHEMA_VERSION})", context)

    for path, predicate, want in _PROFILE_SCHEMA:
        _require(predicate(_get_path(data, path)), f"{path} must be {want}", context)

    for letter, vol in data["drive_map"].items():
        _require(isinstance(letter, str) and len(letter) == 1 and letter.isalpha(),
                  f"drive_map key {letter!r} is not a single drive letter", context)
        _require(isinstance(vol, str), f"drive_map[{letter!r}] must be a volume name string", context)

    return data


def load_profile(machines_dir: pathlib.Path, machine_id: int) -> dict | None:
    """The validated profile dict, or None if no file exists for this id.

    Never creates anything — an absent file is a normal, silent result.
    """
    path = profile_path(machines_dir, machine_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ProfileError(f"{path}: invalid JSON ({e})") from e
    return validate_profile(data, context=str(path))


def save_profile(machines_dir: pathlib.Path, profile: dict) -> None:
    """Validate, then write the whole profile back to its file."""
    validate_profile(profile, context="save_profile")
    machines_dir.mkdir(parents=True, exist_ok=True)
    path = profile_path(machines_dir, profile["machine_id"])
    path.write_text(json.dumps(profile, indent=2) + "\n")


def list_profiles(machines_dir: pathlib.Path) -> list[dict]:
    """Every valid profile in the store, sorted by machine id."""
    if not machines_dir.exists():
        return []
    out = []
    for path in sorted(machines_dir.glob("*.json")):
        data = json.loads(path.read_text())
        out.append(validate_profile(data, context=str(path)))
    out.sort(key=lambda p: p["machine_id"])
    return out


def allocate_machine_id(machines_dir: pathlib.Path) -> int:
    """The next machine id, advancing the on-disk high-water mark first.

    Reads the current mark (NEXT_ID_START when the file is absent), writes
    mark+1 back to `.next-id` immediately, and only then returns the id to
    assign — so a crash between the two leaks an id rather than ever
    reissuing one, and a deleted profile's id is never recycled because the
    mark is never derived from the files that happen to exist (D4).
    """
    machines_dir.mkdir(parents=True, exist_ok=True)
    mark_path = machines_dir / NEXT_ID_FILE
    if mark_path.exists():
        mark = int(mark_path.read_text().strip())
    else:
        mark = NEXT_ID_START
    mark_path.write_text(f"{mark + 1}\n")
    return mark
