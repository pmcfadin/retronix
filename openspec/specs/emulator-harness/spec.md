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

### Requirement: run-COM scenario
The harness SHALL include a scenario that boots the machine, runs the library's HELLO.COM from the prompt, and passes only when both proofs hold: SIMH's matcher sees the program's own console output, and the oracle log shows the FREAD sequence that delivered the file (offsets tiling the file, all ok).

#### Scenario: The payoff run
- **WHEN** the run-COM scenario executes
- **THEN** it exits 0 with the fixture's output matched on the console and the read trail present in the oracle log

#### Scenario: M0 scenarios keep passing
- **WHEN** the full harness runs after M1 lands
- **THEN** spine, server-down, and unknown-machine still pass unchanged

### Requirement: Mid-run server control
The harness SHALL be able to stop and restart the server while SIMH is still running, driven by a marker the machine prints on the console, so that link loss and link return can be staged inside a single boot. The restarted server SHALL listen on the same port and write to the same oracle log as the one it replaces, so assertions cover the whole run. Deterministic teardown SHALL still hold: whichever server process is alive at the end of the scenario is terminated, on success and on failure alike.

#### Scenario: Server stopped and restarted inside one boot
- **WHEN** a scenario stops the server after the machine has reached the prompt and restarts it on the same port
- **THEN** SIMH keeps running throughout, and the oracle log holds the records from both server lifetimes in order

#### Scenario: Teardown after a staged restart
- **WHEN** a scenario that restarted the server fails partway through
- **THEN** no server process or bound socket survives the run, and the next run starts cleanly

### Requirement: Boot-ladder inspection scenarios
The harness SHALL include scenarios proving the ladder is inspectable from the prompt: `ls /dev` in both link states and `config` in both link states. Each SHALL assert on the machine's console output via SIMH's matcher — these commands touch no wire, so the oracle log is not the evidence — and SHALL additionally assert that the oracle log records no request for the interval in which they run.

#### Scenario: /dev while linked
- **WHEN** the scenario sends `ls /dev` after a successful HELLO
- **THEN** the console shows the self-test devices and the bound drive letter with its volume name, and the oracle log gained no record

#### Scenario: /dev in local-only mode
- **WHEN** the scenario boots with no server and sends `ls /dev`
- **THEN** the console shows the wire down and no drive letter claiming a live volume

#### Scenario: config in both link states
- **WHEN** the scenario sends `config` with the link up and again on a local-only boot
- **THEN** both runs show the machine ID, ROM version, and link config, and the link state each reports matches the rung the machine is on

### Requirement: Link-recovery scenario
The harness SHALL include a scenario that proves one-command recovery end to end within a single boot: boot with the server up, stop the server, confirm a wire command now fails honestly on the console, restart the server, send `bind`, and confirm the link is back. It SHALL pass only when both proofs hold — the console shows the recovery and a post-`bind` wire command succeeding, and the oracle log shows two ok HELLO records for the machine, the second after the restart.

#### Scenario: The recovery run
- **WHEN** the link-recovery scenario executes
- **THEN** it exits 0, with the honest failure and the successful re-bind both matched on the console, and two ok HELLO records in the oracle log

#### Scenario: Recovery without a reboot
- **WHEN** the machine re-binds after the server returns
- **THEN** the console shows no second boot banner, proving the prompt was never restarted

#### Scenario: Earlier milestones keep passing
- **WHEN** the full harness runs after M2 lands
- **THEN** the spine, run-COM, type-missing, server-down, and unknown-machine scenarios still pass unchanged

### Requirement: A second emulator target with a ROM-owned console channel
The harness SHALL be able to run a scenario under trs80gp as well as under SIMH AltairZ80, booting a minted image with `-rom`, taking the wire as a TCP endpoint the emulator dials out to, and reading the console from the printer-port TCP endpoint the ROM mirrors to (ADR-0007). It SHALL NOT depend on the emulator's stock-ROM expect/send layer, which is dead under a custom ROM.

Deterministic teardown SHALL hold for this target exactly as it does for SIMH: the emulator process and both sockets are cleaned up on success and failure alike. Scenarios SHALL run one emulator process at a time.

The trs80gp binary SHALL be obtained by a checksum-pinned download rather than built from source, and the harness SHALL fail with a clear message — never a silent skip — when the pinned binary is absent.

#### Scenario: A Model 4 scenario runs headless from one command
- **WHEN** the harness runs a trs80gp scenario
- **THEN** it boots the minted image, collects console output from the printer tap, evaluates its assertions, and exits without operator interaction

#### Scenario: Teardown on the second target
- **WHEN** a trs80gp scenario fails mid-run
- **THEN** no emulator process or bound socket survives, and the next run starts cleanly

#### Scenario: A missing pinned binary is reported, not skipped
- **WHEN** the pinned trs80gp binary is not present
- **THEN** the harness reports that the tool is missing and which command fetches it, rather than passing or silently omitting the scenario

### Requirement: Two machines of different makes see only their own configuration
The harness SHALL include a scenario that mints two profiles with different machine IDs and different drive maps — one Altair template, one Model 4 template — and boots each in turn against one server. It SHALL pass only when each machine's HELLO carries its own machine ID and each console reports only its own bindings, with no binding from the other machine's map appearing on either.

#### Scenario: Two mints, two identities
- **WHEN** the scenario boots machine 1001's image and then machine 1002's image
- **THEN** the oracle log holds one ok HELLO per machine ID, and neither machine ever presents the other's ID

#### Scenario: Each machine sees only its own map
- **WHEN** each machine runs `config` after its HELLO
- **THEN** its console lists the bindings of its own profile and none of the other profile's

### Requirement: The probe-to-exact loop is proven end to end
The harness SHALL include a scenario that walks the refine loop with no manual editing: create a profile whose hardware facts are declared unknown, mint it, boot it, confirm the server recorded the observed facts and raised `needs-remint`, re-mint from the reconciled profile, boot again, and confirm the profile is `exact` with the flag clear.

#### Scenario: The refine run
- **WHEN** the probe-loop scenario executes
- **THEN** it exits 0, having shown the flag set after the first boot, cleared by the re-mint, and the profile `exact` after the second boot

#### Scenario: Re-minting is deterministic and block-scoped
- **WHEN** the two mints of that profile are compared
- **THEN** every byte outside the config block is identical, and any difference lies inside the block — noting that hardware facts reconciled by the refine loop live in the profile, not the block, so for a hardware-only refinement the two blocks are legitimately byte-identical

### Requirement: Drift after minting is detected at HELLO
The harness SHALL include a scenario that edits a profile after its image was minted, boots that image, and passes only when the server raises `needs-remint` while still answering the HELLO with the edited drive map — proving the running session is correct even though the burned ROM is stale.

#### Scenario: Edited profile flags a stale ROM
- **WHEN** the drive map in a profile is changed after minting and the unchanged image is booted
- **THEN** the response carries the edited map, the profile ends the run with `needs-remint` set, and the foundry CLI reports it

### Requirement: The stamped block is proven against the machine's own report
The harness SHALL include a scenario asserting that what the foundry stamped is what the machine holds: it mints an image, boots it, runs `config`, and compares the machine ID, link config, and cached bindings on the console against the values the foundry wrote.

#### Scenario: Block integrity round trip
- **WHEN** the block-integrity scenario executes
- **THEN** the console's reported machine ID, link config, and baked bindings match the profile the image was minted from, and the block is reported valid

#### Scenario: Earlier milestones keep passing
- **WHEN** the full harness runs after M3 lands
- **THEN** the spine, run-COM, type-missing, server-down, unknown-machine, boot-ladder, and link-recovery scenarios still pass, now against a minted image rather than a hand-edited one

