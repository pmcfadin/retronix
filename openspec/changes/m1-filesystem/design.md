# M1 Filesystem — Design

## Context

M0 left a working spine: frame codec on both sides, HELLO/DIR verbs, oracle log, three-scenario harness. M1 adds the read path and program execution on top without touching anything M0 proved. The full resident BDOS + redirector stays out — M1's shim is deliberately the smallest thing that lets a genuine console-I/O COM run.

## Goals / Non-Goals

**Goals:**
- File bytes flow over the wire; a real COM file fetched from the library executes on the local CPU.
- Verbs stay additive and idempotent; M0's proof never breaks.

**Non-Goals:**
- No writes, no owned volumes, no OPEN/CLOSE handles, no wildcards, no user areas.
- Not the redirector: programs run against a console shim, not a full BDOS over local/remote drives. Disk-function BDOS calls (F_OPEN et al.) are out until the redirector milestone.

## Decisions

**FREAD is stateless read-at-offset — no OPEN/CLOSE verbs.**
ADR-0003 already outlawed server-side cursors, so file handles would be state with no owner. Request: drive, 8.3 name, offset(4), length(2). Response: actual-count(2) + bytes. EOF = short read; zero-byte ok read past EOF. Consequence: every chunk request is independently retryable, and `type`/`run` are just loops.

**Chunk size 512 bytes.**
Fits comfortably in a v0 frame, keeps the machine's per-chunk latency low, and divides the TPA cleanly. The loader asks for 512 until a short read says done.

**The frame receiver gains a destination pointer.**
M0's `rcvfrm` writes payloads to RBUF (256 bytes). M1 parameterizes the destination so FREAD payloads stream straight to the TPA at their final addresses — no copy, no size ceiling below the TPA itself. RBUF remains the default for control responses.

**BDOS shim: functions 0, 1, 2, 9, 11 at 0005h, plus RET-to-monitor.**
The canonical entry (JMP at 0005h, function in C) so real binaries work unmodified. Unsupported functions return failure honestly rather than faking success — a program that needs disk calls gets a clean "no", not corruption. The monitor plants the return path: warm boot (fn 0) and RET both land back at the prompt with the monitor's stack restored.

**Name validation is server-side allowlisting.**
Uppercase 8.3 built only from `[A-Z0-9$_-]` (the practical CP/M set); anything else — separators, dot-dot, control bytes — is bad-request before any path is formed. The volume root is the trust boundary.

**New error code FNOTFND joins the closed table in both constant files.**
Additive, mirrored in `machine/protocol.inc` and `server/protocol.py`, mapped by the monitor to an honest "file not found" message (and later by the redirector to the BDOS convention).

## Risks / Trade-offs

- [512-byte chunks mean a 20 KB COM takes ~40 round trips] → fine under SIMH; real-iron latency budgets are an M5 calibration, and DriveWire proves serial disk speeds are workable.
- [Programs can smash the monitor (they own the machine below the shim)] → accepted: that's what real CP/M is; the harness always cold-boots per scenario.
- [Shim's honest "no" may still confuse programs that assume disk BDOS] → library curation (BDOS-clean, console-only for M1) is the ADR-0001 consequence already on record.

## Migration Plan

Purely additive. M0 scenarios run unchanged before and after; land server verb first (server tolerates unknown verbs already), then machine side, then the harness scenario.

## Open Questions

None blocking. Whether `run` passes a command tail into the CP/M default FCB/DMA areas can be decided during implementation (the fixture doesn't need it).
