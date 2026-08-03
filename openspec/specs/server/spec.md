# server Specification

## Purpose
TBD - created by archiving change m0-spine. Update Purpose after archive.
## Requirements
### Requirement: Static machine profiles
The server SHALL load machine profiles from configuration at startup. A profile MUST carry at minimum: machine ID, make/model, and a drive map binding drive letters to volume names. M0 does not require creating or editing profiles at runtime.

#### Scenario: Profile resolves a HELLO
- **WHEN** a HELLO arrives with a machine ID present in configuration
- **THEN** the server responds with that profile's drive map

### Requirement: Shared read-only volume export
The server SHALL export at least one named volume backed by a host directory, marked shared read-only (ADR-0002). File entries SHALL surface CP/M-compatible names (8.3 uppercase).

#### Scenario: Host files appear in DIR
- **WHEN** the backing directory contains `HELLO.COM` and DIR is requested for the drive bound to that volume
- **THEN** the response includes `HELLO.COM` with its size

### Requirement: HELLO handling with inventory capture
On HELLO, the server SHALL validate the machine ID, record the reported ROM version and self-test inventory against the profile, and answer with the drive map. Unknown machine IDs SHALL be refused with the unknown-machine error code.

#### Scenario: Inventory is recorded
- **WHEN** a valid HELLO is processed
- **THEN** the profile's recorded inventory reflects what the machine reported

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

