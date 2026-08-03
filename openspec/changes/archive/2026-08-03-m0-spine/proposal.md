# M0 — The Spine

## Why

Every architectural decision is now committed (ADR-0001..0005) but none has touched running code. M0 proves the whole spine in one exchange — boot banner → HELLO against a machine profile → drive map returned → `dir` on a bound volume — so that BIOS hook, wire protocol, and server all shake hands before anything else is built. If this works, everything after is adding verbs (PRD §10, §13).

## What Changes

- A minimal RetroNix BIOS + monitor boots on SIMH AltairZ80, prints a banner, and initializes the serial link.
- The machine opens the session with a HELLO carrying machine ID, ROM version, and self-test inventory; the server answers with the profile's drive map (ADR-0005, config reconciliation deferred to session-tier only for M0).
- A first wire protocol implementation: length-prefixed binary frames with checksum, machine-initiated, one outstanding request, HELLO and DIR verbs only (ADR-0003).
- A minimal server: one static machine profile, one shared read-only volume, HELLO and DIR handling, and a structured protocol log that acts as the test oracle (PRD §9).
- A scripted emulator harness: bring up SIMH + server, run the exchange, assert against the server's structured log, tear down — repeatable by an agent in seconds.

Explicitly out of scope: the redirector/BDOS interception, the Unix shell surface, local floppies, owned volumes, config screen, foundry/minting, real hardware.

## Capabilities

### New Capabilities

- `wire-protocol`: frame format (header, length, checksum), session opening via HELLO, the DIR verb, in-band error codes, timeout/retry semantics with idempotent requests.
- `machine-boot`: BIOS + monitor bring-up on SIMH AltairZ80 — banner, serial init, self-test inventory, HELLO at boot, and a minimal prompt that can issue `dir`.
- `server`: machine profiles (static for M0), volume export (one shared read-only volume), HELLO and DIR request handling, structured protocol logging as the test oracle.
- `emulator-harness`: deterministic scripted bring-up/run/assert/teardown loop around SIMH and the server, suitable for hundreds of agent-driven iterations.

### Modified Capabilities

None — this is the first change; no specs exist yet.

## Impact

- New codebase from zero: 8080/Z80 assembly for the machine side (assembler/toolchain chosen in design), a host-language server (language chosen in design), and harness scripts.
- New external dependency: SIMH AltairZ80 (Schorn build) with socket-redirected serial console.
- No existing code or users are affected; nothing is breaking.
- Sets the protocol's version-0 frame shape that M1+ will extend — verbs are additive after this change.
