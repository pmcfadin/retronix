## MODIFIED Requirements

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

## ADDED Requirements

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
The prompt SHALL accept a `config` command on every rung of the Boot Ladder — linked or in Local-Only Mode — and it SHALL NOT require the wire, so an unreachable server can never make config unreachable. It SHALL display the burned-in machine ID, the ROM version, the burned-in link config (the wire port and framing the image was minted with), the current link state, and the full retained Drive Map with each binding's volume name and bind state.

In this ROM version `config` SHALL be read-only: it SHALL alter neither link config nor Drive Map, and SHALL state plainly that the Drive Map is server-authoritative — changed on the server and reconciled at HELLO (ADR-0005) — rather than offering an edit that does nothing.

#### Scenario: Config while linked
- **WHEN** the operator types `config` after a successful HELLO
- **THEN** the console shows the machine ID, ROM version, link config, a link state of up, and every retained binding with its volume name

#### Scenario: Config in local-only mode
- **WHEN** the operator types `config` after booting with no server
- **THEN** the console still shows machine ID, ROM version, and link config, reports the link state as local-only, and completes without touching the wire

#### Scenario: No pretend editing
- **WHEN** `config` is run in either link state
- **THEN** no machine state changes, no wire request is sent, and the display says where the Drive Map is actually owned

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
