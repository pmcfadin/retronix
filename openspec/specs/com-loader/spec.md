# com-loader Specification

## Purpose
TBD - created by archiving change m1-filesystem. Update Purpose after archive.
## Requirements
### Requirement: Load a COM file into the TPA
The `run` command SHALL fetch the named file from a bound drive via FREAD into memory starting at 0100h, streaming payload chunks directly to their target addresses (not through an intermediate frame buffer), and jump to 0100h only after the entire file is loaded.

#### Scenario: Fixture runs on the real CPU
- **WHEN** the operator runs the library's HELLO.COM at the prompt
- **THEN** the console shows the program's own output, produced by the local CPU executing the fetched bytes

#### Scenario: Missing file fails honestly
- **WHEN** the operator runs a name the volume doesn't hold
- **THEN** the console reports file-not-found and returns to the prompt without jumping anywhere

### Requirement: Minimal BDOS console shim
Address 0005h SHALL dispatch a minimal BDOS subset sufficient for console-only CP/M programs: functions 1 (console in), 2 (console out), 9 (print $-terminated string), 11 (console status), and function 0 (warm boot) returning to the monitor prompt. A RET from the program's entry point SHALL likewise return to the prompt.

#### Scenario: Genuine 1982 calling convention
- **WHEN** a loaded program executes MVI C,9 / LXI D,msg / CALL 0005h
- **THEN** the $-terminated message appears on the console and the program continues

#### Scenario: Unsupported function is honest
- **WHEN** a loaded program requests a BDOS function outside the shim's subset
- **THEN** the shim returns the CP/M convention for "no" (A=0 or 0FFh as appropriate) rather than pretending success, and the monitor survives

### Requirement: type command for text browsing
The `type` command SHALL print a file from a bound drive to the console via FREAD, so the volume is browsable before anything is executed.

#### Scenario: Reading the library's ABOUT.TXT
- **WHEN** the operator types `type about.txt`
- **THEN** the file's text appears on the console and the prompt returns

