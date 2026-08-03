## MODIFIED Requirements

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
