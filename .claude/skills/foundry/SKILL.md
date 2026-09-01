---
name: foundry
description: Provision a RetroNix machine — create a machine profile, mint boot media, and read back refine state. Trigger phrases — "provision a machine", "mint a ROM", "new machine profile", "add a machine", "re-mint", "check needs-remint".
---

# Foundry: provisioning RetroNix machines

The foundry is the only thing that writes a machine profile. The running
server (`server/retronix_server.py`) only *reads* the store — it writes back
exactly one narrow thing (observed hardware facts and the `needs_remint`
flag, via HELLO reconciliation) and nothing else. Every other edit —
creating a machine, changing its drive map, minting boot media — goes
through `server/foundry.py`. If you find yourself editing a file under
`server/machines/` by hand, stop: that is what `foundry new`/`mint` are for.

See `docs/adr/0006-mint-is-template-plus-config-block.md` and
`openspec/changes/m3-foundry/design.md` for why the split exists.

## The provision loop

1. `new` — create a profile, get an assigned machine ID.
2. `mint` — stamp the profile into boot media (`build/mint/<id>.bin`).
3. Boot the mint (SIMH for Altair, trs80gp for Model 4).
4. `show`/`list` — check whether the boot's HELLO left `needs_remint` set.
5. If it did, `mint` again — the reconciled (observed) values get stamped
   this time — and go back to step 3. A profile becomes `exact` only after
   a boot whose HELLO agrees with what was just minted.

Minting never runs an assembler. It copies the platform's ROM template byte
for byte and rewrites only the reserved config block, so two mints of one
unchanged profile are byte-identical.

## CLI verbs

Run from the repo root: `python3 server/foundry.py [--machines-dir DIR]
[--volumes-file FILE] <verb> ...`. Both global flags default to the
server's own committed store (`server/machines/`, `server/volumes.json`).

### `new` — create a profile and assign a machine ID

```
python3 server/foundry.py new --make MAKE --model MODEL \
  --platform {altair-m2sio,trs80-model4-tr1865} \
  [--notes NOTES] [--rom-template PATH] \
  [--drive LETTER=volume ...] [--cpu N] [--ram-kb N] [--console N]
```

- `--platform` selects the ROM template and link-config defaults; there is
  no default — always pass it.
- `--drive LETTER=volume` is repeatable (`--drive A=library --drive
  C=scratch`); the volume name must exist in the volumes file.
- `--cpu`/`--ram-kb`/`--console` are the operator's *declared* guesses, not
  observations — they seed `hardware.declared` and are what makes a fresh
  profile `probe` rather than `exact`.
- `--rom-template` overrides the platform default
  (`build/retronix.bin` for Altair, `build/retronix-m4.bin` for Model 4).

Prints `created machine <id> (...)` on success. The ID comes from
`server/machines/.next-id`, a high-water mark that only ever advances —
retiring a machine never frees its ID for reuse.

### `list` — every profile in the store

```
python3 server/foundry.py list
```

One line per machine: ID, make/model, `state=probe|exact`, and
`[needs-remint]` when the flag is set.

### `show <machine_id>` — one profile in full

```
python3 server/foundry.py show 1001
```

Prints state (with `*** NEEDS RE-MINT ***` when flagged), drive map, link
config, `hardware.declared` vs `hardware.observed`, and the `mint` record
(checksum, sha256, timestamp, ROM version, what was last stamped). This is
the command to run after a boot to see whether the machine's HELLO agreed
with what was minted.

### `mint <machine_id>` — stamp a config block, write boot media

```
python3 server/foundry.py mint 1001 [--out-dir DIR]
```

Copies the profile's ROM template, stamps the config block (machine ID,
link config, cached drive map, checksum), and writes `<out-dir>/<id>.bin`
— `build/mint/<id>.bin` by default (gitignored; nothing under it is
committed). Also updates the profile: any hardware fact HELLO has observed
since the last mint becomes the new declared baseline, `mint.*` records the
new checksum/sha256/timestamp, `needs_remint` clears, and `state` resets to
`probe` — minting never confers `exact` on its own; only a subsequent
agreeing HELLO does that.

Refuses (exit 1, message on stderr, no traceback) if the machine has no
profile, the ROM template file is missing, or the template is too short for
the config block at its platform's fixed offset.

## Store layout

- `server/machines/<id>.json` — one file per machine, schema v1
  (`design.md`'s "Profile JSON schema"). Fields: `machine_id`, `identity`
  (make/model/notes), `platform`, `rom_template`, `link`, `drive_map`,
  `state` (`probe`|`exact`), `hardware.declared`/`hardware.observed`,
  `mint` (checksum/sha256/timestamp/rom_version/stamped), `needs_remint`.
- `server/machines/.next-id` — the sequential high-water mark, starting at
  1001. `new` reads it, writes `mark+1` back, *then* creates the profile —
  in that order, so a crash leaks an ID rather than ever reusing one. IDs
  are never derived from `max(existing files) + 1`; a deleted profile's ID
  is gone for good.
- `server/volumes.json` — volume definitions (name → path/kind), separate
  from the machines directory. `drive_map` entries in a profile name
  volumes from this file; `mint` fails if a name doesn't resolve.
- `build/mint/<id>.bin` — mint output, gitignored. Not the profile; not
  committed; regenerate it any time by re-running `mint`.

Only `server/machines/1001.json` is committed today. Machine 1002 (the
Model 4 proof machine) is minted on demand by the harness into a temp
`--machines-dir`, not checked in.

## Platforms and how each boots

- **`altair-m2sio`** — MITS Altair 8800 / M2SIO ACIA. Template
  `build/retronix.bin`. Boots under SIMH's AltairZ80 (`tools/bin/altairz80`)
  with the mint attached as the boot image and the M2SIO's `connect=`
  dialing the server's TCP port — the harness's `run_sim`/`run_linked_sim`
  path.
- **`trs80-model4-tr1865`** — TRS-80 Model 4 / TR1865 UART. Template
  `build/retronix-m4.bin`. Boots under trs80gp
  (`tools/bin/trs80gp.app`, fetched by `tools/fetch-trs80gp.sh` — see
  ADR-0007), launched as `open -a tools/bin/trs80gp.app --args -m4 -dx -hx
  -rom <mint>.bin -r :<wire-port> -p :<printer-port>` — exec'ing the binary
  path directly does not work; it must go through `open -a` to get a real
  WindowServer session (`docs/research/trs80-model4-emulation.md`,
  "Invocation matters"). The wire dials the server the same way the M2SIO
  does; the printer tap (`-p`) is a second socket carrying every console
  character, and it is **observe-only** — no scriptable keystroke-input
  channel exists under a custom Model 4 ROM (`-ip` and `-rB` are both dead;
  task 1.1). Because nothing can type at the prompt, the ROM proves its
  own shell on a linked boot: after the `config` block dump + `ls /dev`
  auto-report (printed twice), it auto-runs `dir`, `type about.txt`, and
  `run hello.com` through the same command dispatch a human would use —
  `dir`/`type`/`run` are implemented on the Model 4 template now, ported
  from the Altair one, so this is a real directory listing, the real text
  of `about.txt`, and `hello.com`'s genuine "HELLO, WORLD FROM RETRONIX"
  output after a real COM-file fetch over the wire. This whole sequence,
  oracle-backed (one `ok dir`, two `ok fread`), is what a harness scenario
  asserts against.

Both platforms share one config-block format and one foundry; only the
platform default's ROM template and link-config bytes differ
(`server/foundry.py`'s `PLATFORM_DEFAULTS`).

## The rule

The running server reads `server/machines/` and `server/volumes.json`; it
never creates, deletes, or rewrites a profile except the one narrow HELLO
write (observed facts + `needs_remint`, `server/reconcile.py`). Provisioning
a machine, changing its drive map, or fixing drift is always: edit nothing
by hand, run `foundry new`/`mint`, boot, `foundry show` to check the result.
