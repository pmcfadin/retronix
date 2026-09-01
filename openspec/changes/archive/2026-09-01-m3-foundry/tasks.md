# M3 Foundry — Tasks

Groups map onto the subareas in `docs/agents/orchestration.md` and are ordered
by dependency: unknowns/tools → server → machine (Altair, then Model 4) →
harness → docs. There is **no protocol group**: D5 fixes the wire as it
stands, and the refine loop is built entirely from the existing HELLO payload.

Group 1 exists to close the two things that could invalidate later work: the
keystroke-injection unknown and the pinned emulator binary. Do it first —
group 4 is expensive and group 5 cannot be designed until 1.1 has an answer.
Groups 3 and 4 can run in parallel once group 2's block writer exists.

## 1. Unknowns and tooling

- [x] 1.1 Close the `-ip :PORT` unknown: determine whether trs80gp delivers
  keystrokes from a TCP endpoint to a **custom** ROM, or whether that path is
  ROM-gated like `-iw`/`-i`. Test with a minimal Model 4 probe ROM that echoes
  received keys to the printer tap. Record the answer in
  `docs/research/trs80-model4-emulation.md` and pick the Model 4 input channel
  accordingly: `-ip` if it works, otherwise ROM-owned console input over a
  second serial endpoint (`-rB`). Do this before any group 4 work.
- [x] 1.2 Add a checksum-pinned trs80gp fetch to `tools/`: download
  `trs80gp-2.5.7.zip`, verify a pinned SHA-256, unpack, strip
  `com.apple.quarantine` from the ad-hoc-signed app, and install the binary
  under `tools/bin/`. Fail loudly on a checksum mismatch; never fall back to
  an unverified copy. Note in `tools/build-tools.sh` why this one tool is not
  built from source, pointing at ADR-0007.
- [x] 1.3 Mirror the pinned archive somewhere the project controls, since
  upstream keeps only the last few releases online, and record where.

## 2. Server (foundry, store, reconciliation)

- [x] 2.1 Define the config block v1 format in one place on the Python side —
  magic, block version, platform id, machine ID (4 LE), link config, entry
  count, profile state, reserved, 16×20-byte cached map, wire-rule checksum —
  with pack and unpack plus round-trip tests, including a test that a
  single-byte mutation breaks the checksum.
- [x] 2.2 Add the profile store: `server/machines/<id>.json` with the schema
  from design.md, load/save helpers, and validation that rejects a malformed
  profile with a clear message rather than a traceback.
- [x] 2.3 Add machine-ID assignment from `server/machines/.next-id` starting at
  1001: advance the mark *before* writing the profile, never derive the next
  ID from existing files, and cover the retired-machine case with a test.
- [x] 2.4 Implement `server/foundry.py` with `new`, `list`, `show`, `mint <id>`.
  `mint` copies the profile's ROM template, stamps the block, writes
  `build/mint/<id>.bin`, and records the block checksum and mint time in the
  profile. Assert byte-determinism (mint twice, compare) and
  template-equality-outside-the-block in tests. Gitignore `build/mint/`.
- [x] 2.5 Teach the server `--machines-dir` (default `server/machines`), move
  volume definitions to their own configuration, and migrate machine 1001 into
  the store with `.next-id` at 1002. Update `server/tests/` and the harness in
  the same step, then delete `server/profiles.json`.
- [x] 2.6 Implement HELLO reconciliation in one function with its own tests:
  write observed facts and ROM version, set `needs-remint` on disagreement with
  the last mint, clear it and set `exact` on full agreement, and touch nothing
  else in the profile. Prove idempotence — two identical HELLOs, one resulting
  profile.
- [x] 2.7 Prove the server never mutates identity, drive map, link config, or
  mint state: a test that snapshots those fields across a HELLO and asserts
  they are byte-identical, and that an unknown machine ID creates no file.
  `make test` green.

## 3. Machine — Altair template and the config block

- [x] 3.1 Reserve the block: add `machine/config.inc` with `CFGBLK` and the
  field offsets, place the block at `0E100h` with `org 0E000h` holding a jump
  to the monitor body relocated to `0E300h`, and confirm the listing's end
  address still clears the stack. Add the test that pins the assembler's
  constants against the Python stamper's.
- [x] 3.2 Read and validate the block at cold boot — magic, version, checksum
  under the existing wire-checksum routine — before the wire is touched.
- [x] 3.3 On a valid block, copy the machine ID into the HELLO payload and
  apply the link config in place of the `WRESET`/`WMODE` equates, so identity
  and framing come from the block and not from the assembled code.
- [x] 3.4 On a valid block, preload `DMAP`/`MAPCNT` from the block's cached map
  before any wire traffic (D6); confirm a successful HELLO replaces the map
  wholesale rather than merging, and that `ls /dev` marks preloaded bindings
  dead in Local-Only Mode.
- [x] 3.5 On an invalid, unstamped, or unknown-version block, print the honest
  "config block unreadable" line, skip HELLO entirely, and land at the prompt
  in Local-Only Mode.
- [x] 3.6 Extend `config` to report the block: validity, format version, and
  the stamped machine ID, link config, and baked bindings; keep it read-only
  and name re-minting as the only way to change the block.
- [x] 3.7 Rebuild strict-8080 and confirm every existing harness scenario still
  passes against a *minted* 1001 image.

## 4. Machine — TRS-80 Model 4 template

- [x] 4.1 Prove the relocation in isolation, before any wire work: a template
  that copies itself into RAM above `4000`, jumps into the copy, switches the
  port-84h map to `10`, writes and reads back page zero, and prints one line to
  the printer tap. This is the milestone's top technical risk — it gets its own
  proof.
- [x] 4.2 Lay down the CP/M page-zero vectors after the map switch and confirm
  the TPA boundary, so `0005` and the restart vectors exist before anything
  uses them.
- [x] 4.3 Bring up the TR1865 wire at `E8`–`EB` with the verified init
  (`OUT (E8h),0`; `0EEh`→`E9` for 9600 or `0FFh` for 19200; `6Fh`→`EA`), and
  mirror every console character to the printer port at `F8h`.
- [x] 4.4 Place the config block in the Model 4 template at the same offset from
  the template base as the Altair one, inside the `0000`–`37FF` ROM window, and
  make it survive the copy into RAM. Confirm the image fits the window.
- [x] 4.5 Port the boot ladder: block read and validation, DMAP preload, HELLO
  with the bounded retry loop that survives the dropped first byte, banner,
  prompt, and Local-Only Mode with no server.
- [x] 4.6 Per the closed 1.1 answer (no scriptable input channel exists):
  implement the keyboard-matrix console-input driver for interactive and
  real-iron use, and add the boot-time auto-report — print the `config`
  block report and `ls /dev` unprompted after banner and HELLO — so headless
  scenarios assert on boot output over the printer tap without typing.

## 5. Harness

- [x] 5.1 Add a trs80gp scenario runner alongside the SIMH one: launch with
  `-m4 -dx -hx -rom <image> -r :PORT -p :PORT2`, listen for both dial-outs,
  read the console from the printer tap, and tear down the process and both
  sockets on success and failure alike. Report a missing pinned binary
  explicitly rather than skipping.
- [x] 5.2 Give scenarios a temporary machines directory and a foundry call, so
  a scenario can mint its own images instead of depending on committed ones.
- [x] 5.3 Add the two-machines scenario: mint 1001 (Altair) and 1002 (Model 4)
  with different drive maps, boot each in turn against one server, and assert
  one ok HELLO per machine ID and that neither console shows the other's
  bindings. One emulator at a time.
- [x] 5.4 Add the probe-loop scenario: profile with unknown RAM → mint → boot →
  observed facts recorded and `needs-remint` set → re-mint → boot → `exact` and
  the flag clear; assert the two mints differ only inside the block.
- [x] 5.5 Add the drift scenario: edit a profile after minting, boot the
  unchanged image, and assert the response carries the edited map while the
  profile ends with `needs-remint` set.
- [x] 5.6 Add the block-integrity scenario: `config` on a booted mint reports
  the machine ID, link config, and baked bindings the foundry stamped, and
  reports the block valid.
- [x] 5.7 Run the full harness ten times consecutively green
  (`python3 harness/run_proof.py --runs 10`), with the Altair scenarios passing
  against minted images.

## 6. Docs

- [x] 6.1 Write `.claude/skills/foundry/SKILL.md`: the provision loop
  (`new` → `mint` → boot → check refine state → re-mint), the CLI verbs, the
  store layout, and the rule that the running server only reads profiles.
- [x] 6.2 Update `README.md`'s proof section with the M3 scenarios and the
  two-platform story, including how to fetch the pinned trs80gp binary.
- [x] 6.3 Fold the 1.1 answer and any Model 4 surprises back into
  `docs/research/trs80-model4-emulation.md`, so the next person reads verified
  facts rather than the open question.
