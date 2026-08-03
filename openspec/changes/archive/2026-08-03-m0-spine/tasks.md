# M0 Spine — Tasks

## 1. Toolchain & Skeleton

- [x] 1.1 Install and verify the toolchain: zmac (or fall back to Macro Assembler AS) and SIMH AltairZ80; record versions in the README
- [x] 1.2 Create repo layout (`machine/`, `server/`, `harness/`) with a root Makefile exposing `make image`, `make server`, `make m0`
- [x] 1.3 Define the shared protocol constants (frame layout, function codes, error table) once, mirrored as `machine/protocol.inc` and `server/protocol.py`, with a comment linking each to ADR-0003

## 2. Server

- [x] 2.1 Implement frame codec in Python: encode/decode, length validation, additive checksum, unit tests including corrupt-checksum rejection
- [x] 2.2 Implement `profiles.json` loading (machine ID → make/model, drive map) and the shared read-only volume backed by a host directory with 8.3 uppercase name mapping
- [x] 2.3 Implement HELLO handling: validate machine ID, record ROM version + inventory, respond with drive map; unknown ID → unknown-machine error
- [x] 2.4 Implement DIR handling for a bound drive letter (entries with name and size); unbound drive → unbound-drive error; verify retry returns identical bytes
- [x] 2.5 Implement the JSONL structured log (machine ID, verb, params, result code, timestamp per exchange) and a TCP listener for the SIMH socket attach

## 3. Machine Image

- [x] 3.1 Write BIOS bring-up in 8080 subset: banner with ROM version on the SIMH console, 2SIO init for both channels from assembled-in link config
- [x] 3.2 Implement self-test inventory collection (CPU detect, RAM size, serial status) into the HELLO payload buffer
- [x] 3.3 Implement the machine-side frame layer: send request, receive response, checksum verify, timeout with bounded retry
- [x] 3.4 Implement HELLO at boot storing the returned drive map; on exhausted retries fall through to the prompt in local-only mode (no reboot needed to land somewhere usable)
- [x] 3.5 Implement the monitor prompt with `dir`: issue DIR for a bound drive, print returned entries; print an honest error message for error responses
- [x] 3.6 Verify the image assembles in strict 8080 mode and boots to banner in SIMH via `load` + `go` (zmac `.8080` mode; runtime-enforced with SIMH `set cpu 8080`)

## 4. Harness & Proof

- [x] 4.1 Write the SIMH driver: generate the .ini (load image, attach 2SIO to socket, go), start server then SIMH, ordered and headless
- [x] 4.2 Write assertions against the server JSONL log: HELLO seen with expected machine ID and inventory fields, DIR answered with expected entries; exit code reflects assertions
- [x] 4.3 Implement deterministic teardown of both processes on success and failure; prove two consecutive runs need no manual cleanup
- [x] 4.4 Add negative-path runs: server down at boot → machine reaches local-only prompt; unknown machine ID → clean refusal logged
- [x] 4.5 Wire it all to `make m0`, run it ten times consecutively green, and record the spine proof (command + expected log shape) in the README
