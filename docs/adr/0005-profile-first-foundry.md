# Profile-first foundry: machines are born configured, then reconciled at HELLO

Provisioning starts on the server, not the machine. Creating a machine
profile (make, model, hardware details) assigns a machine ID and lets the
foundry mint boot media — EPROM image or boot floppy image, per profile —
with the BIOS, link config, and ID baked in. For hardware the catalog can't
fully predict (S-100 card mixes), the first mint is a probe build; the
boot-time report-back refines the profile and the next mint is exact. This
inverts the PRD's original flow (manual bring-up → capture → burn), which
survives only as the automated refine loop.

Every boot begins with a HELLO: the machine presents its ID, ROM version,
and self-test inventory; the server diffs against the profile and
reconciles config in three tiers — session config in RAM is updated
silently every boot, a local disk cache is refreshed when it exists, and
the burned ROM is never pretended to change: drift flags the profile for
re-mint.

Over-the-wire updating covers **config only** in v1. CP/NOS-style network
boot of system software (shell, redirector) was deferred, with one hard
invariant either way: the ROM alone must boot to a usable local-only prompt
forever — the wire may offer upgrades but is never load-bearing for boot.
