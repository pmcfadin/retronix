# M0 Spine — Design

## Context

Greenfield: no code exists. The architecture is fixed by ADR-0001..0005; M0 implements the thinnest vertical slice that exercises all of it — boot, HELLO, drive map, one DIR — entirely under SIMH AltairZ80 with the serial wire on a socket. The server doubles as the test oracle via its structured log (PRD §9).

## Goals / Non-Goals

**Goals:**
- One command proves the spine end-to-end and is cheap enough to run hundreds of times.
- The version-0 frame shape ships here and only grows additively afterward.
- Machine-side code is honest 8080 code that will later run on real iron unchanged in spirit (different BIOS port, same protocol layer).

**Non-Goals:**
- No CP/M BDOS/CCP in the image yet — M0 is BIOS + monitor only; the redirector arrives with M1.
- No local disk, no owned volumes, no config screen, no foundry, no real hardware.
- No performance work; 9600 baud equivalent is fine.

## Decisions

**Machine code targets the 8080 instruction subset, assembled with `zmac`.**
Writing 8080-only mnemonics keeps every PRD target (8080 and Z80) in play from day one. `zmac` is a maintained cross-assembler with 8080 support and plain binary output; Macro Assembler AS is the fallback if `zmac` proves awkward. Rejected: sjasmplus (Z80-only), native CP/M ASM (kills the fast iteration loop).

**The M0 image is a raw binary SIMH loads directly (`load` + `go`), not a disk image.**
Fastest possible edit-assemble-boot loop; no media formats to get right yet. The "mint" concept is honored in miniature: link config and machine ID are assembled-in constants — the image is born configured (ADR-0005).

**Two serial channels: SIMH console for the operator prompt, the 2SIO's second port attached to a TCP socket for the wire.**
Keeps human-visible output and protocol bytes strictly separate, so the harness never parses prompt text off the same channel the frames use. The server listens on the socket; SIMH connects on attach.

**Server and harness in Python 3, stdlib only.**
Iteration speed dominates at M0 and the server is I/O-bound at vintage baud rates; `socket`, `json`, and `logging` cover everything. Rejected: Go/Rust (compile step buys nothing yet — revisit if the server grows real concurrency needs), Node (adds a runtime dependency the harness doesn't need).

**Frame v0: `[version][function][len-lo][len-hi][payload…][checksum]`, additive 8-bit checksum.**
An additive checksum is a few instructions on the 8080; the leading version byte is the escape hatch to CRC-16 later without breaking framing. Error codes are a closed table in a shared constants file mirrored between the asm and Python sides.

**Profiles are a `profiles.json` the server reads at startup; machine ID is a 32-bit integer.**
Static config satisfies the M0 spec; the real profile store arrives with the foundry (M3). JSON because the harness asserts against JSONL logs already.

**Structured log is JSON Lines to a file, one record per request/response pair.**
The harness asserts on parsed records (machine ID, verb, result code), never on terminal text.

**Repo layout:** `machine/` (asm + build), `server/` (Python), `harness/` (runner + assertions), `Makefile` at root with `make m0` as the one command.

## Risks / Trade-offs

- [SIMH socket-serial semantics (attach direction, buffering) differ from real UARTs] → the protocol already assumes latency and one outstanding request (ADR-0003); harness owns startup ordering (server first, then SIMH).
- [Additive checksum is weak against burst errors on real cables] → acceptable inside an emulator; version byte reserves the CRC-16 upgrade path before real iron (M5).
- [8080-subset discipline could silently slip (Z80-only opcodes)] → assemble in 8080 mode so violations are build errors, not review findings.
- [zmac availability/quirks] → Macro Assembler AS as named fallback; the Makefile isolates the assembler behind one variable.

## Migration Plan

Greenfield — nothing to migrate. Rollback is deleting the change; nothing external depends on M0 output.

## Open Questions

None blocking. The CRC-16 upgrade and the console-vs-wire port assignments on *real* hardware are M5 concerns.
