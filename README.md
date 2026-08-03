# RetroNix

A custom CP/M BIOS plus Unix-flavored shell for real 8080/Z80 hardware,
backed by a serial-connected server. Real bits on real silicon; the server
removes the friction. See `docs/RetroNix-PRD.md` for the full picture,
`docs/adr/` for the decisions, and `CONTEXT.md` for the vocabulary.

## Layout

- `machine/` — 8080 assembly: BIOS, monitor, wire protocol client
- `server/` — Python 3 (stdlib only): profiles, volumes, protocol, JSONL log
- `harness/` — the agent loop: bring up SIMH + server, run, assert, tear down
- `tools/` — `build-tools.sh` builds the toolchain from source into `tools/bin/`

## Toolchain

Built by `make tools` (or `tools/build-tools.sh`). Versions verified on
macOS arm64, 2026-08-02:

- **zmac 18oct2022** — 8080/Z80 cross-assembler, http://48k.ca/zmac.html
- **AltairZ80, Open SIMH V4.1-0** (commit a1f57fa3) — built `NOVIDEO=1`
- **Python 3** — system interpreter, stdlib only

## Proof: the spine, the filesystem, and the boot ladder

`make m0` proves the spine: boot banner → HELLO against a machine profile →
drive map returned → `dir` on a bound volume, all under SIMH with the wire
on a TCP socket. M2 adds the rungs above it — what the self-test found, what
each drive letter is bound to, and getting a dead link back without a
reboot. Success is asserted against the server's structured JSONL log and
SIMH's own expect matcher driving the console; the harness reads terminal
text only for the two things a matcher cannot express — a marker's
*absence*, and the mid-run triggers that stop and restart the server.
Proven 10× consecutive green across all thirteen scenarios
(`python3 harness/run_proof.py --runs 10`) against ROM 0.3.0 on 2026-08-02.

Roughly one attached session in a hundred, AltairZ80's outbound `connect=`
never completes: the server logs its `listening` line and nothing else, and
the machine lands local-only after exhausting its HELLO retries. When the
oracle shows that exact signature — not one byte across the wire, so neither
end is at fault — the harness runs the session once more and says so on
stdout, keeping the failed attempt's console as `*-noconnect.txt`. A retry
is never silent, so it cannot launder a regression into a pass. **Any
N-pass figure recorded here, including the one above, may therefore include
one or more announced retries** — the last recorded run had one, in pass 3.

Each pass runs thirteen scenarios:

- **spine** — the M0 exchange end to end; the oracle log must show exactly
  one `hello` (machine 1001, inventory populated, `A: → library`) and one
  `dir` (`result: ok`, entry count matching the volume directory).
- **run-com** — `run hello.com` and `run big.com` fetched over the wire
  execute on the local CPU (genuine BDOS function-9 calls through the shim
  at 0005h); the oracle must show FREAD offsets tiling each file exactly
  (BIG.COM: 0, 512, 1024).
- **type-missing** — `type about.txt` prints over the wire; `run nope.com`
  reports file-not-found on the console with the matching `file-not-found`
  oracle record.
- **server-down** — no server on the wire; the machine must land at the
  local-only prompt (never dead-end).
- **unknown-machine** — the server refuses an unprofiled machine ID with a
  clean `unknown-machine` error; the machine degrades to local-only.
- **dev-linked** — `ls /dev` with the link up: the self-test devices (CPU,
  RAM, console, and the wire reported up) and all sixteen drive letters with
  their bind state, `a: library` through `p: unbound`. The oracle log must
  gain no record while it runs — `/dev` is synthetic, and asking the server
  for it would be a lie.
- **dev-local** — the same listing after a boot with no server: the wire
  reads down, no letter claims a volume, and nothing reaches the wire.
- **config** — `config` on both rungs of the ladder. Machine ID, ROM version
  and burned-in link config appear in each; the link state reads `up` when
  linked and `local-only mode` when not; neither run sends anything, and
  both name the server profile as the drive map's owner.
- **multi-binding** — a profile binding `A: library` and `C: scratch`. Both
  bindings must appear in `config` and in `ls /dev` (with `b:` honestly
  unbound between them), the whole map must come back in the HELLO record,
  and `dir` must still address `A` — a wider map does not move the default
  drive. A `bind` on the still-live link then re-runs HELLO, adopts the map
  again, and prints no second banner.
- **empty-map** — a profile that binds nothing: the machine reports `link
  up: no network drives bound`, `config` reads `link state: up` with no
  bindings, `/dev` shows the wire up and every letter unbound, and the word
  local-only appears nowhere. An empty map is a live link, not a dead one.
- **bind-refusals** — the paths where the ladder does not climb. `ls /usr`
  gets the honest "only /dev is listable in this ROM version"; `bind`
  against a server holding somebody else's profile reports the refusal
  rather than a timeout, and the oracle must gain exactly one HELLO record
  across that bind, refused; and `bind` with nothing listening reports no
  response, bounded,
  and returns a usable prompt. One banner throughout.
- **link-recovery** — the whole loss-and-return cycle inside one boot. The
  machine links and lists a volume; the harness kills the server underneath
  it; `dir` reports `wire error: no response` rather than inventing a
  listing, because nothing on this wire is unprompted (ADR-0003) and silence
  is all the machine gets; the server comes back on the same port and the
  same oracle log; one `bind` — no reboot — brings the link up, and `dir`
  works again. Between the kill and the `bind`, `ls /dev` must show the wire
  down and the retained binding as `a: library (dead)` — named, not hidden,
  and distinct from a letter that was never bound. One log spanning both
  server lifetimes with a complete `ok` HELLO plus `ok` DIR exchange in
  each, and exactly one boot banner on the console: the prompt was never
  restarted.
- **teardown-after-failure** — the teardown guarantee proven on the path
  that risks it. A nested scenario stages a server restart and then fails
  outright; this one passes only if the restarted server process is dead and
  its port takes a fresh listener afterwards. Green runs show nothing leaks
  when scenarios pass; this shows nothing leaks when one does not.

Getting that scenario green took two emulator findings, both now handled in
the ROM. AltairZ80's M2SIO does re-dial its outbound `connect=` when a server
returns, but its MC6850 model latches DCD inactive the moment a socket dies,
so the machine keeps reading no carrier across the silent re-dial. The real
killer was subtler: bytes written into the dead ACIA during the failing `dir`
sat in SIMH's transmit buffer and were flushed the instant the socket came
back, arriving ahead of the re-bind HELLO and wedging the server mid-frame —
a timeout against a server that was up the whole time. `wtx` now gates
transmission on carrier as well as TDRE, so a dead link swallows no bytes and
nothing stale survives to be flushed, and `bind` clears the latched carrier
loss with a data-port read and waits out the re-dial instead of master-
resetting the connection away. Recovery is one command, about thirteen
seconds of it the bounded carrier wait. The measurements are in the comment
above `scenario_link_recovery` in `harness/run_proof.py`.

Expected oracle shape for the spine scenario:

```json
{"verb": "hello", "machine_id": 1001, "rom_version": "0.3.0",
 "inventory": {"cpu": "8080", "ram_kb": 63, "serial_up": true},
 "drive_map": {"A": "library"}, "result": "ok", "ts": ...}
{"verb": "dir", "machine_id": 1001, "drive": "A", "volume": "library",
 "entry_count": 3, "result": "ok", "ts": ...}
```

(RAM honestly reads 63 KB: the sim's boot-ROM page occupies the top KB and
the self-test refuses to count what it can't write.)
