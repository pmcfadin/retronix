## ADDED Requirements

### Requirement: The catalog is a versioned, fixed-stride index file
The library volume SHALL carry a catalog index file, `CATALOG.IDX`, with an 8-byte header (magic, format version, record count, reserved) followed by one fixed-stride record per published file (8.3 name, size, one-line description, source machine ID, publish date). Records MUST be at a fixed byte offset from the header — `header_size + record_size * index` — so the file is walkable without parsing delimiters, and MUST be plain enough that a `type`-style raw dump of the file is legible for its ASCII fields even though its binary fields are not.

#### Scenario: An empty library has a valid, empty catalog
- **WHEN** no file has ever been published
- **THEN** `CATALOG.IDX` exists with a valid header and a record count of zero

#### Scenario: Records are fixed-stride
- **WHEN** the catalog holds more than one record
- **THEN** every record occupies exactly the same number of bytes, at an offset computable from its index alone

### Requirement: Publishing is a server-side promotion, never a machine act
`library.py publish <machine-id> <file> --desc <text>` SHALL copy `<file>` byte-for-byte from the machine's owned volume into the library volume and append or replace its record in the catalog with the file's size, the given description, the source machine ID, and today's date. `unpublish <file>` SHALL remove the file from the library volume and its catalog record. Neither operation SHALL be reachable over the wire; both are CLI-only.

#### Scenario: Publishing a pushed file
- **WHEN** the operator runs `publish` naming a machine ID and a file present on that machine's owned volume
- **THEN** the file appears in the library volume's directory and a matching record appears in the catalog

#### Scenario: Unpublishing removes both the file and its record
- **WHEN** the operator runs `unpublish` naming a file present in the library
- **THEN** the file is gone from the library volume's directory and its catalog record is gone

#### Scenario: Publish resolves the machine's owned volume automatically
- **WHEN** the operator runs `publish` naming a machine ID with exactly one owned volume
- **THEN** the CLI locates that volume from the machine's ID without the operator naming it explicitly

### Requirement: The running server never mutates the library
All catalog and library-volume mutation SHALL go through `library.py`. The running server SHALL only read the library volume and its catalog, in service of DIR and FREAD requests, exactly as it reads any other shared volume.

#### Scenario: A fresh publish is visible without a server restart
- **WHEN** `library.py publish` runs while the server is already serving requests
- **THEN** the next FREAD or DIR against the library volume reflects the change, with no server restart

### Requirement: The library CLI surfaces the catalog to the operator
`library.py list` SHALL print every catalog entry — name, size, description, source machine, and publish date — so an operator can inspect the library without booting a machine.

#### Scenario: Listing a populated library
- **WHEN** the operator runs `library.py list` against a library with published entries
- **THEN** every entry is printed with its name, size, description, source machine, and publish date

### Requirement: An agent skill teaches the push-publish-install loop
The repository SHALL carry an agent skill at `.claude/skills/library/SKILL.md` describing the loop end to end: a machine pushes a file to its own owned volume, an operator publishes it with `library.py`, and any machine installs it from the catalog. It SHALL name the CLI verbs and state that the running server never mutates the library.

#### Scenario: The loop is documented as a loop
- **WHEN** an agent reads the skill
- **THEN** it can carry out push → publish → install without reading `library.py`'s source
