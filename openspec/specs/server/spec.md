# server Specification

## Purpose
TBD - created by archiving change m0-spine. Update Purpose after archive.
## Requirements
### Requirement: Static machine profiles
The server SHALL load machine profiles at startup from a store directory holding one JSON file per machine, defaulting to `server/machines/` and overridable with `--machines-dir`. Volume definitions SHALL be configured separately from the machine store, so the store directory holds machine profiles only.

A profile MUST carry at minimum: machine ID, make/model, platform and ROM template, link config, a drive map binding drive letters to volume names, profile state (`probe` or `exact`), declared and observed hardware facts kept as separate sets, mint state, and the `needs-remint` flag. Profiles SHALL NOT be created at runtime by the server; creation and every edit other than reconciliation belong to the foundry CLI.

#### Scenario: Profile resolves a HELLO
- **WHEN** a HELLO arrives with a machine ID present in the store
- **THEN** the server responds with that profile's drive map

#### Scenario: A different store is used when asked
- **WHEN** the server is started with `--machines-dir` naming another directory
- **THEN** it serves the profiles in that directory and neither reads nor writes the default store

#### Scenario: Two machines, two profiles, two maps
- **WHEN** the store holds profiles for two machine IDs with different drive maps and each sends HELLO in turn
- **THEN** each receives its own profile's map and neither sees the other's bindings

### Requirement: Shared read-only volume export
The server SHALL export at least one named volume backed by a host directory, marked shared read-only (ADR-0002). File entries SHALL surface CP/M-compatible names (8.3 uppercase).

#### Scenario: Host files appear in DIR
- **WHEN** the backing directory contains `HELLO.COM` and DIR is requested for the drive bound to that volume
- **THEN** the response includes `HELLO.COM` with its size

### Requirement: HELLO handling with inventory capture
On HELLO, the server SHALL validate the machine ID, record the reported ROM version and self-test inventory into the profile's observed facts, reconcile as specified above, and answer with the profile's drive map. Unknown machine IDs SHALL be refused with the unknown-machine error code and SHALL NOT cause a profile to be created.

#### Scenario: Inventory is recorded
- **WHEN** a valid HELLO is processed
- **THEN** the profile's observed inventory reflects what the machine reported, and its declared facts are untouched

#### Scenario: Unknown machine creates nothing
- **WHEN** a HELLO arrives with a machine ID no profile carries
- **THEN** the response is the unknown-machine error and the store gains no file

### Requirement: Structured protocol log as test oracle
The server SHALL log every request and response as a structured record (machine ID, verb, parameters, result code, timestamp) to a machine-readable stream. Assertions in tests SHALL be possible against this log alone, without scraping terminal output.

#### Scenario: One exchange, two records
- **WHEN** a machine completes a HELLO followed by a DIR
- **THEN** the log contains exactly one HELLO record and one DIR record for that machine ID, each with its result code

### Requirement: FREAD handling with strict name validation
The server SHALL serve FREAD from shared volumes by mapping the 8.3 request name onto the backing directory. Names MUST be validated as plain 8.3 (no path separators, no dot-dot, printable ASCII); anything else is rejected as a bad request, never resolved against the host filesystem.

#### Scenario: Traversal attempt is refused
- **WHEN** an FREAD names something containing a path separator or parent reference
- **THEN** the server answers bad-request and the host filesystem outside the volume root is never touched

### Requirement: Read exchanges are logged
Every FREAD SHALL produce one oracle log record carrying machine ID, drive, filename, offset, requested and actual length, and result code.

#### Scenario: A COM load leaves a read trail
- **WHEN** a machine loads a file via a sequence of FREAD requests
- **THEN** the log shows one record per request, with offsets that tile the file

### Requirement: HELLO reconciles the profile against what the machine reports
On every HELLO — first of a session or a repeat — the server SHALL compare the reported self-test inventory and ROM version against the profile and against the values the profile's last mint recorded, and SHALL reconcile in three tiers (ADR-0005): the drive map it answers with is the profile's current one; the profile's **observed** hardware facts are updated to what the machine reported; and where the reported values disagree with what was minted, the server SHALL set the profile's `needs-remint` flag rather than pretending the burned ROM changed.

When everything the machine reports agrees with the profile and with the last mint, and no declared fact remains unobserved, the server SHALL clear `needs-remint` and set the profile's state to `exact`.

Reconciliation SHALL be idempotent: two identical HELLOs leave the profile in the same state as one.

#### Scenario: An unexpected RAM size refines the profile
- **WHEN** a machine whose profile declares an unknown RAM size sends HELLO reporting 63 KB
- **THEN** the profile's observed RAM size becomes 63 KB, `needs-remint` is set, and the response still carries the profile's drive map

#### Scenario: A matching boot makes the profile exact
- **WHEN** a machine boots from a mint stamped with the reconciled values and its HELLO reports exactly those values
- **THEN** the profile's state becomes `exact` and `needs-remint` is clear

#### Scenario: Editing the profile after minting is drift
- **WHEN** a profile's drive map or link config is changed after the machine was minted, and the machine sends HELLO
- **THEN** the server sets `needs-remint`, and the HELLO response carries the edited drive map so the running session is correct even though the ROM is stale

#### Scenario: Reconciliation is idempotent
- **WHEN** a machine sends the same HELLO twice on one session
- **THEN** the profile after the second is identical to the profile after the first

#### Scenario: Drift is visible to the operator, not only to the server
- **WHEN** `needs-remint` has been set by a HELLO
- **THEN** the flag is persisted in the profile file, so the foundry CLI reports it without the server running

