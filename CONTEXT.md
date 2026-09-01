# RetroNix

A custom CP/M BIOS plus Unix-flavored shell for real 8080/Z80 hardware,
backed by a serial-connected server that acts as filesystem, software
library, and ROM foundry.

## Language

**Volume**:
A named unit of storage exported by the server. One server can export
several volumes; a machine sees a volume only once it is bound to a drive
letter. Every volume is either **shared** — read-only on the wire, any
machine may bind it, and the only way its contents ever change is a
server-side act (publishing) — or **owned** — read-write over the wire, but
by exactly one machine; the server enforces exclusivity by binding it to no
one else.
_Avoid_: share, remote disk, network filesystem

**Library**:
The one shared volume the server publishes homebrew into: the published COM
files themselves, plus the Catalog that indexes them. Browsed like any other
shared volume — FREAD and `type` work on it before `lib` does anything
smarter with the same bytes.
_Avoid_: repository, archive (both imply version history the library
doesn't keep)

**Catalog**:
The versioned, fixed-stride index file the library volume carries — one
record per published file: name, size, description, source machine, publish
date. Maintained only by the publish step, never by a machine; `lib` FREADs
and parses it the way `type` reads any other file.
_Avoid_: manifest, database (it's one file, parseable by an 8080 without a
query engine)

**Publish / Unpublish**:
The server-side act, through the `library.py` CLI, that promotes a file from
a machine's owned volume into the library and updates the Catalog to match
— or removes one. Never something a machine does; the wire has no verb for
it.
_Avoid_: upload, deploy (both suggest the machine initiates it)

**Push**:
A machine writing a file to a volume it owns, over the wire (FWRITE). The
machine-side half of getting homebrew into the library — Publish is the
server-side half that has to happen afterward.
_Avoid_: upload, save (save undersells that this is a network write with the
same idempotency rules as everything else on the wire)

**Install**:
The machine-side copy of a file from the library into a drive the machine
owns: an FREAD from the library composed with an FWRITE to the owned drive,
through the TPA, chunk by chunk. `cp` is the same code path generalized to
any two drives.
_Avoid_: download (implies a different mechanism than the FREAD it actually
is)

**Boot Ladder**:
The ordered fallback sequence a machine walks at power-on: self-test →
device discovery → config resolution (burned-in → saved → manual) → bind
network drives if configured → prompt. It never dead-ends; every rung lands
somewhere usable. Config is the sole authority for connecting — an
unconfigured machine never probes the wire on its own.
_Avoid_: boot sequence (undersells the fallback guarantee)

**Machine Profile**:
The server-side record of one physical machine: make, model, hardware facts
both declared and observed, machine ID, ROM template, link config, drive map,
owned volumes, and mint state. One file per machine, committed to the repo.
Created before the machine ever boots RetroNix; refined by HELLO report-backs.
_Avoid_: device record, registration

**Machine ID**:
The identity the foundry bakes into minted boot media, assigned at profile
creation from a sequential high-water mark starting at 1001 and never reused,
even after a machine is retired. Presented in every HELLO; the key under which
the server files the profile.
_Avoid_: serial number, hostname

**Probe / Exact**:
The two states a machine profile can be in. A profile is born **probe**: some
hardware facts in it are declared guesses rather than observations. It becomes
**exact** after a boot whose HELLO report-back matches the profile with no
drift. Exact is a claim about agreement between the profile and the machine,
not about how much detail the profile holds.
_Avoid_: draft/final, unverified/verified (they read as "the profile is
wrong", when it is merely unconfirmed)

**HELLO**:
The machine-initiated exchange that opens every booted session: the machine
presents its machine ID, ROM version, and self-test inventory; the server
answers with the profile's current drive map and flags drift for re-mint.
_Avoid_: handshake (undersells the reconciliation), discovery (config
decides; nothing is being discovered)

**Needs-remint**:
The drift flag the server raises at HELLO when what the machine reports — its
hardware inventory, its ROM version, or the contents of its config block —
diverges from the profile. It says the boot media is stale, not that anything
is broken, and it clears only when a fresh mint is stamped from the
reconciled profile.
_Avoid_: dirty, out of sync (both read as a fault; the profile is right and
the ROM is merely older)

**Mint**:
The foundry act of generating boot media — an EPROM image or boot floppy
image — from a machine profile: copy the platform's ROM template, stamp the
config block, write the image out. No assembler runs on this path, so a mint
is byte-deterministic (ADR-0006). The first mint for a probe profile carries
declared facts and expects to be re-minted once observations arrive.
_Avoid_: burn (that's what the human does with the minted image), export

**ROM Template**:
The single canonical ROM image per platform that minting copies — BIOS,
shell, and an unstamped config block, built from source by the ordinary
build. Platform-specific, never machine-specific: nothing in a template names
a machine.
_Avoid_: base image, skeleton, blank ROM (a template is a working ROM)

**Config Block**:
The reserved, fixed-address, versioned region of a ROM template that minting
stamps: magic, block-format version, machine ID, link config, a cached copy of
the drive map, and a checksum. The burned-in tier of ADR-0005 made concrete —
the BIOS reads its identity here rather than from assembly-time constants, and
drift is a byte-for-byte comparison of profile against block.
_Avoid_: header, config area, NVRAM (nothing here is writable by the machine)

**Foundry**:
The subsystem that mints boot media from machine profiles, driven by an
operator CLI. The entry point of provisioning, not a graduation step: machines
are born configured. Profiles are created and edited only through the foundry;
the running server reads them and never writes them.
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
