# Minting stamps a config block into a per-platform ROM template

There is one canonical ROM image per platform — the ROM template — built from
source by the ordinary build, and every machine's boot media is a copy of it
with one reserved region rewritten. That region, the config block, sits at a
fixed address the BIOS knows and carries a magic, a block-format version, the
machine ID, the link config, a cached copy of the drive map, and a checksum.
Minting is copy-then-stamp: no assembler on the mint path, no per-machine
build. Two mints of the same profile are byte-identical, so a mint can be
diffed, checksummed, and reasoned about without re-running a toolchain.

The BIOS reads its identity out of the block rather than out of assembly-time
equates. That is what makes drift mechanical: the profile and the block are
the same fields in the same order, so "this machine needs a re-mint" is a
byte-for-byte comparison rather than a judgement call, and `config` on the
machine prints exactly what the foundry stamped.

Because the block carries the drive map, the BIOS pre-populates its retained
map from the block at cold boot, before the wire is touched. A successful
HELLO overwrites it — the session tier still beats the burned tier of
ADR-0005 — but a machine that never reaches a server now shows its intended
bindings marked dead instead of an empty map. Local-Only Mode gets more
honest, not less: the machine can say what it was configured for and that it
cannot reach it.

Rejected: having the foundry run zmac per machine. That puts a toolchain on
the provisioning path, makes mint output depend on the assembler's version,
and blurs the line ADR-0005 draws between burned-in config and code — if
every mint is a fresh assembly, there is nothing to point at and call "the
configuration", and the promise that the ROM is never pretended to change
loses its teeth.
