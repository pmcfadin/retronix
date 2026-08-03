# wire-protocol — M1 delta

## ADDED Requirements

### Requirement: FREAD verb reads file bytes statelessly
The FREAD request SHALL name a drive letter, an 8.3 filename, a 32-bit byte offset, and a 16-bit length; the success response SHALL carry the actual byte count followed by the bytes. The server MUST hold no per-file state between requests (ADR-0003): the same request always yields the same response for an unchanged volume.

#### Scenario: Read at offset
- **WHEN** the machine sends FREAD for an existing file with offset 9 and length 16
- **THEN** the response carries exactly the 16 bytes starting at offset 9

#### Scenario: Short read signals EOF
- **WHEN** the requested range extends past the end of the file
- **THEN** the response carries only the bytes that exist, and a read wholly past EOF carries zero bytes with an ok result

#### Scenario: Retry yields identical bytes
- **WHEN** the machine times out and re-sends an identical FREAD
- **THEN** the response bytes are identical to what the lost response carried

### Requirement: file-not-found error code
The v0 error table SHALL gain a `file-not-found` code, returned when an FREAD names a file absent from the bound volume. The code MUST be mappable onto an honest BDOS error return.

#### Scenario: Missing file
- **WHEN** the machine sends FREAD for a name not present on the volume
- **THEN** the response is an error frame carrying the file-not-found code
