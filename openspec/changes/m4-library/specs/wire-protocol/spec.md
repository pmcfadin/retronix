## ADDED Requirements

### Requirement: FWRITE verb writes file bytes idempotently
The FWRITE request SHALL name a drive letter, an 8.3 filename, a 32-bit byte offset, and a 32-bit total file size, followed by up to 512 bytes of chunk data; the total size MUST be present and consistent on every chunk of one file, not only the first. The server MUST hold no per-file state between requests (ADR-0003): on every FWRITE, the target file is created if absent and resized to exactly the given total size, then the chunk bytes are written at the given offset — so an identical resent chunk, or chunks arriving out of order, converge to the same final file. The success response SHALL carry the actual byte count written.

#### Scenario: Write at offset creates and sizes the file
- **WHEN** the machine sends FWRITE for a new file with total size 1024, offset 512, and 512 bytes of data
- **THEN** the file is created at exactly 1024 bytes, with the sent bytes at offset 512

#### Scenario: Retry lands identically
- **WHEN** the machine times out and re-sends an identical FWRITE chunk
- **THEN** the resulting file is byte-identical to what a single successful write would have produced

#### Scenario: Write against a volume the machine does not own is refused
- **WHEN** the machine sends FWRITE for a drive bound to a shared volume, or to an owned volume it does not own
- **THEN** the response is an error frame carrying the read-only-volume code, and the file on the volume is untouched

### Requirement: FDEL verb deletes a file idempotently
The FDEL request SHALL name a drive letter and an 8.3 filename. Deleting a file that does not exist MUST succeed, matching every other verb's idempotency rule (ADR-0003): a repeated FDEL for the same name is never an error for having been asked twice.

#### Scenario: Delete an existing file
- **WHEN** the machine sends FDEL for a file present on a volume it owns
- **THEN** the response is ok and the file no longer appears in a subsequent DIR of that volume

#### Scenario: Delete of an absent file succeeds
- **WHEN** the machine sends FDEL for a name not present on the volume
- **THEN** the response is ok, not an error

#### Scenario: Delete against a volume the machine does not own is refused
- **WHEN** the machine sends FDEL for a drive bound to a shared volume, or to an owned volume it does not own
- **THEN** the response is an error frame carrying the read-only-volume code, and no file is removed

### Requirement: read-only-volume error code
The v0 error table SHALL gain a `read-only-volume` code, returned by FWRITE and FDEL when the target drive resolves to a volume the requesting machine is not permitted to write — a shared volume, or an owned volume it does not own. The code MUST be mappable onto an honest BDOS error return.

#### Scenario: Write refusal is distinct from other errors
- **WHEN** an FWRITE or FDEL is refused for lack of write permission on the volume
- **THEN** the response carries the read-only-volume code, distinct from unbound-drive, bad-request, and file-not-found
