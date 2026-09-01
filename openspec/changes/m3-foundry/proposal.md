# M3 Foundry — Proposal

## Why

Pillar 5 says the server is a ROM foundry, and ADR-0005 says machines are born
configured. Neither is true yet. Machine 1001 exists because its make, model,
and drive map are hand-written into `server/profiles.json`, and its identity is
hand-written a second time into `machine/bios.asm` as `db 0E9h,03h,00h,00h`.
Provisioning a second machine today means editing assembly and rebuilding —
which is exactly the manual bring-up flow ADR-0005 inverted.

Everything the foundry needs already exists on the wire. HELLO carries the
machine ID, ROM version, and self-test inventory; the server already records
what the machine reported. What is missing is a place to put the answer (a
profile store the operator can create entries in), a way to turn a profile
into boot media (minting), and the loop that closes between them — the drift
flag that says the burned ROM no longer matches the profile. M3 builds all
three, and proves them by provisioning two machines of different makes from
the same command line.

## What Changes

- **Minting is copy-a-template-and-stamp-a-block (ADR-0006).** One canonical
  ROM template per platform, built from source as today. The template reserves
  a fixed-address, versioned **config block** — magic, block version, machine
  ID, link config, cached drive map, checksum. Minting copies the template and
  rewrites that block. No assembler on the mint path; two mints of one profile
  are byte-identical.
- **The BIOS reads its identity from the block.** Machine ID and link config
  stop being assembly-time constants. `config` prints what the foundry
  stamped, and the machine can report its block back so drift is a byte
  comparison rather than a guess.
- **The baked drive map pre-populates the retained map at cold boot (D6).**
  Before the wire is touched, so a machine that never reaches a server shows
  its intended bindings marked dead instead of an empty map. A successful
  HELLO overwrites them — session tier still beats burned tier (ADR-0005).
- **A profile store: `server/machines/<id>.json`, one file per machine,
  committed.** It replaces `server/profiles.json`; machine 1001 migrates into
  it and the old file is deleted. Volume definitions move to their own file so
  the machines directory holds machines only. The server gains
  `--machines-dir` so the harness can point at a temp directory per scenario.
- **An operator CLI, `server/foundry.py`, with four verbs:** `new`, `list`,
  `show`, `mint <id>`. The running server only *reads* the store; every
  mutation goes through the CLI. Mints land in `build/mint/<id>.bin`
  (gitignored).
- **Machine IDs are sequential from 1001 and never reused (D4),** assigned by
  the CLI from an explicit high-water mark (`server/machines/.next-id`), so
  retiring a machine cannot recycle its identity by accident.
- **The full probe → refine loop, with zero wire changes (D5).** A profile is
  born `probe`. On every HELLO the server diffs the reported inventory and ROM
  version against the profile, writes what it saw into the profile's *observed*
  facts, and sets `needs-remint` when they disagree with what was minted.
  `list`/`show` surface the flag; the next `mint` stamps the reconciled values;
  a boot whose HELLO matches makes the profile `exact`. No new verbs, no
  payload changes — the existing HELLO already carries everything.
- **A second platform: a TRS-80 Model 4 ROM template under trs80gp
  (ADR-0007).** trs80gp is fetched as a checksum-pinned binary rather than
  built from source, and the Model 4 template must copy itself into RAM and
  flip the port-84h map bits before CP/M page zero can exist. Console output
  is captured through the emulator's printer-port TCP tap.
- **A repo agent skill, `.claude/skills/foundry/SKILL.md`,** teaching an agent
  the provision loop: `new` → `mint` → boot → check refine state → re-mint.
- **Harness proof: two machines of different make, sequential sessions (D7).**
  Mint 1001 (Altair) and 1002 (Model 4) with different drive maps; each boots
  and sees only its own map. Plus the probe loop end to end, drift detection,
  and stamped-block integrity. One emulator process at a time.

Not in scope: owned-volume exclusivity (needs the write path — M4), editing
config from the machine, EPROM/floppy media targets beyond a raw image, and
running both emulators concurrently.

## Capabilities

### New Capabilities

- `foundry`: the profile store, machine-ID assignment, the config block
  format, minting, and the operator CLI — everything that turns a machine
  profile into boot media and keeps the two reconciled.

### Modified Capabilities

- `machine-boot`: identity and link config come from the stamped config block
  rather than assembly-time constants; the block's cached drive map
  pre-populates the retained map before the wire is touched; `config` reports
  the block; a Model 4 ROM template joins the Altair one.
- `server`: profiles load from a per-machine store directory rather than a
  single static file, the server reads that store and never writes it, and
  HELLO now reconciles — recording observed facts and raising `needs-remint`
  on drift.
- `emulator-harness`: adds trs80gp as a second emulator with the printer-port
  console tap, and the D7 scenarios (two machines, probe loop, drift, block
  integrity).

`wire-protocol` needs **no delta**. Every requirement the refine loop rests on
— HELLO carries machine ID, ROM version, and inventory; HELLO is idempotent
and re-issuable; the response carries the current drive map — is already
specified. D5 is explicit that M3 adds no verb, code, or payload change.

## Impact

- `server/foundry.py` (new), `server/machines/` (new, replaces
  `server/profiles.json`), `server/retronix_server.py` (store loading,
  `--machines-dir`, HELLO reconciliation), `server/tests/`.
- `machine/bios.asm` — config block reservation, block read and validation at
  cold boot, DMAP preload, `config` display of the block. Strict 8080 subset;
  the image must keep booting under `set cpu 8080`.
- `machine/m4/` (new) — the Model 4 ROM template: relocate-to-RAM, port 84h
  map switch, TR1865 driver, printer-port console mirror. Z80 target, not
  8080-subset.
- `tools/` — checksum-pinned trs80gp fetch with the quarantine attribute
  stripped; `tools/build-tools.sh` documents why this one is not from source.
- `harness/` — a trs80gp scenario runner alongside the SIMH one, and the D7
  scenarios.
- `.claude/skills/foundry/SKILL.md` (new).
- No changes to `machine/protocol.inc` or `server/protocol.py`.
