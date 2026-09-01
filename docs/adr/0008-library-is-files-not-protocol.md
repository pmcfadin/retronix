# The library is files, not protocol: push to owned volumes, publish is a server-side promotion

The wire gets exactly two new verbs in M4 — FWRITE and FDEL — and both apply
only to volumes a machine owns (ADR-0002). A machine can write its own
volume; it can never write the shared library volume, on the wire, under any
circumstance. Getting a file *into* the library is therefore always two acts,
never one: **push** — the machine FWRITEs a file to its own owned volume —
and **publish** — an operator, through `server/library.py`, copies that file
from the owned volume into the library volume and updates the catalog. PRD
§101's "publishing happens server-side, never through a CP/M drive" holds
verbatim; M4 is where the owned-volume write path it always depended on
finally exists, and with it the exclusivity proof ADR-0002 deferred: a second
machine whose profile claims an already-owned volume has that binding
dropped at HELLO, the same honest `unbound-drive` code an operator's typo in
`volumes.json` already produces today.

The library itself is not a service the machine queries — it is a shared
volume like any other, carrying the published COM files plus one more file: a
versioned, fixed-stride catalog index that the publish step maintains.
Browsing it is FREAD, the same verb that already reads every other file on a
shared volume; the shell's `lib` gains no wire privilege `type` doesn't
already have — it FREADs `CATALOG.IDX` and parses fixed offsets instead of
printing raw bytes. No catalog wire verb exists, and none is needed: the
catalog is data, not protocol, in exactly the sense ADR-0006 made
provisioning a data problem instead of a build step.

Rejected: first-class catalog verbs (`CATLIST`, `CATSEARCH`, ...) that would
let the machine query the library server-side. This is speculative
generality at 8-bit scale — a whole request/response shape and a server-side
query engine to save one FREAD-and-parse the shell already knows how to do,
and it puts presentation logic on the wire that belongs in the shell.
Rejected also: machine-writable shared volumes, i.e., skipping the publish
step and letting a machine FWRITE straight into the library. That reopens
the multi-writer problem ADR-0002 dodged by construction — the exclusivity
guarantee holds only because "owned" and "shared" are disjoint categories
with different wire privileges, and a write-through-to-shared path erases
that line to save one CLI command.

Consequences: FWRITE and FDEL are idempotent by the same rule every verb
since ADR-0003 has followed — chunked writes carry an explicit offset and a
total size applied on every chunk, and deleting an absent file is not an
error. Writes and deletes against a volume the requesting machine does not
own answer with one new, honestly distinct result code rather than reusing
`unbound-drive` or silently no-opping. And because ownership is now something
the wire can be asked to enforce, the owned-volume exclusivity proof that M3
left for "the write path" has a write path to prove it against.
