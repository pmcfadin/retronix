## Context

Every wire verb since M0 has been a read. HELLO, DIR, and FREAD (ADR-0003,
M1) all follow the same rule — no per-connection state, idempotent by
construction — and the server never writes anything a machine sent it.
`server/volumes.json` carries one volume today, `library`, kind `shared`.
`server/machines/<id>.json` profiles bind drive letters to volume names but
have never had an owned volume to bind. ADR-0002 named the two kinds of
volumes at M0 and left "owned" unimplemented; M3's proposal named the same
gap explicitly as deferred to M4.

Constraints that shape everything below: HELLO's response already carries a
per-binding flags byte with bit0 marking read-only (`server/retronix_server.py`
`handle_hello`, `machine/protocol.inc`'s HELLO OK payload comment) — written
for M0, never yet exercised for a refusal, because nothing writable existed
to distinguish it from. The wire is machine-initiated, one outstanding
request, no server state between requests (ADR-0003) — this constrains
FWRITE and FDEL exactly as it constrained FREAD: every verb must be
idempotent under retry with no memory of what came before. `server/`
capabilities separate CLI-mutated data (foundry's profiles, now the
library's catalog) from what the running server may write itself — the
running server never creates or destroys files a human didn't ask it to,
except the narrow reconciliation write HELLO already performs.

## Goals / Non-Goals

**Goals:**
- Give a machine a place to save its own work: FWRITE and FDEL against a
  volume it owns, idempotent by the same rule as every other verb.
- Make owned-volume exclusivity real: a second machine's conflicting claim
  is refused, honestly, with a code that already exists.
- Make the library a shared volume plus one ordinary file, not a service —
  no catalog wire verb.
- Prove the whole circle end to end, cross-platform, headlessly.

**Non-Goals:**
- The redirector — BDOS-level file I/O interception that would make network
  writes transparent to unmodified CP/M programs (D6; its own milestone,
  ordered right after this one).
- Enforcing BDOS-cleanliness on published software — documented publisher
  responsibility (D4), not tooling.
- Any catalog wire verb, any server-side rendering of the catalog into text
  (ADR-0008).
- A compiled server. Server work stays Python (re-confirmed during
  grilling; a rewrite is a possible post-M5 decision).
- Concurrent writers to one owned volume — ADR-0002's dodge still holds:
  exactly one machine may ever hold a binding to a given owned volume.

## Decisions

### Wire delta: FWRITE (0x04), FDEL (0x05), RRDONLY (0x06)

The next free function codes after FREAD (0x03) are 0x04 and 0x05; the next
free result code after RFNF (0x05) is 0x06.

```
FWRITE	equ	04h
FDEL	equ	05h
RRDONLY	equ	06h		; write/delete refused: volume not owned by the caller
```

**FWRITE request — 20-byte header + up to 512 bytes of chunk data:**

| Bytes | Field |
|---|---|
| 1 | drive index |
| 11 | name, 8+3 space-padded (FREAD's field, verbatim) |
| 4 | offset, little-endian — where this chunk starts |
| 4 | total size, little-endian — the file's final size, resent on every chunk |
| ≤512 | chunk data — the frame's payload length minus 20 gives the count |

FREAD's 18-byte request is offset+length because a read needs to say how
much to fetch; FWRITE's is offset+total-size because a write needs to say
how big the *file* ends up, not how big *this chunk* is — the chunk length
is just "whatever's left in the frame." Total size travels on every chunk,
not only the first, because the server holds no per-connection state
(ADR-0003) and cannot remember "the total this file was declared as" between
requests — each FWRITE is a complete, self-contained instruction: "this file
is N bytes long; here are bytes [offset, offset+len) of it."

**FWRITE OK response — 3 bytes:** `[ROK][written-lo][written-hi]`, the byte
count actually written this chunk (mirrors FREAD's `[ROK][actual-lo][actual-hi]`).
Failure responses are a single result byte: `RUNBND` (drive not bound),
`RBADREQ` (malformed payload), `RRDONLY` (volume not owned by the caller).

**FDEL request — 12 bytes:** drive index (1) + name (11), FREAD's name field
again. **FDEL OK response:** `[ROK]`, whether or not the name existed —
delete-of-absent is success, per ADR-0003's idempotency rule extended the
obvious way. Failure responses: `RUNBND`, `RBADREQ`, `RRDONLY`.

**Idempotency, concretely.** `handle_fwrite` does not ask "have I seen this
file before" — it cannot, statelessly. On every call: open-or-create the
target file, resize it to exactly `total_size` (zero-extend if growing,
truncate if shrinking — this is what "created on first touch, always sized
to total" means: the *first* FWRITE for a name necessarily creates it at
that size, and *every* FWRITE, first or hundredth, re-asserts that size),
then write the chunk bytes at `offset`. Resending an identical chunk is a
no-op difference; resending chunks out of order converges to the same file
because each write only touches its own byte range and every write agrees
on the final size. This is FREAD's statelessness read backwards.

Rejected: a length field instead of total-size (mirrors FREAD's shape more
closely, but then nothing pins the file's final size — a short last chunk
would leave the file exactly as long as the highest offset written so far,
which is wrong for a file whose true length isn't a multiple of the chunk
size and happens to lose its last chunk to a timeout). Rejected: an explicit
`FCLOSE`/finalize verb (reintroduces per-connection state — which chunks
have arrived — that ADR-0003 exists to avoid; also not idempotent, since a
resent close after a genuine close is ambiguous).

### Ownership: a field on the volume, enforced by dropping the binding

`volumes.json` gains an `owner` field on any volume of kind `owned`:

```json
{
  "library": {"path": "volumes/library", "kind": "shared"},
  "home-1001": {"path": "volumes/home-1001", "kind": "owned", "owner": 1001}
}
```

Ownership lives on the volume, not the profile — a profile only ever says
*which letter binds which volume name* (`drive_map`, unchanged shape); it
never asserts ownership itself, because ownership is a property of the
resource, the same way `kind` already is. This is also why no profile schema
change is needed: `drive_map: {"B": "home-1001"}` is exactly today's shape.

`resolve_drive_map` (`server/retronix_server.py`) gains one more thing to
check per binding, right alongside "does this volume name exist at all": if
the volume's kind is `owned` and its `owner` does not match the profile's
`machine_id`, the binding is dropped — logged loudly to stderr exactly like
today's "volume not found in the volumes file" case, silently absent from
the machine's drive map, no different in kind from an operator's typo. This
*is* "refused at HELLO" (D7 scenario 1): the claim never enters the drive
map HELLO answers with, so every subsequent request against that letter —
DIR, FREAD, FWRITE, FDEL — meets `RUNBND`, the code that already exists for
an unbound drive. **No new HELLO-time result code.** The alternative — a
distinct wire code for "HELLO succeeded but refused one of your bindings" —
would either fail the whole HELLO (wrong: the rest of the machine's map is
still good, and ADR-0003 says HELLO is always answerable) or duplicate
`RUNBND`'s exact meaning to the machine (a drive that isn't there). Reusing
it is the honest choice, not a shortcut.

Once a session's `drive_map` is resolved this way, "does this machine own
this drive" is no longer a question `handle_fwrite`/`handle_fdel` need to
ask about *other* machines at all: if the letter resolved to something in
`session.drive_map`, it's either `shared` (read-only, refuse with `RRDONLY`)
or `owned` *by this machine* (an owned volume bound to someone else was
never in the map to begin with). Writing a drive you don't own is impossible
by construction, exactly as D5 states — the check is one `vol.kind ==
"shared"` away from already being correct.

Rejected: an `owned_volumes` list on the profile (redundant with
`drive_map` — a profile binding a letter to an owned volume it doesn't own
is already the misconfiguration to catch; a second list just gives the two
a chance to disagree). Rejected: a runtime claim/release protocol (a machine
"checking out" a volume at HELLO and "releasing" it on disconnect) — this
is exactly the per-connection state ADR-0003 forbids, and static ownership
in `volumes.json` needs none of it: exclusivity is a fact about
configuration, not about who's currently connected.

### Catalog index v1: fixed-stride, versioned, `type`-tolerable

An 8-byte header, then one 68-byte record per published file:

**Header:**

| Bytes | Field |
|---|---|
| 4 | magic, ASCII `RNXL` |
| 1 | format version — `01` |
| 2 | record count, little-endian |
| 1 | reserved, zero |

**Record (68 bytes):**

| Bytes | Field |
|---|---|
| 12 | name — 8.3 with the dot, e.g. `HELLO   .COM`, space-padded, uppercase |
| 4 | size, little-endian, bytes |
| 40 | description, ASCII, space-padded/truncated, one line |
| 4 | source machine id, little-endian |
| 8 | publish date, ASCII `YYYYMMDD` |

Fixed stride, no delimiters: an 8080 walking the file needs only the header's
record count and `8 + 68*i` — the same reason the config block (ADR-0006) and
the DIR/HELLO wire entries are fixed-stride rather than length-prefixed or
delimited. "Tolerable to `type`" is deliberately not "clean under `type`":
the name, description, and date fields render as readable ASCII; the two
binary 4-byte fields between them will show as a handful of control
characters, which is the honest cost of packing a size and a machine id
without inventing a second encoding for them. This mirrors the config
block's own "cheap to read at cold boot over eyeball-friendly" trade
(ADR-0006).

The catalog lives on the library volume as `CATALOG.IDX`. `library.py
publish` reads the whole file, appends or replaces the record for the
published name, and writes it back whole (68 bytes times a few dozen entries
is nothing to rewrite). `lib` FREADs it in 512-byte chunks — the same chunk
size and the same TYPBUF-shaped buffer `type` already uses — and prints
`name  size  description` per record.

Rejected: TLV records (ADR-0006 already rejected this shape for the config
block for the same reason: every field read becomes a walk on an 8080).
Rejected: one line of human text per entry, server-rendered (D2's rejected
alternative — bakes presentation into data; `lib`'s column layout becomes a
server concern instead of a shell concern, and a future second client of the
catalog inherits whatever text format the first one chose).

### `library.py`: a foundry-shaped CLI, minimal metadata

```
python3 server/library.py publish <machine-id> <file> --desc "one line"
python3 server/library.py unpublish <file>
python3 server/library.py list
```

`publish` resolves `<machine-id>`'s owned volume by scanning
`volumes.json` for an entry with `kind: "owned"` and `owner == <machine-id>`
(exactly one is expected for M4's proof; more than one is an error naming
which volumes matched, since the CLI has no way to guess which the operator
meant). It copies `<file>` byte for byte from that volume's directory into
the library volume's directory, computes its size from the copy, and
appends-or-replaces its record in `CATALOG.IDX` with today's date and the
given description. `unpublish` removes the file and its record.
`BDOS-clean` — the published COM behaves under the BDOS console shim
(com-loader's requirement) rather than poking hardware directly — is a
documented expectation on the publisher, not something `publish` checks; the
CLI has no way to run 8080 code to verify it, and inventing one is out of
scope.

All library mutation goes through this CLI, exactly as all profile mutation
goes through `foundry.py`. The running server only reads `volumes.json` and
the files under it; it does not run `library.py` and does not watch for
catalog changes — a fresh publish is visible to a machine as soon as its
next FREAD sees the new bytes, no restart needed, because the server never
cached volume contents to begin with.

### The TPA copy path: `install`, `cp`, `rm`, `lib`

`install <name>` and `cp <src>/<name> <dst>/<name>` share one loop:

1. `DIR` the source drive, find `<name>`, read its size — this is the
   `total_size` FWRITE needs up front; FREAD's own short-read-at-EOF
   behavior only tells you after the fact.
2. Loop from `offset = 0`: `FREAD` the source drive/name at `offset` for 512
   bytes into a fixed 512-byte buffer in the TPA; `FWRITE` the same bytes to
   the destination drive/name at the same `offset`, with `total_size` from
   step 1; advance `offset` by the actual bytes read; stop when a chunk
   reads short (the file's tail) or `offset` reaches `total_size`.
3. Report the outcome honestly: a `RRDONLY` on the first FWRITE call means
   the destination isn't owned by this machine ("refused: destination is
   read-only"); a `RFNF` on the first FREAD means the source name is wrong.

`install` is `cp <library-drive>/<name> <default-owned-drive>/<name>` with
the source pinned to the library and the destination to the machine's own
default owned drive — one code path, exercising the FREAD+FWRITE composition
before real iron does, per D3. `rm <name>` is one `FDEL` against the default
drive (or `rm <drive>/<name>` against a named one); delete-of-absent prints
success, honestly, because the wire already says it succeeded.

`lib` FREADs `CATALOG.IDX` from the library drive in 512-byte chunks,
validates the header (magic, version), and prints one line per record —
name, size, description — reusing the same chunked-FREAD-into-a-fixed-buffer
shape `type` already has.

These four verbs are deliberately **shell built-ins that speak the wire
directly**, not BDOS function-call interceptions — a program that opens a
file with CP/M's own FCB calls still only sees local drives. That gap is
exactly what the redirector (D6, deferred to the milestone right after this
one) closes; M4 proves the wire primitives it will sit on top of.

### Model 4 auto-demo: two more synthetic commands

M3's boot-time auto-demo (`bootdemo`, `machine/bios_m4.asm`) already feeds
fixed command strings — `DIR`, `TYPE ABOUT.TXT`, `RUN HELLO.COM` — through
the same `kwcmp`/`fnparse` path typed input uses, because the Model 4 has no
scriptable console-input channel under a custom ROM (M3's closed Open
Question). The circle scenario (D7 scenario 5) needs the Model 4 to prove it
sees a catalog entry that did not exist when its ROM was minted and runs it
— both inherently dynamic, but the *demo script* itself is static ROM data,
so the fixture it demonstrates is pinned to a known name. `bootdemo` gains
two more synthetic lines after the existing three: `LIB` (prints the
catalog — whatever `library.py publish` has put there by the time this
machine boots, proving the demo reads live server state, not a baked
fixture) and `RUN CIRCLE.COM` (the harness's well-known homebrew fixture
name for this scenario). This is the same trade M3 made for `DEMORUN: db
'RUN HELLO.COM'` — a fixed name in ROM, dynamic content behind it.

## Risks / Trade-offs

- **Two machines' profiles can be edited to name the same owned volume by
  operator mistake, and only the loser learns about it, quietly, in
  stderr.** → This is the intended behavior (an owned-volume claim conflict
  is exactly as loud as a missing-volume typo already is), but `foundry.py
  list`/`show` could be extended to cross-check `drive_map` bindings against
  `volumes.json` ownership and flag the conflict before boot. Out of scope
  for M4 (foundry gets no delta) — noted as a natural M5-or-later
  foundry enhancement, not invented here.
- **FWRITE resizing the file on every call means a chunk delivered very out
  of order (offset near the end, arriving before offset 0) briefly leaves a
  file with garbage (zero) bytes before its real content arrives.** → This
  is fine under the wire's own rules: the machine never reads a file it is
  still writing, and a crashed write leaves an honestly incomplete file
  rather than a corrupted one — no chunk ever overwrites bytes it wasn't
  told to.
  - **`install`/`cp` writing chunks strictly in order (D5) sidesteps this in
    practice**; only a genuinely adversarial or buggy client could produce
    out-of-order chunks, and the harness's oracle log would show it plainly.
- **`library.py publish` racing a machine's own FWRITE to the same owned
  volume** (an operator publishes while the machine is still pushing) **could
  copy a partially-written file.** → Out of scope for M4: the D7 circle
  scenario publishes only after the push completes and the harness confirms
  it via the oracle log, matching the documented publisher workflow (push,
  confirm, then publish). A future library.py could refuse to publish a file
  whose size doesn't match a DIR taken immediately before the copy; not
  built here.
- **The catalog is rewritten whole on every publish/unpublish** — fine at
  homebrew-library scale (dozens of entries), a naive design at scale it
  will likely never reach. Not a risk this milestone needs to mitigate.

## Migration Plan

No existing data changes shape. `volumes.json` gains new owned-volume
entries (harness fixtures and, for the real proof, `home-1001`-style
volumes for the machines D7 exercises); the existing `library` entry is
untouched, just joined by `CATALOG.IDX` inside its directory once the first
publish happens. No profile schema version bump — `drive_map`'s shape is
unchanged. Rollback is deleting the new `owner` fields and the new shell
verbs; nothing here is load-bearing for boot (the invariant that the ROM
alone always reaches a usable prompt is untouched — FWRITE/FDEL/lib/install
all fail honestly with no server, exactly as `dir`/`type`/`run` do today).

## Open Questions

- Exact column layout `lib` prints (spacing, whether size is shown in bytes
  or KB) is not normative — the record content is; same posture M3 took
  for `config`'s display format.
- Whether `install`/`cp` need an explicit overwrite confirmation when the
  destination name already exists. Current design: no — FWRITE at offset 0
  with a new total-size simply resizes and rewrites, silently, matching
  "re-sending any chunk lands identically." If this reads as surprising in
  practice, a confirmation belongs in the shell, not the wire; not decided
  here.
- Whether a machine may hold more than one owned volume simultaneously
  (the design permits it — `resolve_drive_map`'s check is per-binding, not
  per-machine) is unexercised by any D7 scenario and left for whenever a
  real need for it shows up.
