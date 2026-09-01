"""HELLO reconciliation — one function, its own tests (task 2.6).

ADR-0005's three tiers, restated for the refine loop (design.md "The refine
loop is a four-state walk, driven only by HELLO"): the drive map the server
answers with is always the profile's current one (server/retronix_server.py
handles that directly); the profile's *observed* hardware facts are
overwritten with what this HELLO reported; and where the reported facts
disagree with the profile's declared facts, or the profile's live link/drive
map disagrees with what `mint.stamped` recorded, the flag is `needs_remint`
rather than a pretense that the burned ROM changed.

`reconcile_hello` is a pure function of its inputs — `profile.hardware`
.declared, `profile.mint`, `profile.link`, `profile.drive_map`, and the
HELLO payload — and never of `profile.hardware.observed` itself. That is
what makes two identical HELLOs idempotent: replaying the same inputs
recomputes the same observed/needs_remint/state every time, rather than
drifting from call to call.

Only `hardware.observed`, `state`, and `needs_remint` are written. Identity,
platform, rom_template, link, drive_map, and mint are read, never touched —
that boundary is what the never-mutates-identity test in test_reconcile.py
and test_handlers.py checks.
"""
from __future__ import annotations

import time

# The HELLO wire payload (protocol.py / protocol.inc) reports cpu and
# ram_kb; it carries no console fact in protocol v0, so hardware.declared
# .console / .observed.console exist in the schema but are not reconciled
# here — there is nothing on the wire to reconcile them against yet.
HW_FIELDS = ("cpu", "ram_kb")

UNSPECIFIED = 0  # a declared hardware fact of 0 reads as "not yet asserted"

# Fields where 0 is never a real declared value, so it safely doubles as
# "the operator hasn't asserted this yet" (design.md's "unexpected RAM
# size" scenario). `cpu` has no such spare value — 0 is the 8080 encoding
# HELLO itself uses (protocol.inc), a legitimate declaration in its own
# right — so it is compared directly with no unspecified sentinel.
SENTINEL_FIELDS = {"ram_kb"}


def reconcile_hello(profile: dict, *, rom_version: tuple[int, int, int],
                    cpu: int, ram_kb: int, now: float | None = None) -> None:
    """Mutate `profile` in place per the refine loop above.

    `rom_version` is the HELLO payload's (major, minor, patch). `now`
    overrides the observed last-seen timestamp — pass a fixed value in
    tests that need two reconciliations to produce byte-identical results.
    """
    rom_str = ".".join(str(b) for b in rom_version)
    when = time.time() if now is None else now

    observed = profile["hardware"]["observed"]
    observed["cpu"] = cpu
    observed["ram_kb"] = ram_kb
    observed["rom_version"] = rom_str
    observed["last_seen"] = when

    declared = profile["hardware"]["declared"]
    reported = {"cpu": cpu, "ram_kb": ram_kb}
    mismatch = False
    for field in HW_FIELDS:
        dval = declared.get(field, UNSPECIFIED)
        if field in SENTINEL_FIELDS and dval == UNSPECIFIED:
            mismatch = True
        elif dval != reported[field]:
            mismatch = True

    mint = profile["mint"]
    stamped = mint.get("stamped")
    if stamped is None:
        mismatch = True  # never minted at all — cannot be exact
    elif stamped.get("link") != profile["link"] or stamped.get("drive_map") != profile["drive_map"]:
        mismatch = True  # profile edited since the last mint (drift)

    if mint.get("rom_version") is not None and mint["rom_version"] != rom_str:
        mismatch = True

    profile["needs_remint"] = mismatch
    profile["state"] = "probe" if mismatch else "exact"
