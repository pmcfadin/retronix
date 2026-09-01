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
M3 (below) folds in a foundry, a second machine, and five more scenarios;
the harness now runs all eighteen together every pass, and the latest
10-consecutive-run proof — Altair ROM 0.4.0, both machines minted through
the foundry — is 180/180 green with no announced retries, 2026-09-01
(~3.65 minutes per pass, the trs80gp legs dominating the wall clock).

Roughly one attached session in a hundred, AltairZ80's outbound `connect=`
never completes: the server logs its `listening` line and nothing else, and
the machine lands local-only after exhausting its HELLO retries. When the
oracle shows that exact signature — not one byte across the wire, so neither
end is at fault — the harness runs the session once more and says so on
stdout, keeping the failed attempt's console as `*-noconnect.txt`. A retry
is never silent, so it cannot launder a regression into a pass. **Any
N-pass figure recorded here, including the one above, may therefore include
one or more announced retries** — the last recorded run had one, in pass 3.

Each pass runs eighteen scenarios:

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
- **two-machines** — mint 1001 (Altair) and 1002 (Model 4) with different
  drive maps, boot each in turn against one server, and assert one ok HELLO
  per machine ID and that neither console shows the other's bindings. One
  emulator process at a time.
- **m4-demo** — the Model 4's real dispatch path, proven against a volume
  that actually carries the library fixtures (`two-machines` deliberately
  boots 1002 against an empty "scratch" map, to keep the isolation point
  crisp). On a linked boot the ROM auto-runs `boot demo: dir`, `boot demo:
  type about.txt`, and `boot demo: run hello.com` unprompted — the same
  synthetic-command path an operator's own typing would take — so the
  console shows a real directory listing, the real text of `about.txt`,
  and `HELLO, WORLD FROM RETRONIX` once `hello.com` is actually fetched
  over the wire and executed on the TRS-80. Oracle stays the authority:
  one `ok dir` (3 entries) and two `ok fread` (`ABOUT.TXT`, `HELLO.COM`).
- **probe-loop** — a profile with unknown RAM: mint, boot, observed facts
  recorded and `needs-remint` set, re-mint, boot again, `exact` and the flag
  clear. The two mints differ only inside the config block.
- **drift** — a profile edited after minting, then a boot of the unchanged
  image: the response carries the edited map, and the profile ends the run
  with `needs-remint` set. Same mechanism as `probe-loop`, seen from the
  other direction.
- **block-integrity** — `config` on a booted mint reports the machine ID,
  link config, and baked bindings the foundry stamped, and reports the
  block valid.

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

### The foundry: profile → mint → boot → HELLO → refine

Machine 1001 used to exist because its identity was hand-written into
`server/profiles.json` and duplicated a second time into `machine/bios.asm`
as assembly constants — provisioning a second machine meant editing
assembly and rebuilding. M3 closes that (ADR-0006): `server/foundry.py new`
assigns a machine ID from `server/machines/.next-id` (sequential from 1001,
never reused, even after a machine is retired) and writes a profile to
`server/machines/<id>.json`; `foundry mint <id>` copies the platform's ROM
template byte for byte and stamps a fixed-address config block — magic,
machine ID, link config, cached drive map, checksum — into
`build/mint/<id>.bin`. No assembler runs on the mint path, so two mints of
one unchanged profile are byte-identical. The BIOS reads its identity out
of that block at cold boot, before the wire is touched; an unstamped
template lands honestly in Local-Only Mode instead of dialing with a
garbage machine ID.

A profile is born `probe`. Every HELLO reconciles what the machine actually
reported — hardware inventory, ROM version — against what was last minted;
any disagreement sets `needs_remint` and leaves the profile at `probe`. The
next `mint` stamps the reconciled (observed) values and clears the flag; a
subsequent HELLO that agrees makes the profile `exact`. Editing a profile
by hand after minting it hits the same mechanism as a fresh probe — drift
and first-boot reconciliation are one code path, exercised by the
`probe-loop` and `drift` scenarios above. The running server only ever
reads `server/machines/`; every write except that one narrow HELLO
reconciliation goes through the foundry CLI. `.claude/skills/foundry/
SKILL.md` has the full verb-by-verb loop.

### Two platforms, one proof

M3 mints and boots two machines of different makes from one command line:
1001 (Altair 8800, `build/retronix.bin`) under SIMH as before, and 1002
(TRS-80 Model 4, `build/retronix-m4.bin`) under trs80gp. A Model 4 has no
shadow-ROM trick to keep the system ROM and page-zero RAM both present, so
the template copies itself into RAM above `4000h`, jumps into the copy,
and only then switches the port-84h memory map before page zero can exist
— the same relocate-then-switch idea Montezuma Micro CP/M used on real
hardware, proved in isolation before any wire code was written (task 4.1).
The wire is a TR1865 UART at `E8h`-`EBh`, the same protocol as the Altair's
M2SIO. Full hardware detail is in
`docs/research/trs80-model4-emulation.md`.

trs80gp is closed-source freeware (ADR-0007,
`docs/adr/0007-trs80gp-pinned-binary.md`), so it doesn't join the rest of
the toolchain's from-source build. `tools/fetch-trs80gp.sh` — called from
`tools/build-tools.sh`, or run standalone — downloads `trs80gp-2.5.7.zip`
and checks it against a pinned SHA-256, trying a project-controlled GitHub
release mirror first (upstream keeps only the last few releases online)
and falling back to upstream; a checksum mismatch from either source is
fatal, never a silent fallback to an unverified copy. The script also
strips the ad-hoc-signed app's quarantine attribute so it launches without
a Gatekeeper prompt.

The Model 4 leg of the harness is **observe-only**, and this was verified
rather than assumed (M3 task 1.1): no scriptable keystroke-input channel
exists under a custom ROM. Both `-ip` (keyboard injection) and the design's
assumed fallback, a second serial endpoint (`-rB`), were tested against a
probe ROM and found dead — `-ip` stalls on a stock-ROM hook this ROM
doesn't have, and `-rB` accepts a TCP connection but delivers zero bytes to
any I/O port a Z80 program can read. The keyboard-matrix driver that will
make the machine usable interactively is code-complete in
`machine/bios_m4.asm` (task 4.6) — real and typeable in trs80gp's own
window, and the driver the real-iron machine will use — but the harness
has no channel to exercise it over TCP, so it stays untested by
`run_proof.py`.

Because the harness can never type at the Model 4 prompt, the ROM proves
its own shell instead: on a linked boot it auto-runs a demo — `boot demo:
dir`, `boot demo: type about.txt`, `boot demo: run hello.com` — through
the same synthetic-command dispatch path (`dircmd`/`typecmd`/`runcmd`,
ported byte-for-byte from `machine/bios.asm`) an operator's own typing
would take, right after the banner, HELLO, and the `config`/`ls /dev`
auto-report, all read off the printer port's TCP tap (`-p :PORT`) the same
way SIMH's console file is read. `dir`, `type`, and `run` are real on the
Model 4 now, not stubs: the demo's `run hello.com` fetches an actual CP/M
COM file over the wire and executes it on the TRS-80, and the console
shows `HELLO, WORLD FROM RETRONIX` — hello.com's genuine output — not a
canned string. The `m4-demo` scenario above is the oracle-backed proof:
one `ok dir` over the real volume and two `ok fread` records
(`ABOUT.TXT`, `HELLO.COM`), plus the console carrying each real payload.

The `two-machines` scenario is the two-platform isolation proof: mint 1001
and 1002 with different drive maps, boot each in turn against one server
(one emulator process at a time — SIMH, then trs80gp), and confirm neither
console shows the other's bindings.

Expected oracle shape for the spine scenario:

```json
{"verb": "hello", "machine_id": 1001, "rom_version": "0.4.0",
 "inventory": {"cpu": "8080", "ram_kb": 63, "serial_up": true},
 "drive_map": {"A": "library"}, "result": "ok", "ts": ...}
{"verb": "dir", "machine_id": 1001, "drive": "A", "volume": "library",
 "entry_count": 3, "result": "ok", "ts": ...}
```

(RAM honestly reads 63 KB: the sim's boot-ROM page occupies the top KB and
the self-test refuses to count what it can't write.)
