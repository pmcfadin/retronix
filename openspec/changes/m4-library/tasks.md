# M4 Library — Tasks

Groups map onto the subareas in `docs/agents/orchestration.md` and are
ordered by dependency: protocol → server → library CLI → machine (Altair,
then Model 4, which can run in parallel once the protocol pair exists) →
harness → docs. Protocol goes first because every other group reads its
constants; harness goes last because it needs both server and machine live.

## 1. Protocol

- [ ] 1.1 Add FWRITE (`0x04`) and FDEL (`0x05`) function codes and the
  `RRDONLY` (`0x06`) result code to `server/protocol.py` and
  `machine/protocol.inc` in the same commit. Document the FWRITE request
  shape (drive, name, offset 4 LE, total-size 4 LE, chunk data) and the FDEL
  request shape (drive, name) in both files' header comments, mirroring how
  FREAD's shape is documented today.
- [ ] 1.2 Add an encode/decode round-trip unit test for FWRITE and FDEL on
  the Python side, including a case that resends an identical chunk and
  confirms the encoded bytes are identical (the framing half of
  idempotency; the storage half is a server test).

## 2. Server — write path, ownership, oracle log

- [ ] 2.1 Add an `owner` field to owned-kind volume entries in the volumes
  file schema and the `Volume` class; extend `load_volumes` to read it.
- [ ] 2.2 Extend `resolve_drive_map` to drop a binding to an owned volume
  whose `owner` does not match the connecting machine's ID, logging loudly
  to stderr exactly like today's missing-volume case. Unit test: a second
  claimant's binding is absent from its resolved drive map while the rest
  of its map is intact; the rightful owner's binding is present and marked
  writable.
- [ ] 2.3 Implement `Volume.write(name, offset, total_size, data)`:
  create-or-resize the target file to exactly `total_size`, write the chunk
  at `offset`. Unit tests: a fresh file is created at the right size; a
  resent identical chunk produces a byte-identical file; chunks arriving
  out of order converge to the same final file.
- [ ] 2.4 Implement `Volume.delete(name)`: remove if present, ok either way.
  Unit test: delete-then-delete-again both succeed, the second a no-op.
- [ ] 2.5 Implement `handle_fwrite` and `handle_fdel` in
  `retronix_server.py`: resolve the drive, refuse with `RRDONLY` when the
  bound volume is shared or owned by someone else, otherwise call
  `Volume.write`/`Volume.delete`. Oracle log records per design.md's field
  list (machine ID, drive, filename, result; FWRITE additionally offset,
  total size, chunk length).
- [ ] 2.6 Confirm the harness's existing per-scenario temp-volumes-file
  mechanism can express an owned volume with an `owner`; no changes needed
  if the JSON schema extension from 2.1 is already sufficient — verify with
  a throwaway fixture, don't skip the check.
- [ ] 2.7 `make test` green.

## 3. Library CLI and catalog

- [ ] 3.1 Define the catalog v1 header (magic, version, record count,
  reserved) and record (name, size, desc, source machine, date) pack/unpack
  in one place on the Python side, with round-trip tests including a
  header-validity test and a test that record `i`'s byte offset is exactly
  `8 + 68*i`.
- [ ] 3.2 Implement `server/library.py publish <machine-id> <file> --desc
  "..."`: resolve the machine's owned volume from the volumes file (a clear
  error if zero or more than one owned volume matches that machine ID),
  copy the file byte-for-byte into the library volume's directory,
  append-or-replace its catalog record with size, description, source
  machine ID, and today's date.
- [ ] 3.3 Implement `library.py unpublish <file>`: remove the file from the
  library volume's directory and its catalog record.
- [ ] 3.4 Implement `library.py list`: print every catalog record.
- [ ] 3.5 Tests: publish creates the file and its record; unpublish removes
  both; re-publishing the same name replaces its record rather than
  duplicating it; publish against an unknown machine ID, or a machine with
  no owned volume, or a machine with more than one, fails with a clear
  message rather than a traceback.

## 4. Machine — Altair template

- [ ] 4.1 Add FWRITE/FDEL request builders and response parsers to
  `machine/bios.asm`, following the existing FREAD (`setfrq`) pattern.
  Strict 8080 subset; confirm `set cpu 8080` still assembles and boots.
- [ ] 4.2 Implement `install <name>`: DIR the library drive for the name's
  size, then the chunked FREAD-into-buffer / FWRITE-from-buffer loop to the
  default owned drive (design.md's algorithm). Honest error reporting for
  file-not-found (source) and the read-only refusal (destination).
- [ ] 4.3 Implement `cp <src-drive>/<name> <dst-drive>/<name>` as the same
  loop generalized to two named drives.
- [ ] 4.4 Implement `rm <name>` (and `rm <drive>/<name>`): one FDEL,
  console reports success including for a name that was never there.
- [ ] 4.5 Implement `lib`: chunked FREAD of `CATALOG.IDX`, header
  validation (magic, version), one printed line per record (name, size,
  description).
- [ ] 4.6 Add the four keywords to the shell's command table and
  usage/help text. Rebuild strict-8080 and confirm every existing M0–M3
  harness scenario still passes against the extended image.

## 5. Machine — TRS-80 Model 4 template

- [ ] 5.1 Port FWRITE/FDEL request builders and response parsers to
  `machine/bios_m4.asm` (Z80, no 8080-subset constraint).
- [ ] 5.2 Port `install`, `cp`, `rm`, `lib` to the Model 4 template, sharing
  design.md's algorithm with the Altair implementation (4.2–4.5).
- [ ] 5.3 Extend `bootdemo` with two more synthetic command lines after the
  existing `DIR`/`TYPE ABOUT.TXT`/`RUN HELLO.COM` sequence: `LIB` and `RUN`
  of a fixed, well-known published-fixture name (pick and document the
  name, e.g. `CIRCLE.COM`, shared with the harness's circle scenario in
  group 6).
- [ ] 5.4 Confirm the existing M3 Model 4 scenarios (relocation, page-zero,
  HELLO retry, two-machines, block-integrity) still pass against the
  extended image.

## 6. Harness

- [ ] 6.1 Add fixture volumes files (owned volumes carrying `owner`) and a
  small pre-populated catalog fixture for scenarios that need a library
  with entries already in it.
- [ ] 6.2 Add the exclusivity scenario: two profiles bound to one owned
  volume, boot the non-owner, assert the dropped binding and the
  unbound-drive result on any subsequent access to that letter.
- [ ] 6.3 Add the install scenario: the Altair installs a library COM to
  its owned volume; assert the program's own console output after a
  subsequent `run`, and the oracle log's FREAD/FWRITE trail with
  server-side bytes compared equal to the library's copy.
- [ ] 6.4 Add the rm scenario: delete an existing file, confirm it's gone
  from DIR, delete the same now-absent name again, confirm both FDEL
  records in the oracle log are ok.
- [ ] 6.5 Add the read-only refusal scenario: a write and a delete attempt
  against the shared library volume, both refused with the read-only code
  on the console, the library volume's directory byte-for-byte unchanged
  afterward.
- [ ] 6.6 Add the circle scenario: the Altair pushes a file to its owned
  volume, the harness invokes `library.py publish` as a subprocess
  (matching how it already invokes `foundry.py mint`), the Model 4 boots
  and its extended auto-demo shows the new catalog entry and runs the
  freshly published COM. Assert on both consoles and the oracle log's
  FWRITE-then-later-FREAD trail. One emulator process at a time.
- [ ] 6.7 Run the full harness ten times consecutively green
  (`python3 harness/run_proof.py --runs 10`).

## 7. Docs

- [ ] 7.1 Write `.claude/skills/library/SKILL.md`: the push → publish →
  install loop, the CLI verbs, the catalog format, and the rule that the
  running server never mutates the library.
- [ ] 7.2 Update `README.md`'s proof section with the M4 scenarios and the
  circle story.
