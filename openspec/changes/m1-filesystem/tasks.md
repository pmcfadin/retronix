# M1 Filesystem — Tasks

## 1. Protocol

- [ ] 1.1 Add FREAD function code and FNOTFND error code to `server/protocol.py` and `machine/protocol.inc`, keeping the two files in lockstep
- [ ] 1.2 Unit-test FREAD framing: request layout (drive, 8.3 name, offset, length), response layout (actual count + bytes)

## 2. Server

- [ ] 2.1 Implement 8.3 name validation (allowlist charset, no separators/dot-dot) with unit tests including traversal attempts
- [ ] 2.2 Implement FREAD on shared volumes: offset/length reads, short-read EOF, zero-byte ok past EOF, file-not-found; verify identical bytes on repeated requests
- [ ] 2.3 Add the FREAD oracle record (machine, drive, name, offset, requested, actual, result) with unit tests

## 3. Machine

- [ ] 3.1 Parameterize the frame receiver with a destination pointer; control responses default to RBUF as today
- [ ] 3.2 Implement the FREAD client: build request, receive payload to a caller-supplied address, loop chunks of 512 until short read
- [ ] 3.3 Implement `type <file>`: FREAD loop through a bounce buffer, print printable bytes, honest error for file-not-found
- [ ] 3.4 Implement `run <file>`: stream chunks to 0100h, verify full load, set up shim state, jump; report file-not-found and oversize honestly
- [ ] 3.5 Implement the BDOS console shim at 0005h (functions 0, 1, 2, 9, 11; honest failure for others) with RET-to-monitor via planted stack
- [ ] 3.6 Rebuild strict-8080 and confirm M0's three harness scenarios still pass unchanged

## 4. Proof

- [ ] 4.1 Add the run-COM harness scenario: send `run hello.com`, match the fixture's own console output via SIMH expect, assert the FREAD trail (tiling offsets, all ok) in the oracle log
- [ ] 4.2 Add a type-and-missing-file scenario: `type about.txt` output matched; `run nope.com` yields file-not-found on console and in the log
- [ ] 4.3 Run the full harness (all five scenarios) ten times consecutively green and update the README's proof section
