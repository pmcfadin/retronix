## Context

M1 left the machine with a wire client, a COM loader, and a three-verb
prompt (`dir`, `type`, `run`). Its HELLO handler reads the response's
binding count into `MAPCNT`, copies the first binding's drive index into
`DEFDRV`, and discards the rest — including every volume name. The bytes
are actually present: `rcvfrm` routes payload bytes 0–2 into `RBUF` and
bytes 3.. to `[RDST]`, and HELLO sets `RDST` to `RBUF+3`, so the whole
response already lands contiguously in `RBUF`. Nothing parses past the
first entry.

Constraints that shape everything below: strict 8080 subset (the harness
runs `set cpu 8080`); the monitor lives at E000 with the stack at FE00;
the wire is machine-initiated with no unprompted server frames (ADR-0003),
so the machine cannot be *told* the link died; the Drive Map is
server-authoritative and reconciled at HELLO (ADR-0005); the namespace is
two levels deep with a synthetic read-only `/dev` (ADR-0004).

## Goals / Non-Goals

**Goals:**
- Make the Boot Ladder inspectable from the prompt: what the self-test
  found, and what each drive letter is actually bound to.
- Make Local-Only Mode leavable in one command.
- Store the whole Drive Map machine-side so the above can be honest.
- Prove the recovery flow in the harness, inside a single boot.

**Non-Goals:**
- Editing the Drive Map or link config from the machine (M3, foundry).
- Persisting config to local disk — tier 2 of PRD §6.3 needs a local disk
  the emulator target does not have yet.
- Addressing commands at a non-default drive (`dir /b`). The protocol
  supports it; the shell's parser does not, and widening it is not what
  this milestone is about.
- Any change to server handlers, volumes, or the oracle log format.

## Decisions

**The command is `bind`.** CONTEXT.md already speaks of bindings, bind
time, and "recovering a dead bind takes one command"; `bind` is that
command spelled the way the glossary spells the concept. Rejected:
`reconnect` and `link` (describe the wire, not the outcome — the wire may
have been fine all along and the server merely restarted), and `hello`
(names the wire verb, which is an implementation detail the operator
should not have to know). Taking no argument now leaves `bind <drive>
<volume>` free as the natural M3 extension.

**Retained map is a fixed-stride table, parsed from `RBUF`.** Sixteen
entries of {drive index, kind, flags, name length, 16 name bytes}. Fixed
stride means index arithmetic instead of a linked walk, which is what the
8080 is good at. Volume names longer than 16 characters are truncated at
parse and shown truncated — the alternative (variable-length storage) buys
nothing for a display-only table. `RBUF` grows from 256 to 512 bytes so a
sixteen-binding response cannot overrun it; the receiver itself stays
untouched, which keeps M1's FREAD streaming path exactly as proven.

**Link state stays a single flag, cleared on wire failure.** `LINKUP`
already exists. Because nothing on the wire announces a dead server, the
machine learns the link is gone only when a request times out — so
`dir`/`type`/`run` clear `LINKUP` when `rpc` exhausts its retries. That is
what makes the "dead" state in `/dev` truthful rather than stale: a
binding is *dead* when the retained map holds it and `LINKUP` is clear,
*unbound* when no entry holds the letter at all.

**`config` is read-only in M2, and says so.** The Drive Map is owned by the
server profile; the v0 error table and verb set have no config-write verb,
and inventing one before the foundry exists would be building the wrong
half first. An edit screen that changed only RAM would be exactly the kind
of pretend the project refuses. So `config` displays and names its
authority.

**`ls` accepts only `/dev` in M2.** The honest refusal for other paths is
cheaper and more truthful than mapping `/a` onto the existing `dir`, which
would quietly imply the full ADR-0004 namespace exists.

**`bind` drains the wire before re-issuing HELLO.** After a dropped link
the ACIA can hold a stale byte and the peer may have queued a partial
frame. `bind` re-runs the `WRESET`/`WMODE` init and drains any pending
RDRF before framing. `rpc`'s bounded retry would eventually resynchronize
anyway, but a clean first attempt keeps the failure message honest — "no
response" should mean no response, not "we ate a stale byte".

**The harness gets a console watcher thread, not a new run model.**
`run_sim` blocks on `sim.wait()`, so mid-run control needs something else
watching. A thread tailing the console file for a marker (the `retronix>`
prompt, or a command's own output) and firing a callback is the smallest
addition that keeps every existing scenario untouched. Rejected: driving
SIMH interactively over stdin (fragile, and the current design deliberately
feeds SIMH a script), and splitting the recovery into two boots (it would
prove nothing about recovering *without a reboot*, which is the whole
requirement).

## Risks / Trade-offs

- **SIMH may not re-establish the outbound M2SIO socket after the server
  dies.** The scenario depends on AltairZ80 reconnecting to
  `connect=127.0.0.1:<port>` once the listener returns. → Verify early,
  before writing the assertions. Fallback that proves the same requirement:
  boot with no server at all (the machine lands in Local-Only Mode, as the
  existing server-down scenario shows), start the server mid-run, then
  `bind`. The socket is then established for the first time rather than
  re-established, which sidesteps the reconnect question entirely.
- **Memory pressure above E000.** The retained table (~320 bytes), the
  larger `RBUF` (+256), and three new command handlers all land in the
  monitor region. → Check the listing's end address after each build; there
  is roughly 7.5 KB between E000 and the stack, and M1 used a fraction of
  it, but this is the first milestone that adds bulk data.
- **Console-text assertions are brittle.** Three new commands mean three
  new display formats the harness matches on. → Match short stable
  substrings (a volume name, `local-only`, a device keyword), never whole
  lines or column layout.
- **Two servers, one log.** The restarted server appends to the same oracle
  log. → Assert on record counts and ordering rather than assuming the log
  belongs to one process lifetime.

## Open Questions

- Does AltairZ80's M2SIO retry an outbound connection after the peer
  closes? Answer decides which shape the recovery scenario takes (see the
  first risk); both shapes satisfy the spec.
- Exact `/dev` line format. Deliberately unspecified in the requirements —
  the content is normative, the column layout is not.
