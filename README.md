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

## M0 — the spine

`make m0` proves the spine: boot banner → HELLO against a machine profile →
drive map returned → `dir` on a bound volume, all under SIMH with the wire
on a TCP socket. Success is asserted against the server's structured JSONL
log, never scraped terminal text. Proven 10× consecutive green
(`python3 harness/run_m0.py --runs 10`) on 2026-08-02.

Each pass runs three scenarios:

- **spine** — the M0 exchange end to end; the oracle log must show exactly
  one `hello` (machine 1001, inventory populated, `A: → library`) and one
  `dir` (`result: ok`, entry count matching the volume directory).
- **server-down** — no server on the wire; the machine must land at the
  local-only prompt (never dead-end).
- **unknown-machine** — the server refuses an unprofiled machine ID with a
  clean `unknown-machine` error; the machine degrades to local-only.

Expected oracle shape for the spine scenario:

```json
{"verb": "hello", "machine_id": 1001, "rom_version": "0.1.0",
 "inventory": {"cpu": "8080", "ram_kb": 63, "serial_up": true},
 "drive_map": {"A": "library"}, "result": "ok", "ts": ...}
{"verb": "dir", "machine_id": 1001, "drive": "A", "volume": "library",
 "entry_count": 2, "result": "ok", "ts": ...}
```

(RAM honestly reads 63 KB: the sim's boot-ROM page occupies the top KB and
the self-test refuses to count what it can't write.)
