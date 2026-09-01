# foundry Specification

## Purpose
TBD - created by archiving change m3-foundry. Update Purpose after archive.
## Requirements
### Requirement: Machine profiles live in a per-machine store
The server SHALL keep machine profiles as one JSON file per machine in a store directory (`server/machines/<id>.json` by default), and SHALL accept a `--machines-dir` option naming a different directory so tests and harness scenarios can each run against their own store. Volume definitions SHALL live outside the machine store so the store directory holds machine profiles and nothing else.

A profile SHALL carry: the machine ID; identity (make, model, notes); the platform and the ROM template it mints from; link config; drive map; profile state (`probe` or `exact`); hardware facts split into **declared** (what the operator asserted) and **observed** (what HELLO reported); mint state (the checksum of the block last stamped, and when); and the `needs-remint` flag.

#### Scenario: A profile resolves a HELLO from the store
- **WHEN** the server starts against a store directory containing a profile and a HELLO arrives with that machine ID
- **THEN** the server answers with that profile's drive map, exactly as it did when profiles came from a single static file

#### Scenario: Each scenario gets its own store
- **WHEN** the server is started with `--machines-dir` naming a temporary directory
- **THEN** it reads profiles from that directory only, and the repository's own store is neither read nor written

#### Scenario: Declared and observed are separate fields
- **WHEN** a profile is created with a declared RAM size and a HELLO later reports a different one
- **THEN** the declared value is unchanged and the observed value carries what the machine reported

### Requirement: The running server never mutates identity, map, or mint state
All creation and editing of profiles SHALL go through the foundry CLI. The running server SHALL write only reconciliation results — observed hardware facts, the last-seen ROM version, and the `needs-remint` flag. It SHALL NOT create profiles, assign machine IDs, alter identity, alter the drive map, alter link config, or alter mint state.

#### Scenario: HELLO from an unknown machine creates nothing
- **WHEN** a HELLO arrives carrying a machine ID with no profile in the store
- **THEN** the server answers unknown-machine and no profile file is created

#### Scenario: Reconciliation touches only observed fields
- **WHEN** a HELLO is reconciled against a profile
- **THEN** the file's identity, platform, link config, drive map, and mint state are byte-identical to what they were before, and only observed facts, last-seen ROM version, state, and the `needs-remint` flag may have changed

### Requirement: Machine IDs are sequential from 1001 and never reused
The foundry SHALL assign machine IDs from an explicit high-water mark held in the store (`.next-id`), starting at 1001. Creating a profile SHALL advance the mark before the profile is written, so an interrupted create leaks an ID rather than reissuing one. The foundry SHALL NOT derive the next ID from the profiles that happen to exist.

#### Scenario: Sequential assignment
- **WHEN** two profiles are created in a store whose mark is at 1001
- **THEN** they are assigned 1001 and 1002 and the mark stands at 1003

#### Scenario: A retired machine's ID is not recycled
- **WHEN** the profile for the highest-numbered machine is deleted and a new profile is created
- **THEN** the new profile is assigned the next ID after the deleted one, not the deleted one

### Requirement: Minting stamps a config block into a ROM template
Minting SHALL copy the profile's platform ROM template byte for byte and rewrite only the reserved config block (ADR-0006). No assembler SHALL run on the mint path. The block SHALL carry a magic, a block-format version, the machine ID as 32-bit little-endian, the link config, the profile's drive map cached in the machine-side fixed-stride entry format, and a checksum computed by the same rule as a wire frame's, so that summing the defined block yields zero.

Mint output SHALL be written under `build/mint/<id>.bin` and SHALL NOT be committed. The foundry SHALL record the stamped block's checksum and the mint time in the profile.

#### Scenario: Minting is byte-deterministic
- **WHEN** the same profile is minted twice against the same template
- **THEN** the two output images are byte-identical

#### Scenario: Only the block differs from the template
- **WHEN** a mint is compared byte for byte against the ROM template it was made from
- **THEN** every byte outside the reserved config block is identical

#### Scenario: The stamped machine ID matches the profile
- **WHEN** a profile with machine ID 1002 is minted
- **THEN** the four little-endian bytes at the block's machine-ID offset decode to 1002

#### Scenario: The stamped block verifies
- **WHEN** a minted image's config block is summed under the wire checksum rule
- **THEN** the sum is zero, and altering any byte of the block makes it non-zero

#### Scenario: Two profiles produce two different images
- **WHEN** two profiles with different machine IDs and different drive maps are minted from one template
- **THEN** the images differ only inside the config block, and each carries its own ID and map

### Requirement: The foundry CLI is the operator surface
The foundry SHALL provide a command-line interface with at minimum: `new` (create a profile, assigning the next machine ID), `list` (every profile with its ID, make and model, state, and whether it needs a re-mint), `show <id>` (one profile in full, including declared versus observed facts and mint state), and `mint <id>` (produce boot media from that profile). `list` and `show` SHALL surface the `needs-remint` flag prominently enough that an operator cannot miss a stale ROM.

#### Scenario: new assigns an ID and writes a probe profile
- **WHEN** the operator runs `new` with a make, model, and platform
- **THEN** a profile file appears in the store carrying the next machine ID, state `probe`, and no mint state

#### Scenario: list surfaces the drift flag
- **WHEN** a profile has `needs-remint` set and the operator runs `list`
- **THEN** that machine's line reports that it needs a re-mint

#### Scenario: show distinguishes declared from observed
- **WHEN** the operator runs `show` on a profile that has been booted at least once
- **THEN** the output presents the declared facts and the observed facts as separate, comparable sets

#### Scenario: mint refuses an unknown machine
- **WHEN** the operator runs `mint` with an ID no profile in the store carries
- **THEN** the command fails with a clear message and writes no image

### Requirement: The profile is born probe and becomes exact only by agreement
A profile created by `new` SHALL be in state `probe`. It SHALL become `exact` only after a HELLO whose reported inventory and ROM version agree with the profile and with what the last mint stamped, with no declared fact left unobserved. `mint` on a profile carrying `needs-remint` SHALL stamp the reconciled values and clear the flag; the state SHALL become `exact` on the next agreeing HELLO, not at mint time.

#### Scenario: Born probe
- **WHEN** a profile is created
- **THEN** its state is `probe` and `needs-remint` is clear

#### Scenario: Minting does not confer exactness
- **WHEN** a profile carrying `needs-remint` is re-minted
- **THEN** the flag clears, the mint state records the new block, and the state remains `probe` until a HELLO agrees

#### Scenario: Agreement makes it exact
- **WHEN** a machine boots from a mint whose stamped values match everything its HELLO reports
- **THEN** the profile's state becomes `exact` and `needs-remint` stays clear

### Requirement: An agent skill teaches the provision loop
The repository SHALL carry an agent skill at `.claude/skills/foundry/SKILL.md` describing the provision loop end to end: create a profile, mint it, boot the machine, inspect the refine state, re-mint when the profile says a re-mint is needed. It SHALL name the CLI verbs and the store layout, and SHALL state that the running server never mutates profiles.

#### Scenario: The loop is documented as a loop
- **WHEN** an agent reads the skill
- **THEN** it can carry out `new` → `mint` → boot → check state → re-mint without reading the foundry's source

