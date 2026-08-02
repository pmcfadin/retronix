# Volumes are shared-read-only or owned-writable, enforced by the server

Every server volume is exactly one of two kinds: **shared** (any machine may
bind it, all access read-only over the wire) or **owned** (writable, bound by
at most one machine at a time). The server enforces exclusivity — a second
machine binding an owned volume gets a clean refusal at bind time.

This dodges the multi-writer problem instead of solving it: CP/M's BDOS
assumes it owns the disk, so two machines writing one volume would corrupt
directory state no matter how the server serializes wire requests. A locking
protocol on the wire was rejected for v1 — nothing for the 8-bit side to
implement, nothing to get wrong. Publishing into the shared library volume
happens server-side, never through a CP/M drive.
