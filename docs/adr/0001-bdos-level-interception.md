# Intercept at the BDOS level, not the BIOS level

The redirector hooks CP/M's BDOS function-call layer, deciding per call
whether a device is local or remote — not the ~17 BIOS entry points. Three
of the five pillars (software library, ROM foundry, server-as-test-oracle)
need file-level semantics: under sector-level BIOS interception the server
would see sector numbers and have to reverse-engineer CP/M's directory
structure to know a file was even opened. CP/NET validated this exact layer
across heterogeneous hardware; we inherit its NDOS/SNIOS-style factoring.

## Considered Options

BIOS-level (sector-based) interception was rejected: maximum transparency
and "free" program loading, but it starves the server of file semantics and
multiplies round trips over serial.

## Consequences

- The wire protocol speaks files and operations (open/read/dir), not sectors.
- Programs that bypass BDOS and hit the BIOS directly (copy-protected
  commercial software, low-level disk utilities) will not see network drives.
  Software distributed through the RetroNix library must be BDOS-clean.
- Program loading from the network drive works via the CCP's normal
  BDOS-sequential-read load path — cheap, though not the "free" path §8 of
  the PRD describes for the BIOS model.
