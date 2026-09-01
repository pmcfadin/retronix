## ADDED Requirements

### Requirement: Owned-volume exclusivity scenario
The harness SHALL include a scenario that mints two machines with profiles whose drive maps both bind the same owned volume, boots the machine that is not the volume's owner, and asserts that its drive map has no binding for that letter and that a subsequent request against the letter answers unbound-drive — proving the deferred ADR-0002 exclusivity claim end to end.

#### Scenario: The exclusivity run
- **WHEN** the exclusivity scenario executes
- **THEN** it exits 0, with the non-owner's HELLO succeeding minus the conflicting binding, and the oracle log showing unbound-drive for any request against that letter

### Requirement: install scenario
The harness SHALL include a scenario in which the Altair machine installs a COM file from the library to its own owned volume via the `install` command, asserted both on the console (the program's own output after a subsequent `run`) and against the oracle log (the FREAD sequence from the library and the FWRITE sequence to the owned volume, with server-side bytes compared equal to the library's copy).

#### Scenario: The install run
- **WHEN** the install scenario executes
- **THEN** it exits 0, the installed file's bytes on the server match the library's copy exactly, and the oracle log shows the FREAD and FWRITE sequences that produced it

### Requirement: rm scenario
The harness SHALL include a scenario that deletes a file from an owned volume with `rm`, confirms it is gone from a subsequent DIR, then runs `rm` again against the same now-absent name and confirms success both times — both outcomes asserted against the oracle log.

#### Scenario: The rm run
- **WHEN** the rm scenario executes
- **THEN** it exits 0, the first delete removes the file, the second delete (of the absent name) still succeeds, and both FDEL records in the oracle log carry an ok result

### Requirement: Read-only refusal scenario
The harness SHALL include a scenario that attempts a write and a delete against the shared library volume and asserts both are refused with the read-only-volume code, reported honestly on the console, with the library volume's contents unchanged.

#### Scenario: The refusal run
- **WHEN** the read-only refusal scenario executes
- **THEN** it exits 0, both the write and the delete attempts report the read-only refusal on the console, and the library volume's directory is byte-for-byte unchanged afterward

### Requirement: The homebrew circle scenario, cross-platform
The harness SHALL include a scenario proving the full circle with no manual editing: the Altair machine pushes a file to its own owned volume via `install`-style FWRITE chunks (or an equivalent push fixture), `library.py publish` promotes it into the library and the catalog, and the Model 4 machine boots and — through its boot-time auto-demo — shows the new catalog entry and runs the freshly published COM. It SHALL pass only when the Model 4's console shows both the catalog entry and the program's own output, and the oracle log shows the Altair's push and the Model 4's later FREAD of the same bytes. One emulator process at a time.

#### Scenario: The circle run
- **WHEN** the circle scenario executes
- **THEN** it exits 0, the Model 4's boot console shows the published file's catalog entry and its own program output, and the oracle log shows the Altair's FWRITE sequence followed later by the Model 4's FREAD of the identical bytes

#### Scenario: Earlier milestones keep passing
- **WHEN** the full harness runs after M4 lands
- **THEN** the spine, run-COM, boot-ladder, link-recovery, two-machines, probe-loop, drift, and block-integrity scenarios still pass unchanged
