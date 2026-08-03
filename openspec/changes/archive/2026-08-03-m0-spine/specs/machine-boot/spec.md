# machine-boot

Machine-side bring-up for M0 on SIMH AltairZ80: BIOS + minimal monitor. No redirector, no shell, no local disk — just the spine (PRD §10). The never-dead-end pillar applies from the first boot.

## ADDED Requirements

### Requirement: Banner on boot
The BIOS SHALL print a RetroNix banner (name and ROM version) on the console as its first visible act after power-on.

#### Scenario: Cold boot shows the banner
- **WHEN** the machine image is booted in SIMH AltairZ80
- **THEN** the console shows the RetroNix banner including a ROM version string

### Requirement: Serial link initialized from burned link config
The BIOS SHALL initialize the serial port using link config baked into the boot image at build (mint) time. The machine ID SHALL likewise be baked in, not entered at runtime.

#### Scenario: Link comes up without operator input
- **WHEN** the machine boots with a server listening on the configured serial channel
- **THEN** the link is usable for HELLO with no operator interaction

### Requirement: Self-test inventory
Boot SHALL collect a device inventory (at minimum: CPU type detected, RAM size, serial port status) before attempting HELLO, and the inventory SHALL be included in the HELLO payload.

#### Scenario: Inventory reaches the server
- **WHEN** the machine completes HELLO
- **THEN** the server's log shows the machine's inventory fields populated

### Requirement: HELLO at boot, local-only on failure
A configured machine SHALL send HELLO during boot. If HELLO fails (timeout after bounded retries, or an error response), the machine SHALL still land at a usable prompt in local-only mode — never a dead end, no reboot required to retry.

#### Scenario: Successful HELLO binds the drive map
- **WHEN** HELLO succeeds
- **THEN** the prompt is reachable and the drive map from the response is in effect

#### Scenario: Server down at boot
- **WHEN** the machine boots with no server on the wire
- **THEN** the machine reaches the prompt in local-only mode after retries are exhausted

### Requirement: Minimal prompt with dir
The monitor SHALL present a prompt accepting at minimum a `dir` command, which issues the wire DIR verb for a bound drive and prints the returned entries.

#### Scenario: dir round trip
- **WHEN** the operator types `dir` at the prompt after a successful HELLO
- **THEN** the console prints the file listing of the bound volume as returned by the server
