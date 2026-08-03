# M1 — Filesystem

## Why

The spine is proven (M0, archived): HELLO and DIR work end to end on a strict-8080 image under SIMH. But the network drive can't yet deliver a single file byte — the library pillar is a catalog you can see and not touch. M1 adds the read path and the payoff moment the PRD promises: browse the volume and **run a real COM file fetched over the wire on the local CPU** (PRD §13 M1, pillar 1 and 4).

## What Changes

- A stateless FREAD verb: read `length` bytes at `offset` from a named file on a bound drive. No OPEN/CLOSE, no server-side cursors — ADR-0003's idempotency rule makes stateless reads the only shape that fits, and it means retries and re-reads are always safe.
- The monitor gains `type` (print a text file) and `run` (load a COM file to 0100h and execute it — real bits on the real CPU).
- A minimal BDOS console shim at the canonical `0005h` entry so genuine CP/M COM files that do console I/O (including the library's `HELLO.COM` fixture) run unmodified: functions 1, 2, 9, 11, and function 0 / RET back to the monitor.
- Server: FREAD handling on shared volumes with strict 8.3 name validation (no traversal), plus oracle log records for reads.
- Harness: a run-COM scenario — the fixture's output on the console is the machine-side proof; FREAD records in the oracle log are the server-side proof.

Explicitly out of scope: the full resident BDOS + redirector (that is M2's boot-ladder milestone territory), writes of any kind (owned volumes stay post-M1), wildcards, user areas.

## Capabilities

### New Capabilities

- `com-loader`: loading a COM file from a network drive into the TPA at 0100h, the minimal BDOS console shim, program entry/exit conventions, and honest failure when the file doesn't exist or doesn't fit.

### Modified Capabilities

- `wire-protocol`: ADDED — the FREAD verb (stateless read-at-offset, short-read EOF semantics, new error code for file-not-found).
- `server`: ADDED — FREAD handling with 8.3 name validation and read logging.
- `emulator-harness`: ADDED — the run-COM scenario asserting both console output and oracle read records.

## Impact

- `machine/bios.asm` grows the FREAD client, load loop, BDOS shim, and two commands; the frame receiver learns to deliver payloads to arbitrary memory (loading goes straight to the TPA, not through RBUF).
- `server/retronix_server.py` and both protocol constant files gain FREAD and the `file-not-found` error code (additive — M0 codes and verbs are untouched, per the version-0 additive-growth rule).
- `harness/run_m0.py` gains a scenario; existing scenarios unchanged.
- No breaking changes; M0's proof keeps passing throughout.
