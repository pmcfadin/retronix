# server — M1 delta

## ADDED Requirements

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
