## Context

M2 left the machine able to *report* its configuration and left the server
able to *serve* one profile that a human typed into `server/profiles.json`.
The identity in that file is duplicated in `machine/bios.asm` as
`HELLOP: db 0E9h,03h,00h,00h` — machine 1001, little-endian — and the link
config is a pair of equates (`WRESET`, `WMODE`). Provisioning a second machine
means editing assembly. That is the flow ADR-0005 inverted, and M3 is where
the inversion actually lands.

Constraints that shape everything below: the Altair BIOS is a strict 8080
subset and must keep booting under `set cpu 8080`; the monitor lives at E000
with the stack at FE00 and the current image ends around EDAE; the wire is
machine-initiated with one outstanding request and no unprompted server frames
(ADR-0003); the drive map is server-authoritative and reconciled in three
tiers at HELLO (ADR-0005); and D5 fixes the wire as-is — the refine loop must
be built entirely out of the HELLO payload that already exists.

The second platform brings its own constraints, all from
`docs/research/trs80-model4-emulation.md`: trs80gp is a closed-source binary
(ADR-0007), its stock-ROM scripting layer is dead under our ROM, ROM and page
zero are mutually exclusive on a Model 4, and the first byte of every TCP
stream is lost to a connect race.

## Goals / Non-Goals

**Goals:**
- Turn a machine profile into boot media with one command, deterministically.
- Give the BIOS one place to read its identity from, so profile-vs-ROM drift
  is a byte comparison instead of a judgement call.
- Close the probe → refine → exact loop end to end, on the existing wire.
- Prove it on two machines of different makes, from the same CLI.

**Non-Goals:**
- Owned-volume exclusivity (needs the write path — M4).
- Editing config from the machine. `config` stays read-only; the foundry owns
  mutation and the block is not writable at runtime.
- Media targets beyond a raw image (EPROM/floppy layouts are per-profile
  catalog data, deferred in the PRD).
- Running both emulators at once. Scenarios are sequential.
- Any wire-protocol change.

## Decisions

**Config block v1 layout.** One fixed-address region per template, stamped by
the foundry and read by the BIOS. Offsets are from the block's base:

| Offset | Size | Field |
|---|---|---|
| `0x000` | 4 | magic, ASCII `RNXC` |
| `0x004` | 1 | block format version — `01` for v1 |
| `0x005` | 1 | platform id — `01` Altair 8800 / M2SIO ACIA, `02` TRS-80 Model 4 / TR1865 |
| `0x006` | 4 | machine ID, 32-bit little-endian — byte-identical to the HELLO payload's first four bytes |
| `0x00A` | 8 | link config, interpreted by platform id: port base, reset byte, mode byte, baud/divisor byte, then 4 reserved zero |
| `0x012` | 1 | cached map entry count, 0–16 |
| `0x013` | 1 | profile state at mint — `00` probe, `01` exact |
| `0x014` | 12 | reserved, zero |
| `0x020` | 320 | cached drive map: 16 entries × 20 bytes |
| `0x160` | 1 | checksum |

The map is **exactly `DMAP`'s shape** — `DMAPN` (16) entries of `DENTSZ` (20)
bytes: drive index, kind, flags, name length, 16 name bytes. Preloading the
retained map is then a 320-byte block copy, not a parse, and the same
truncation rule that already governs HELLO responses governs the block. The
checksum is the wire's rule reused verbatim: the two's complement of the 8-bit
sum of bytes `0x000`–`0x15F`, so summing the whole defined block yields zero
and the BIOS can call the routine it already has. 353 bytes are defined; the
template reserves 512 at the block base with the tail zero-filled, so a v2
block can grow without moving anything.

Alternatives rejected: a length-prefixed TLV block (flexible, but every field
read becomes a walk on an 8080, and the whole point is that the block is cheap
to read at cold boot); and re-encoding the map in a denser form (it would save
~200 bytes of ROM and cost a translation layer on both sides for no behavior).

**Where the block lives.** A per-platform equate, `CFGBLK`, published in a new
`machine/config.inc` and mirrored by the Python stamper — one number in two
places, checked by a test. For the Altair template it goes at `0E100h`, with
`org 0E000h` holding a `jmp` to the monitor body relocated to `0E300h`: the
boot entry address does not move, the block sits at a round address, and the
image grows by ~512 bytes with roughly 3 KB still clear below the stack. On
the Model 4 the block must land inside the ROM's `0000`–`37FF` window and
survive the copy into RAM, so it is placed in the relocated image at the same
offset from the template's base.

**The BIOS validates the block, and falls back honestly.** At cold boot it
checks the magic, the version, and the checksum. On success it copies the
machine ID into the HELLO payload, applies the link config, and copies the
cached map into `DMAP` with `MAPCNT` set from the entry count — all before the
wire is touched (D6). On failure it boots with an all-zero identity, prints
that the config block is unreadable, and goes straight to Local-Only Mode
rather than dialing with a garbage machine ID. An unstamped template (the
build output, before minting) hits exactly this path, which is the correct
behavior for a ROM nobody has provisioned.

**The foundry is a CLI; the server is a reader.** `server/foundry.py` with
`new`, `list`, `show`, `mint <id>`. Splitting write from read this way means
the server never has to arbitrate concurrent profile edits, the store stays
diff-able in git, and the harness can hand each scenario a temp
`--machines-dir` without a running server holding a lock. The cost is that a
`needs-remint` flag discovered by a *running* server has to be written by that
server — so the one write the server does perform is confined to a single
reconciliation function with its own test, and it writes only the observed
facts and the flag, never identity, drive map, or mint state.

**Profile JSON schema (v1).** One file per machine, `server/machines/<id>.json`:

```json
{
  "schema": 1,
  "machine_id": 1001,
  "identity": { "make": "MITS", "model": "Altair 8800", "notes": "" },
  "platform": "altair-m2sio",
  "rom_template": "build/retronix.bin",
  "link": { "port_base": 16, "reset": 3, "mode": 21, "baud": 0 },
  "drive_map": { "A": "library" },
  "state": "probe",
  "hardware": {
    "declared": { "cpu": 0, "ram_kb": 0, "console": 0 },
    "observed": { "cpu": null, "ram_kb": null, "console": null,
                  "rom_version": null, "last_seen": null }
  },
  "mint": { "block_checksum": null, "block_sha256": null,
            "minted_at": null, "rom_version": null },
  "needs_remint": false
}
```

`declared` is what the operator asserted; `observed` is what HELLO reported.
Keeping them apart is what makes `probe` meaningful — a profile is `exact`
when every declared fact has a matching observation, not when someone decided
it looked finished. `platform` selects the ROM template and the interpretation
of `link`; `rom_template` names the image the mint copies.

**Machine ID assignment.** `server/machines/.next-id` holds the high-water
mark, starting at 1001. `new` reads it, writes back `n+1`, then creates the
profile — in that order, so a crash leaks an ID rather than reusing one. The
file is committed. Rejected: computing `max(existing) + 1` at `new` time,
which silently recycles the ID of any machine whose profile was deleted, and
that is precisely the failure D4 exists to prevent.

**The refine loop is a four-state walk, driven only by HELLO.**

- `probe`, no mint — created by `new`. `mint` is legal; it stamps declared
  values and records the block checksum.
- `probe`, minted — the machine can boot. Its HELLO carries the real
  inventory.
- On each HELLO the server writes `observed` from the reported inventory and
  ROM version, then compares: if any observed fact differs from what the mint
  recorded, or the reported ROM version differs, it sets `needs_remint` and
  leaves the state at `probe`. If everything matches and no declared fact is
  still unobserved, it clears `needs_remint` and sets the state to `exact`.
- `mint` on a profile with `needs_remint` stamps the reconciled (observed)
  values and clears the flag; the next matching HELLO makes it `exact`.

Drift and probe are therefore the same mechanism seen twice: a profile edited
after minting flags `needs_remint` at the next HELLO for exactly the same
reason a probe profile does. That is why D7's scenarios 2 and 3 exercise one
code path.

**Console capture on the Model 4 is a byte channel we own.** trs80gp's
`-p :PORT` printer tap, with the ROM mirroring every console character to
`OUT (0F8h),A`. The harness reads that socket the way it reads SIMH's console
file. This is closer to the PRD's "assert against the protocol, not scraped
terminal characters" than screen scraping was, and it is the only option that
survives a custom ROM (the emulator's `-iw`/`-i` layer is wired to the stock
ROM's keyboard hook and is verified dead under ours).

**Model 4 template plan.** Reset lands at `0000` with map 0 (ROM at
`0000`–`37FF`). The template's first act is to copy itself into RAM above
`4000`, jump into the copy, then `OUT (84h)` with map `10` — RAM at
`0000`–`F3FF`, keyboard at `F400`, video at `F800` — which gives a ~61 KB TPA
with the console hardware still addressable and no bank gymnastics. Only then
does page zero exist and the CP/M vectors get written. The wire is the TR1865
at `E8`–`EB` with the init the research verified: `OUT (E8h),0`, then `0EEh`
to `E9` (9600 both ways) or `0FFh` for 19200 if throughput bites, then `6Fh`
to `EA` (8N1, not-break, DTR, RTS). This is Z80 code in `machine/m4/`; the
8080-subset rule is an Altair-template rule and does not apply here.

## Risks / Trade-offs

- **The map-switch relocation is new code with no analogue in the Altair
  BIOS** — get it wrong and the machine dies before it can print why. → Prove
  it in isolation first: a Model 4 template that relocates, switches to map
  `10`, and prints one line to the printer tap, as its own harness scenario
  before any wire work starts.
- **`-ip :PORT` may not restore keystroke injection under a custom ROM**
  (UNVERIFIED; the whole scripting layer is ROM-gated). Without it the harness
  cannot type at the Model 4 prompt, and D7's scenarios all need input. → This
  is the first task in the milestone, deliberately ahead of the template work.
  Fallback: ROM-owned console input over a second serial endpoint (`-rB`), at
  the cost of a channel the Altair path does not have.
- **The connect race drops the first byte of every stream** (reproduced on
  every research run). → The HELLO retry loop is load-bearing on this
  platform, and the harness needs the "emulator never opened the wire" escape
  hatch that `run_linked_sim` already has.
- **Emulated baud throttles the wire.** trs80gp honours the programmed rate
  even over TCP, so a 32 KB COM file at 9600 is ~30 s of wall clock. → Program
  19200 and keep Model 4 scenarios off the COM-loading path where possible.
- **trs80gp is not headless and is closed-source** (ADR-0007). → Pin the
  checksum, mirror the archive, and accept that Model 4 scenarios do not run
  on a windowless CI runner. The Altair proof stays the one that must always
  pass.
- **Deleting `server/profiles.json` breaks anything that reads it** — the
  server, the tests, and the harness all name it today. → One task migrates
  all three together; volume definitions move to their own file in the same
  step so the machines directory holds machines only.
- **The block's fixed address collides with a growing monitor.** The Altair
  image already reaches EDAE and the block plus relocation pushes it past
  F000. → Check the listing's end address after every build, as M2 did; the
  block is at a lower address than the code that follows it, so a collision
  shows up as an overlap warning rather than silent corruption.
- **Two sources of truth for `CFGBLK` and the block layout** (assembly and
  Python). → A test that asserts the stamper's constants against the values
  the assembler emitted, so the pair cannot drift silently.

## Migration Plan

1. Add `server/machines/1001.json` carrying today's machine 1001 exactly, plus
   `server/machines/.next-id` = 1002, plus a volumes file holding the
   `library` definition.
2. Teach the server to load from `--machines-dir` (defaulting to
   `server/machines`) and the volumes file; update tests and the harness in
   the same commit.
3. Delete `server/profiles.json`.
4. Mint 1001 from its profile and confirm the existing harness scenarios pass
   against the minted image rather than the hand-edited one. The pre-mint
   template also still boots — into Local-Only Mode with an unreadable block,
   which is the honest answer for an unprovisioned ROM.

Rollback is the reverse: the store is plain JSON in git, and the BIOS's
fallback path means an image minted by a broken foundry still boots to a
prompt.

## Open Questions

- Does `-ip :PORT` deliver keystrokes to a custom ROM? Task 1.1; the answer
  decides whether the Model 4 scenarios drive the prompt or only observe it.
- Does the Model 4 template fit under `37FF` with the block, the relocator,
  the TR1865 driver, and enough of the shell to be worth booting? The research
  notes trs80gp's `-rom` size behavior is loosely specified and assumes the
  14 KB window. If it does not fit, the milestone's Model 4 half narrows to
  boot + HELLO + `config` and leaves the shell verbs to M4.
- Exact `config` output format for the block. The content is normative (magic
  validity, block version, machine ID, link config, cached map); the column
  layout is not.
