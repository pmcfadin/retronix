# emulator-harness Specification

## Purpose
TBD - created by archiving change m0-spine. Update Purpose after archive.
## Requirements
### Requirement: One-command scripted run
The harness SHALL provide a single command that starts the server, boots the machine image in SIMH with the serial console redirected to a socket, waits for the M0 exchange, and exits. It MUST run headless with no operator interaction.

#### Scenario: Clean run from a cold start
- **WHEN** the harness command is invoked on a machine with SIMH installed and no prior state
- **THEN** it completes the boot → HELLO → dir sequence and exits without prompting

### Requirement: Assertions against the server log
The harness SHALL evaluate success by asserting against the server's structured protocol log (HELLO received with expected machine ID; DIR answered with expected entries) — not by scraping emulator terminal output. The command's exit code SHALL be 0 exactly when all assertions pass.

#### Scenario: Failing exchange fails the run
- **WHEN** the machine image never sends a valid HELLO within the timeout
- **THEN** the harness exits non-zero and reports which assertion failed

### Requirement: Deterministic teardown
The harness SHALL terminate the SIMH and server processes it started, on success and on failure alike, leaving no orphaned processes or bound sockets behind.

#### Scenario: Teardown after failure
- **WHEN** a run fails mid-exchange
- **THEN** subsequent runs start cleanly with no manual cleanup

