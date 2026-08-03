# M2 Boot Ladder — Proposal

## Why

The Boot Ladder is pillar 3, and M0/M1 built only its two ends: the machine
self-tests and it lands at a usable prompt in Local-Only Mode when HELLO
fails. What the operator cannot do yet is *see* the ladder or move back up
it. There is no way to ask what the self-test found, no way to see which
drives are bound to which volumes, and no way to recover a dead link short
of a reboot — which is exactly the promise CONTEXT.md makes for Local-Only
Mode ("recovering a dead bind takes one command, not a reboot").

The gap is also literal: M1's BIOS reads the HELLO response's binding count
into `MAPCNT`, keeps the first binding's drive letter in `DEFDRV`, and drops
every other binding and every volume name on the floor. Nothing on the
machine can report the Drive Map because nothing on the machine stores it.

## What Changes

- **Full Drive Map storage machine-side.** Parse every entry of the HELLO
  response (drive index, kind, flags, volume name) into a machine-side
  table instead of keeping only the first binding. `dir`/`type`/`run`
  continue to use the default drive — this is storage, not a new addressing
  scheme.
- **`ls /dev`.** The synthetic, read-only device node of ADR-0004's shallow
  namespace: the honest self-test inventory (CPU, RAM, console, wire) plus
  one line per drive letter showing its bind state — bound volume name,
  dead binding, or unbound. `ls` on any other path says so honestly rather
  than guessing.
- **`config`.** Always present, on every rung of the ladder. For M2 it is
  read-only: machine ID, ROM version, burned-in link config, link state,
  and the full Drive Map with bind states. Editing the map is server-side
  work that arrives with the Foundry (M3); M2 does not pretend otherwise.
- **`bind`.** One-command recovery from Local-Only Mode: drain the wire,
  re-issue HELLO with the same burned-in machine ID and inventory, adopt
  the returned Drive Map, and report success or the honest failure reason.
  No reboot, no re-banner, prompt state intact.
- **Repeat HELLO is explicitly legal on the wire.** `bind` is HELLO again;
  the spec now says so, so no future server change can quietly make the
  second HELLO an error. The current server already satisfies this — the
  change is a spec guarantee plus a regression test, not new behavior.
- **Harness gains mid-run server control** so the recovery flow can be
  proven end to end: boot linked, stop the server, watch a wire command
  fail honestly, restart the server, `bind`, and confirm the link is back.

Not in scope: editing the Drive Map, saving config to local disk (tier 2 of
§6.3, which needs a local disk the emulator target does not yet have),
per-drive command targeting (`dir /b`), and any Foundry work.

## Capabilities

### New Capabilities

None. Every behavior here extends a capability that already exists.

### Modified Capabilities

- `machine-boot`: HELLO now retains the complete Drive Map rather than the
  default drive alone; adds `ls /dev`, `config`, and `bind` to the prompt,
  and makes Local-Only Mode a state the operator can leave without a
  reboot.
- `emulator-harness`: adds boot-ladder scenarios (`ls /dev` in both link
  states, `config` display, kill-server-then-`bind` recovery) and the
  mid-run server control the recovery scenario needs.
- `wire-protocol`: HELLO is explicitly re-issuable mid-session and
  idempotent, so `bind` rests on a stated guarantee.

## Impact

- `machine/bios.asm` — drive-map table and parser, three new prompt verbs,
  wire drain before re-HELLO. Strict 8080 subset as always; the image must
  keep booting with `set cpu 8080`.
- `machine/protocol.inc` and `server/protocol.py` — comment-header
  documentation of repeat-HELLO semantics, kept in lockstep. No new codes.
- `server/tests/test_handlers.py` — one regression test pinning repeat
  HELLO on a single session.
- `harness/run_m0.py` — console watcher for mid-run server control, plus
  the new scenarios.
- No changes to the server's handlers, volumes, or oracle log format.
