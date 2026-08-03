# emulator-harness — M1 delta

## ADDED Requirements

### Requirement: run-COM scenario
The harness SHALL include a scenario that boots the machine, runs the library's HELLO.COM from the prompt, and passes only when both proofs hold: SIMH's matcher sees the program's own console output, and the oracle log shows the FREAD sequence that delivered the file (offsets tiling the file, all ok).

#### Scenario: The payoff run
- **WHEN** the run-COM scenario executes
- **THEN** it exits 0 with the fixture's output matched on the console and the read trail present in the oracle log

#### Scenario: M0 scenarios keep passing
- **WHEN** the full harness runs after M1 lands
- **THEN** spine, server-down, and unknown-machine still pass unchanged
