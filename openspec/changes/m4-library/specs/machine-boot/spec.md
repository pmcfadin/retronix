## ADDED Requirements

### Requirement: lib command browses the library catalog
The `lib` command SHALL FREAD the library volume's catalog index (`CATALOG.IDX`) in chunks, validate its header (magic and format version), and print one line per record naming the file, its size, and its description. It SHALL be available on both the Altair and Model 4 templates.

#### Scenario: Listing a populated catalog
- **WHEN** the operator types `lib` at the prompt with the library volume bound
- **THEN** the console shows one line per published file, with its name, size, and description

#### Scenario: An unreadable catalog is reported honestly
- **WHEN** `lib` FREADs a catalog file whose header magic or format version does not validate
- **THEN** the console reports the catalog as unreadable rather than printing garbage records

### Requirement: install command copies a library file to an owned drive
`install <name>` SHALL DIR the library drive to find `<name>`'s size, then FREAD it from the library and FWRITE it to the machine's default owned drive in 512-byte chunks at matching offsets, using the DIR'd size as FWRITE's total-size on every chunk. It SHALL be available on both templates.

#### Scenario: Installing a library file
- **WHEN** the operator runs `install hello.com` and the library holds `HELLO.COM`
- **THEN** the file appears on the machine's owned drive with bytes identical to the library's copy

#### Scenario: Installing a name the library doesn't hold
- **WHEN** the operator runs `install` for a name absent from the library
- **THEN** the console reports file-not-found and writes nothing to the owned drive

### Requirement: cp command generalizes install between any two drives
`cp <src-drive>/<name> <dst-drive>/<name>` SHALL use the same FREAD-then-FWRITE chunked copy loop as `install`, between any two drive letters the machine's drive map binds, subject to the destination's write rules.

#### Scenario: Copying between two bound drives
- **WHEN** the operator runs `cp` naming a source drive that holds the file and a destination drive the machine owns
- **THEN** the destination gains a copy identical to the source, and the source is unchanged

#### Scenario: Copying to a drive the machine does not own
- **WHEN** the operator runs `cp` naming a destination drive bound to a shared or otherwise unowned volume
- **THEN** the console reports the read-only refusal honestly and no partial file is left claiming success

### Requirement: rm command deletes a file on an owned drive
`rm <name>` (optionally `rm <drive>/<name>`) SHALL issue FDEL against the named drive and report the result. Deleting a name that does not exist SHALL be reported as success, matching the wire's idempotent delete.

#### Scenario: Deleting an existing file
- **WHEN** the operator runs `rm` naming a file present on an owned drive
- **THEN** the file is absent from a subsequent `dir` of that drive and the console reports success

#### Scenario: Deleting an absent file is not an error
- **WHEN** the operator runs `rm` naming a file not present on the drive
- **THEN** the console reports success, matching the wire's delete-of-absent rule

#### Scenario: rm against a shared volume is refused
- **WHEN** the operator runs `rm` naming a file on a shared or unowned volume
- **THEN** the console reports the read-only refusal honestly and the file is untouched

### Requirement: The Model 4's boot-time auto-demo exercises the library
The Model 4 template's boot-time auto-demo — synthetic `dir`, `type`, and `run` commands fed through the shell's normal command path, unprompted, after banner and HELLO, established because the platform has no scriptable console-input channel — SHALL be extended with two further synthetic commands: `lib`, printing the library's current catalog, and `run` of a fixed, known published-fixture name. Both SHALL execute against live server state at boot time, not a value baked into the ROM at mint time, so a file published after this image was minted still appears in the printed catalog and still runs.

#### Scenario: The demo reads live catalog state
- **WHEN** the Model 4 boots after a file has been published to the library under the demo's fixed fixture name
- **THEN** the boot-time console shows that file's catalog entry, followed by its own console output, over the printer tap, with no typed input

#### Scenario: An unpublished fixture is reported honestly
- **WHEN** the Model 4 boots before the demo's fixed fixture name has ever been published
- **THEN** the catalog listing omits it and the subsequent `run` reports file-not-found rather than hanging or crashing
