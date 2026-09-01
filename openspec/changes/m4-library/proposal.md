## Why

Pillar 5 says the server is a software library. Pillar 4 says it's a
filesystem. Neither has a write path yet — every wire verb since M0 has been
a read (HELLO, DIR, FREAD). ADR-0002 named two kinds of volumes in M0 and
left owned-writable volumes unimplemented "until the write path"; M3's
proposal named the same debt explicitly ("owned-volume exclusivity — needs
the write path — M4"). Machine 1001 can read the library's `HELLO.COM`
today. It cannot save anything of its own, and there is nowhere for its own
software to land even if it could.

M4 closes both gaps in one milestone, deliberately as one: FWRITE and FDEL
give a machine a place to save its own work, and `library.py publish` gives
an operator a way to promote that work into the shared library everyone else
can read. The proof is the whole homebrew circle: an Altair pushes a file to
its own volume, an operator publishes it, and a TRS-80 Model 4 boots, shows
it in the catalog, and runs it — 8-bit software distributed machine to
machine through the server, exactly as the PRD's library pillar always meant.

## What Changes

- **FWRITE and FDEL land on the wire — the first protocol change since M1
  (D5).** Chunked, idempotent writes (offset plus a total-size field applied
  on every chunk, so any chunk can be resent and lands identically); deletes
  that succeed whether or not the file existed. Both apply only to volumes
  the requesting machine owns; a write or delete against a shared volume, or
  a volume owned by someone else, answers with one new, honestly distinct
  read-only result code. `machine/protocol.inc` and `server/protocol.py`
  grow together, in lockstep, for the first time since M1.
- **Owned volumes exist for real, and exclusivity is enforced (D1).**
  `volumes.json` gains an `owner` field on volumes of kind `owned`. At
  HELLO, a binding to an owned volume this machine does not own is dropped
  exactly like a binding to a volume that doesn't exist — logged loudly
  server-side, silently absent from the machine's drive map — so a second
  claimant's every subsequent request against that letter meets the
  `unbound-drive` code that already exists. No new HELLO-time wire code; the
  deferred ADR-0002 proof lands on the existing refusal path.
- **The library is a shared volume plus one more file (D2).** A versioned,
  fixed-stride Catalog index (`CATALOG.IDX`) that `library.py publish` writes
  and that `lib` reads with the existing FREAD verb and prints. No catalog
  wire verb; ADR-0008 explains why.
- **`server/library.py`, a foundry-shaped CLI (D4).** `publish <machine-id>
  <file> --desc "..."` copies a file from that machine's owned volume into
  the library and updates the catalog; `unpublish <file>` and `list` round
  it out. All library mutation goes through the CLI; the running server only
  reads volumes, exactly as it only reads machine profiles.
- **`install`, `rm`, `cp`, and `lib` as shell verbs, on both templates
  (D3, D6).** `install <name>` is FREAD-from-library composed with
  FWRITE-to-owned-drive through the TPA, chunk by chunk; `cp` is the same
  code path generalized between any two drives; `rm` is FDEL. This is
  deliberately shell-level, not BDOS-level — the redirector that would make
  ordinary CP/M file I/O transparent to the network is its own milestone
  right after this one (D6).
- **The Model 4's boot-time auto-demo grows two more synthetic commands**
  (`lib`, then `run` of a known published fixture) so the headless proof of
  the full circle needs no scriptable console input, following the pattern
  M3 established for that platform.
- **Harness proof: the full homebrew circle, cross-platform (D7).** Five
  scenarios — exclusivity, install, rm, read-only refusal, and the circle
  itself (Altair pushes → `library.py publish` promotes → Model 4 boots,
  shows the catalog entry, and runs the fresh COM).

Not in scope: the redirector (BDOS-level file I/O interception, D6 — its own
milestone next); editing the catalog by any path other than `library.py`;
enforcing BDOS-cleanliness on published software (documented publisher
responsibility, not tooling); a compiled-server rewrite (server work stays
Python, re-confirmed).

## Capabilities

### New Capabilities

- `library`: the catalog index format, publish/unpublish semantics, and the
  `library.py` operator CLI — the data and tooling that turn a pushed file
  into something every machine can read, mirroring how `foundry` (M3) turns
  a profile into boot media.

### Modified Capabilities

- `wire-protocol`: FWRITE and FDEL join HELLO/DIR/FREAD, and the v0 result
  table gains a read-only-volume code — the first protocol delta since M1.
- `server`: `Volume` gains ownership, HELLO's binding resolution drops a
  conflicting owned-volume claim, and the server gains FWRITE/FDEL handlers
  and their oracle-log records.
- `machine-boot`: `lib`, `install`, `rm`, `cp` join the shell's verb table on
  both the Altair and Model 4 templates, and the Model 4's boot-time
  auto-demo grows to exercise the circle headlessly.
- `emulator-harness`: the five D7 scenarios — exclusivity, install, rm,
  read-only refusal, and the cross-platform circle.

`foundry` and `com-loader` need **no delta**. Foundry's four verbs and the
config-block/mint machinery are untouched by any of D1–D7; owned volumes are
declared in `volumes.json`, not minted into a profile. `com-loader`'s
requirements are about loading and executing a COM file (`run`, the BDOS
console shim, `type`) — `install`/`cp`/`rm`/`lib` are new shell verbs that
compose FREAD and FWRITE but never execute anything, so they belong under
`machine-boot`'s existing home for shell verbs (`dir`, `ls /dev`, `config`,
`bind`) rather than com-loader.

## Impact

- `machine/protocol.inc`, `server/protocol.py` — FWRITE (0x04), FDEL (0x05),
  RRDONLY (0x06), in lockstep.
- `server/retronix_server.py`, `server/volumes.json` — `Volume.owner`,
  `handle_fwrite`, `handle_fdel`, ownership-aware `resolve_drive_map`.
- `server/library.py` (new), `server/tests/`.
- `machine/bios.asm` — `lib`, `install`, `rm`, `cp` shell verbs, TPA copy
  loop, strict 8080 subset kept.
- `machine/bios_m4.asm` — the same four verbs, plus the boot-demo extension.
- `harness/` — the five D7 scenarios, fixture volumes with an `owner` field,
  a catalog fixture.
- `.claude/skills/library/SKILL.md` (new) — the push → publish → install
  loop, mirroring `.claude/skills/foundry/SKILL.md`.
