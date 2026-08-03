# wire-protocol Specification

## Purpose
TBD - created by archiving change m0-spine. Update Purpose after archive.
## Requirements
### Requirement: Length-prefixed binary frames
Every message SHALL be a binary frame: a fixed header (format/version byte, function code byte, 16-bit payload length), followed by the raw payload, followed by a checksum. Payloads MUST NOT be escaped or encoded — any byte value is legal anywhere in the payload.

#### Scenario: Well-formed frame is accepted
- **WHEN** the server receives a frame whose length field matches the payload and whose checksum verifies
- **THEN** the server processes the request and answers with exactly one response frame

#### Scenario: Corrupt frame is rejected in-band
- **WHEN** the server receives a frame whose checksum does not verify
- **THEN** the server answers with an error response frame (bad-frame code) and remains ready for the next request

### Requirement: Machine-initiated, one outstanding request
The machine SHALL initiate every exchange; the server MUST NOT send unprompted frames. The machine MUST NOT send a new request before receiving the response (or timing out) on the previous one.

#### Scenario: Server stays silent between requests
- **WHEN** no request frame is in flight
- **THEN** the server sends no bytes on the wire

### Requirement: HELLO opens every session
The first request after boot SHALL be a HELLO carrying the machine ID, ROM version, and self-test inventory. The success response SHALL carry the profile's current drive map.

HELLO SHALL additionally be re-issuable at any time, on a fresh connection or on one that has already completed a HELLO, and SHALL be idempotent: a repeated HELLO from the same machine ID is a valid request that the server answers with the profile's drive map as it stands, never an error for having been asked twice. This is what makes one-command re-binding possible after a link loss; it introduces no new verb, code, or payload.

#### Scenario: Known machine receives its drive map
- **WHEN** a machine sends HELLO with a machine ID that matches a server-side profile
- **THEN** the response contains the profile's drive map binding at least one drive letter to a volume

#### Scenario: Unknown machine is refused cleanly
- **WHEN** a machine sends HELLO with a machine ID the server has no profile for
- **THEN** the response is an error frame (unknown-machine code), and the server logs the refusal

#### Scenario: Re-HELLO on an established session is accepted
- **WHEN** a machine sends a second HELLO on a connection that already completed one
- **THEN** the response is an ok frame carrying the profile's current drive map, and the session remains usable for subsequent verbs

#### Scenario: Re-HELLO after reconnect is accepted
- **WHEN** a machine reconnects after the link dropped and sends HELLO again
- **THEN** the response carries the drive map exactly as a first HELLO would, and both exchanges appear in the oracle log

### Requirement: DIR verb lists a bound volume
The DIR request SHALL name a drive letter from the machine's drive map and SHALL return the file entries (name, extension, size) of the bound volume. DIR MUST be idempotent.

#### Scenario: DIR on a bound drive returns entries
- **WHEN** the machine sends DIR for a drive letter bound in its HELLO response
- **THEN** the response lists every file on the bound volume with name and size

#### Scenario: DIR on an unbound drive is an error
- **WHEN** the machine sends DIR for a drive letter its drive map does not bind
- **THEN** the response is an error frame (unbound-drive code)

#### Scenario: Retry yields identical result
- **WHEN** the machine times out and re-sends an identical DIR request
- **THEN** the response content is identical to what the lost response would have carried

### Requirement: Errors are in-band response codes
Every failure the server can detect SHALL be reported as a response frame carrying an error code from a defined table. Error codes MUST be mappable onto honest BDOS error returns by the machine side.

#### Scenario: Error table is closed
- **WHEN** any request fails for any reason
- **THEN** the error code in the response is one of the codes defined in the version-0 table

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

