## ADDED Requirements

### Requirement: Owned volumes declare a single owner
A volume definition of kind `owned` SHALL carry an `owner` field naming the one machine ID permitted to write it. Volumes of kind `shared` carry no owner and are never writable over the wire by any machine.

#### Scenario: An owned volume's owner is loaded
- **WHEN** the server loads a volumes file containing an entry of kind `owned` with an `owner` field
- **THEN** that volume is available for binding and its owner is known for write-permission checks

### Requirement: HELLO binding resolution drops bindings it cannot honor
When resolving a profile's drive map at HELLO, the server SHALL drop — logging loudly server-side, silently absent from the response — any binding whose volume name does not exist in the loaded volumes, and any binding to a volume of kind `owned` whose `owner` does not match the connecting machine's ID. HELLO itself SHALL still succeed with the remaining bindings; a dropped binding is never a reason to refuse the whole HELLO.

#### Scenario: A second claimant's binding is dropped
- **WHEN** two profiles both bind a letter to the same owned volume, and the profile whose machine ID does not match the volume's owner sends HELLO
- **THEN** that letter is absent from its drive map, and a subsequent request against the letter — DIR, FREAD, FWRITE, or FDEL — answers the unbound-drive code

#### Scenario: The rightful owner's binding is honored
- **WHEN** the profile whose machine ID matches an owned volume's owner sends HELLO
- **THEN** that letter is present in its drive map with the flags bit that marks it writable

#### Scenario: A dropped binding does not fail the rest of HELLO
- **WHEN** a profile binds one letter to a volume it doesn't own and another letter to a shared volume
- **THEN** HELLO succeeds, the shared-volume binding is present, and only the disallowed binding is absent

### Requirement: FWRITE handling enforces ownership and idempotent chunked writes
The server SHALL serve FWRITE by resolving the drive to a bound volume, refusing with the read-only-volume code if that volume is shared or is owned by a different machine, and otherwise creating or resizing the target file to the request's total size and writing the chunk at the given offset on every call, with no memory of prior chunks.

#### Scenario: A push lands on the owner's volume
- **WHEN** a machine sends a sequence of FWRITE chunks covering an entire file to a volume it owns
- **THEN** the resulting file on disk matches the sent bytes exactly, regardless of the order chunks arrived in

#### Scenario: A write to someone else's owned volume never resolves
- **WHEN** a machine's drive map has no binding for a letter because HELLO dropped it (ownership mismatch)
- **THEN** FWRITE against that letter answers unbound-drive, never read-only-volume, because the drive was never bound to begin with

### Requirement: FDEL handling is idempotent and enforces ownership
The server SHALL serve FDEL by resolving the drive to a bound volume, refusing with the read-only-volume code if that volume is shared or owned by a different machine, and otherwise removing the named file if present — succeeding whether or not it existed.

#### Scenario: Delete removes the file
- **WHEN** FDEL names a file present on a volume the machine owns
- **THEN** the file is gone from the volume's directory afterward

#### Scenario: Delete of an absent file still succeeds
- **WHEN** FDEL names a file not present on a volume the machine owns
- **THEN** the response is ok and the volume's directory is unchanged

### Requirement: Write and delete exchanges are logged
Every FWRITE and FDEL SHALL produce one oracle log record carrying machine ID, drive, filename, and result code; FWRITE's record SHALL additionally carry offset, total size, and chunk length.

#### Scenario: A push leaves a write trail
- **WHEN** a machine pushes a file via a sequence of FWRITE requests
- **THEN** the log shows one record per request, with offsets and total sizes that agree across the whole sequence
