# RetroNix

A custom CP/M BIOS plus Unix-flavored shell for real 8080/Z80 hardware,
backed by a serial-connected server that acts as filesystem, software
library, and ROM foundry.

## Language

**Volume**:
A named unit of storage exported by the server. One server can export
several volumes; a machine sees a volume only once it is bound to a drive
letter. Every volume is either **shared** (read-only, any machine may bind
it) or **owned** (writable, bound by at most one machine; the server
enforces exclusivity at bind time).
_Avoid_: share, remote disk, network filesystem

**Boot Ladder**:
The ordered fallback sequence a machine walks at power-on: self-test →
device discovery → config resolution (burned-in → saved → manual) → bind
network drives if configured → prompt. It never dead-ends; every rung lands
somewhere usable. Config is the sole authority for connecting — an
unconfigured machine never probes the wire on its own.
_Avoid_: boot sequence (undersells the fallback guarantee)

**Machine Profile**:
The server-side record of one physical machine: make, model, discovered
hardware details, machine ID, drive map, and owned volumes. Created before
the machine ever boots RetroNix; refined by HELLO report-backs.
_Avoid_: device record, registration

**Machine ID**:
The identity the foundry bakes into minted boot media, assigned at profile
creation. Presented in every HELLO; the key under which the server files
the profile.
_Avoid_: serial number, hostname

**HELLO**:
The machine-initiated exchange that opens every booted session: the machine
presents its machine ID, ROM version, and self-test inventory; the server
answers with the profile's current drive map and flags drift for re-mint.
_Avoid_: handshake (undersells the reconciliation), discovery (config
decides; nothing is being discovered)

**Mint**:
The foundry act of generating boot media — an EPROM image or boot floppy
image — from a machine profile, with BIOS, link config, and machine ID
baked in. A first mint for unpredictable hardware is a probe build.
_Avoid_: burn (that's what the human does with the minted image), export

**Foundry**:
The server subsystem that mints boot media from machine profiles. The entry
point of provisioning, not a graduation step: machines are born configured.
_Avoid_: ROM builder, image generator

**Local-Only Mode**:
The fully usable state a machine lands in when no network drive is bound —
no server, dead binds, or no config. Local drives work, `config` is one
command away, and recovering a dead bind takes one command, not a reboot.
_Avoid_: offline mode, degraded mode (it is not degraded; it is a rung)

**Redirector**:
The RetroNix layer in front of BDOS that routes each function call to the
real BDOS (local drive) or the wire (network drive). CP/M and its programs
are unaware of it.
_Avoid_: driver, TSR, NDOS (that's CP/NET's name, not ours)

**Network Drive**:
A CP/M drive letter on the machine that is bound to a server volume instead
of local hardware. There can be several per machine, including A: on a
diskless machine.
_Avoid_: the network drive (singular, as if there is only one)

**Drive Map**:
The per-machine table binding each CP/M drive letter (A:–P:) to either
local hardware or a server volume, optionally with a friendly alias the
shell shows as a top-level directory name. Owned by the machine's config;
resolved by the boot ladder; burned into ROM by the foundry.
_Avoid_: mount table, disk assignment
