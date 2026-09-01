# machine-boot Specification

## Purpose
TBD - created by archiving change m0-spine. Update Purpose after archive.
## Requirements
### Requirement: Banner on boot
The BIOS SHALL print a RetroNix banner (name and ROM version) on the console as its first visible act after power-on.

#### Scenario: Cold boot shows the banner
- **WHEN** the machine image is booted in SIMH AltairZ80
- **THEN** the console shows the RetroNix banner including a ROM version string

### Requirement: Serial link initialized from burned link config
The BIOS SHALL initialize the serial port using link config carried in the config block the foundry stamped into the image at mint time. The machine ID SHALL likewise come from that block, not from an assembly-time constant and not entered at runtime. Changing either is a re-mint, never a runtime edit.

#### Scenario: Link comes up without operator input
- **WHEN** the machine boots with a server listening on the configured serial channel
- **THEN** the link is usable for HELLO with no operator interaction

#### Scenario: Two mints of one template dial differently
- **WHEN** two images minted from the same template with different link configs are booted
- **THEN** each initializes the serial port from its own block, with no rebuild of the template between them

### Requirement: Self-test inventory
Boot SHALL collect a device inventory (at minimum: CPU type detected, RAM size, serial port status) before attempting HELLO, and the inventory SHALL be included in the HELLO payload.

#### Scenario: Inventory reaches the server
- **WHEN** the machine completes HELLO
- **THEN** the server's log shows the machine's inventory fields populated

### Requirement: HELLO at boot, local-only on failure
A configured machine SHALL send HELLO during boot. If HELLO fails (timeout after bounded retries, or an error response), the machine SHALL still land at a usable prompt in local-only mode — never a dead end, no reboot required to retry.

On success the machine SHALL retain the **complete** Drive Map the response carries — for every binding: the drive letter, the kind, the flags, and the volume name — up to the sixteen CP/M drive letters, not merely the first binding. Volume names longer than the retained maximum SHALL be stored and displayed truncated rather than overrunning the table. The first bound network drive remains the default drive that `dir`, `type`, and `run` address; the rest are retained so `ls /dev` and `config` can report the truth about the machine's bindings.

#### Scenario: Successful HELLO binds the drive map
- **WHEN** HELLO succeeds
- **THEN** the prompt is reachable and the drive map from the response is in effect

#### Scenario: Server down at boot
- **WHEN** the machine boots with no server on the wire
- **THEN** the machine reaches the prompt in local-only mode after retries are exhausted

#### Scenario: Every binding is retained, not just the first
- **WHEN** HELLO succeeds against a profile whose drive map binds more than one drive letter
- **THEN** the machine holds every returned binding with its drive letter and volume name, and reports all of them when asked

#### Scenario: Default drive is unchanged by the wider map
- **WHEN** the operator types `dir` after a multi-binding HELLO
- **THEN** the listing is of the first bound drive, exactly as before this change

#### Scenario: An empty map is still a live link
- **WHEN** HELLO succeeds but the response binds no drive letters
- **THEN** the machine is linked, reports zero network bindings, and does not claim local-only mode

### Requirement: Minimal prompt with dir
The monitor SHALL present a prompt accepting at minimum a `dir` command, which issues the wire DIR verb for a bound drive and prints the returned entries.

#### Scenario: dir round trip
- **WHEN** the operator types `dir` at the prompt after a successful HELLO
- **THEN** the console prints the file listing of the bound volume as returned by the server

### Requirement: ls /dev lists devices and bind states
`/dev` is synthetic and read-only (ADR-0004): it is generated from what the self-test found and from the retained Drive Map, and it is never a place files can be written or created. `ls /dev` SHALL touch neither the wire nor any disk, and SHALL print:

- one line per device the boot self-test inventoried — at minimum CPU type, RAM size, the console port, and the wire port with whether the link is currently up; and
- one line per CP/M drive letter the machine knows about, carrying its bind state: the bound volume name for a live network binding, an explicit dead marker for a letter the retained map binds while the link is down, and an explicit unbound marker for a letter with no binding.

`ls` with a path other than `/dev` SHALL say plainly that this ROM version lists only `/dev`, rather than silently listing something else.

#### Scenario: Inventory after a successful HELLO
- **WHEN** the operator types `ls /dev` at the prompt with the link up
- **THEN** the console shows the self-test devices, the wire reported as up, and each bound drive letter with its volume name

#### Scenario: Local-only mode is visible in /dev
- **WHEN** the operator types `ls /dev` after booting with no server
- **THEN** the console shows the self-test devices with the wire reported down and no drive letter claiming a live volume, and no wire traffic is attempted

#### Scenario: A dead binding is named, not hidden
- **WHEN** the link drops after a successful HELLO and the operator types `ls /dev`
- **THEN** the drive letters the retained map binds are listed with their volume names and marked dead, distinguishably from letters that were never bound

#### Scenario: ls outside /dev is honest
- **WHEN** the operator types `ls` with any path other than `/dev`
- **THEN** the console reports that only `/dev` is listable in this ROM version and the prompt returns

### Requirement: config is reachable from every rung of the ladder
The prompt SHALL accept a `config` command on every rung of the Boot Ladder — linked or in Local-Only Mode — and it SHALL NOT require the wire, so an unreachable server can never make config unreachable. It SHALL display the machine ID, the ROM version, the link config (the wire port and framing the image was minted with), the current link state, and the full retained Drive Map with each binding's volume name and bind state.

`config` SHALL additionally report the config block itself: whether it validated, its block-format version, and the values the foundry stamped — so the operator can compare a machine against its profile without disassembling the image, and so the server's drift flag can be checked against what the machine actually holds.

In this ROM version `config` SHALL be read-only: it SHALL alter neither link config, Drive Map, nor config block, and SHALL state plainly that the Drive Map is server-authoritative — changed on the server and reconciled at HELLO (ADR-0005) — and that the block is changed only by re-minting (ADR-0006), rather than offering an edit that does nothing.

#### Scenario: Config while linked
- **WHEN** the operator types `config` after a successful HELLO
- **THEN** the console shows the machine ID, ROM version, link config, a link state of up, and every retained binding with its volume name

#### Scenario: Config in local-only mode
- **WHEN** the operator types `config` after booting with no server
- **THEN** the console still shows machine ID, ROM version, and link config, reports the link state as local-only, and completes without touching the wire

#### Scenario: No pretend editing
- **WHEN** `config` is run in either link state
- **THEN** no machine state changes, no wire request is sent, and the display says where the Drive Map and the config block are actually owned

#### Scenario: The stamped block is visible
- **WHEN** the operator types `config` on a machine booted from a mint
- **THEN** the console reports the block as valid, names its format version, and shows the machine ID and link config it stamped

### Requirement: bind recovers a dead link in one command
The prompt SHALL accept a `bind` command that re-runs the ladder's HELLO rung on demand. It SHALL first drain the wire of any bytes left over from a dropped link, then re-issue HELLO with the same burned-in machine ID and ROM version and the inventory collected at boot, using bounded retries as at boot.

On success the machine SHALL replace the retained Drive Map with the response's map, leave the machine linked, and make the wire commands (`dir`, `type`, `run`) work exactly as they do after a successful boot HELLO. On failure it SHALL report the reason honestly — no response after retries, or the server's error code such as unknown-machine — and leave the machine in Local-Only Mode. In neither case SHALL the machine reboot, re-run the self-test, reprint the banner, or lose the prompt.

#### Scenario: One command, not a reboot
- **WHEN** the machine is in local-only mode, the server becomes reachable, and the operator types `bind`
- **THEN** HELLO succeeds, the console reports the newly bound drives, and `dir` lists the bound volume — with no reboot and no second banner

#### Scenario: Bind with still no server
- **WHEN** the operator types `bind` while nothing is listening on the wire
- **THEN** the console reports that there was no response, the machine stays in local-only mode, and the prompt returns usable

#### Scenario: Bind refused by the server
- **WHEN** `bind` reaches a server that has no profile for this machine ID
- **THEN** the console reports the server's refusal rather than a timeout, and the machine stays in local-only mode

#### Scenario: Bind while already linked refreshes the map
- **WHEN** the operator types `bind` with the link already up
- **THEN** the machine re-runs HELLO and adopts the drive map from the new response, replacing the previously retained one

### Requirement: The config block is read and validated at cold boot
The ROM template SHALL reserve a fixed-address, versioned config block that the foundry stamps (ADR-0006), and the BIOS SHALL read it as its first act after the stack is set, before the wire is touched. Validation SHALL check the magic, the block-format version, and the checksum under the same rule a wire frame uses.

On a valid block the BIOS SHALL take its machine ID and its link config from the block — neither SHALL be an assembly-time constant any longer — and SHALL send the block's machine ID in HELLO.

On an invalid, unstamped, or unrecognised-version block the BIOS SHALL say plainly on the console that the config block is unreadable, SHALL NOT dial the wire with an unknown identity, and SHALL go directly to Local-Only Mode at a usable prompt. An unminted template hits exactly this path, which is the correct behavior for a ROM nobody has provisioned.

#### Scenario: A stamped block supplies the identity
- **WHEN** a machine boots from an image minted for machine 1002
- **THEN** the HELLO it sends carries machine ID 1002, taken from the block rather than from the assembled code

#### Scenario: Link config comes from the block
- **WHEN** a machine boots from a mint whose block carries the link config
- **THEN** the serial port is initialized from those values and HELLO succeeds with no operator interaction

#### Scenario: An unstamped template boots honestly
- **WHEN** the ROM template is booted before any mint has stamped it
- **THEN** the console reports that the config block is unreadable, no HELLO is attempted, and the prompt is reachable in Local-Only Mode

#### Scenario: A corrupt block is not trusted
- **WHEN** a single byte inside the config block is altered after minting and the image is booted
- **THEN** the checksum fails, the machine reports the block as unreadable, and it does not dial with the block's contents

### Requirement: The baked drive map pre-populates the retained map
On a valid config block the BIOS SHALL copy the block's cached drive map into the retained Drive Map, with the entry count the block carries, **before** any wire traffic is attempted. A successful HELLO SHALL then replace the retained map wholesale with the response's map: the session tier beats the burned tier (ADR-0005), and the machine never merges the two.

In Local-Only Mode the preloaded bindings SHALL be reported as dead — the volume name the ROM was minted with, marked dead because the link is down — rather than as unbound. The machine SHALL NOT present a baked binding as live.

#### Scenario: Local-only mode shows intended bindings as dead
- **WHEN** a machine minted with drive A bound to `library` boots with no server and the operator types `ls /dev`
- **THEN** drive A is listed with the volume name `library` and marked dead, and no drive claims a live volume

#### Scenario: HELLO replaces the baked map
- **WHEN** a machine whose block caches one drive map completes a HELLO whose response carries a different map
- **THEN** the retained map is the response's map alone, with no binding left over from the block

#### Scenario: No wire traffic before the preload
- **WHEN** a machine boots
- **THEN** the retained map is populated from the block before the first byte is written to the wire

### Requirement: A TRS-80 Model 4 ROM template
The project SHALL carry a second ROM template targeting the TRS-80 Model 4, minted by the same foundry from the same kind of config block as the Altair template. Because the Model 4's system ROM and page-zero RAM are mutually exclusive, the template SHALL copy itself into RAM and switch the port-84h memory map before establishing the CP/M page-zero vectors, and SHALL do so before anything that depends on page zero runs.

The template SHALL bring up the TR1865 serial port as its wire and SHALL mirror every console character to the printer port, so a byte channel the ROM owns carries the console rather than the emulator's stock-ROM scripting layer (ADR-0007). Its HELLO SHALL use the bounded retry loop, because the first byte written to this platform's link is lost to a connect race.

#### Scenario: The machine survives the map switch
- **WHEN** the Model 4 template boots from reset
- **THEN** it relocates into RAM, switches the memory map, and prints its banner on the console channel from the relocated copy

#### Scenario: Page zero exists before it is used
- **WHEN** the Model 4 template has completed its map switch
- **THEN** RAM is readable and writable at page zero and the CP/M restart and BDOS-entry vectors are in place

#### Scenario: The Model 4 reaches the prompt with no server
- **WHEN** the Model 4 image boots with nothing listening on the wire
- **THEN** it lands at a usable prompt in Local-Only Mode, exactly as the Altair image does

#### Scenario: HELLO survives the dropped first byte
- **WHEN** the Model 4 image boots against a listening server
- **THEN** HELLO succeeds despite the first byte of the stream being dropped, because the request is retried rather than sent once

