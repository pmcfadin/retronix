## ADDED Requirements

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

#### Scenario: The second mint differs from the first
- **WHEN** the two mints of that profile are compared
- **THEN** they differ only inside the config block, and the second carries the reconciled values

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
