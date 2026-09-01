# TRS-80 Model 4 emulation for M3

Research for the second machine platform. Criteria: arbitrary system ROM,
RS-232 to TCP, headless/scriptable under the harness, reproducible macOS
(Apple Silicon) build. Claims marked VERIFIED were reproduced locally on this
machine; everything else cites documentation or source.

## Executive recommendation

**Use trs80gp.** It is the only candidate that boots an arbitrary ROM and
bridges the emulated RS-232 straight to a TCP socket with no relay process,
and it dials out with `-r :PORT` exactly the way AltairZ80's
`attach m2sio1 connect=host:port` does — so `Scenario.run_sim` keeps its shape.
I verified end to end: a 95-byte hand-assembled ROM booted on `trs80gp -m4`,
came up at `0000`, drove the TR1865 at ports `E8`–`EB`, and its bytes landed on
a Python socket the harness was listening on.

Two costs. trs80gp is **closed-source binary-only**, so it cannot join
`tools/build-tools.sh` as a from-source build — it becomes a downloaded,
checksum-pinned universal binary (arm64 is native, no Rosetta;
`tools/fetch-trs80gp.sh` pins SHA-256
`a994bd5e62a0d09b9f2f259bd3009bf42c361bdb2ac105d557aacfde1a7926d0` and mirrors
the archive as a GitHub release — see "Pinned binary and mirror" below). And
its expect/send layer (`-iw` / `-i`) is **tied to the stock ROM's keyboard
hook** and goes dead under a custom ROM (VERIFIED). The console **output**
channel therefore has to be a byte stream we own: I verified the **printer
port as a second TCP endpoint** (`-p :PORT`, `OUT (0F8h),A`), which gives the
harness a clean console tap with no screen scraping at all — arguably better
than SIMH's `expect`, and squarely in line with the PRD's "assert against the
protocol, not scraped terminal characters."

Console **input** is the harder problem, and it is now settled (M3 task 1.1,
VERIFIED): **`-ip` does not deliver keystrokes to a custom ROM under any
paste mode, and the design doc's assumed fallback (`-rB`, a second serial
endpoint) does not exist on the Model 4 either** — trs80gp accepts the `-rB`
flag and TCP connection for `-m4` at the argument-parsing layer, but no I/O
port a Z80 program can reach is wired to it (full 0-255 port sweep, zero
bytes delivered). The Model 4's *only* real, Z80-addressable, bidirectional
channel is the single TR1865 UART at `E8h`-`EBh` — the same one the wire
protocol already uses. See "Task 1.1: `-ip` and `-rB`, verified" below for
the full evidence and what this means for D7.

sdltrs is the fallback if a from-source build becomes non-negotiable: BSD-2,
builds on macOS via Homebrew, same `-romfile3` ROM override — but its serial is
a Unix tty only (needs a `socat` pty relay) and it has no scripting layer at
all.

## Candidate matrix

| | trs80gp 2.5.7 | sdltrs (jengun, SDL2) | xtrs (Tim Mann) |
|---|---|---|---|
| License / source | Closed-source, binary-only freeware | BSD 2-Clause, GitLab | Permissive (use "in whole or as a guideline"), GitHub |
| Model 4 support | `-m4`, plus 4P/4ga ROM revisions | Model I/III/4/4P | Model I/III/4/4P |
| Custom ROM | `-rom FILE`, any size — VERIFIED with a 95-byte image | `-romfile3 FILE` (Model III **and** 4); raw, Intel hex or CMD; clamped to 14 KB | `-romfile3 FILE`, same formats |
| RS-232 → TCP | Native. `-r :PORT` dial out, `-r @PORT` listen, `-r host:port`, `-r /dev/tty*` — VERIFIED | tty device only (`-serial NAME`); needs `socat PTY,raw ... TCP:` | tty device only (`-serial NAME`); same relay |
| Second byte channel | Printer port `-p :PORT` (VERIFIED, output only). `-ip` (keyboard) and `-rB` (second serial) both accept a TCP endpoint but neither reaches a custom Model 4 ROM (VERIFIED dead, task 1.1) | printer → stdout | printer → stdout |
| Console scripting | `-iw` wait-for-screen, `-i`/`-if` send, `-it` text-VRAM dump, `-is` screenshot, `-ib` script file, `-ix` exit, `-itime` timeout — all VERIFIED working under the **stock** ROM, all dead under a custom ROM. `-ip` (any of the three paste modes: OS Injection/Typing/Toggle) also VERIFIED dead under a custom ROM | none | none (only the `zbx` debugger) |
| Headless | No. Opens a Cocoa window; runs fine from a CLI inside a login session | No (SDL window; `SDL_VIDEODRIVER=dummy` untested and would kill screen capture) | No (X11; needs Xvfb) |
| macOS Apple Silicon | Universal `x86_64 + arm64` `.app`, ad-hoc signed — VERIFIED via `lipo`/`codesign` | Homebrew deps: `autoconf automake libtool llvm readline sdl2` | X11 build; least attractive on macOS |
| Verdict | **Adopt** | Fallback | Skip — sdltrs is its maintained descendant |

Nothing else surfaced as superior. David Keil's Model 4 emulator is DOS-era
and unmaintained; MAME's TRS-80 driver has no comparable custom-ROM or
socket-serial story for this use.

## What was verified locally

Assembled with the repo's own `tools/bin/zmac` (also George Phillips'), run
against `trs80gp` 2.5.7 for macOS:

- `trs80gp -m4 -dx -hx -rom m4probe.cim -r :PORT -p :PORT2` — a ROM containing
  nothing but our code executes from `0000`; RS-232 output arrives on one
  socket, printer output on the other. Both channels are the emulator dialing
  out to a listening harness.
- The emulator retries the outbound connection, so the harness may listen
  before or after launch. **Bytes written before the connection completes are
  dropped** — the first character of each stream was lost in every run. Same
  class of hazard as the `run_linked_sim` retry comment in `run_proof.py`;
  HELLO must be retried, not fire-and-forget.
- Automation under the **stock** ROM: `-id 120 -is -it -ix` exits 0 in 1.4 s
  and writes `trs80-0.gif` plus a 2048-byte `trs80-text-0.bin` (raw video RAM,
  64-column rows, plain ASCII for the printable range — trivially greppable).
- Automation under a **custom** ROM: the same flags produce nothing. `-iw`,
  `-id`, `-is`, `-it` all stall until `-itime` expires, then the queue is
  abandoned; with `-itime 0` it hangs forever. `-icmd [ input key ]` and
  `[ input toggle ]` (matrix-level typing modes) were retried under task 1.1
  with confirmed-correct bracket quoting (verified by their effect on `-ip`,
  below) and still do not reach a custom ROM's keyboard matrix. Settled.
- **Invocation matters and is a real trap.** Running `tools/bin/trs80gp`
  directly from a shell (even non-interactively backgrounded, even with the
  sandbox disabled) produces a process that sits in `NSApplicationMain`'s
  event loop forever: no window is ever composited, `-p`/`-ip`/`-rB` TCP
  endpoints never connect, and frame-driven automation (`-id`, `-ix`, the
  whole `-i`/`-iw` queue) never advances — it just hangs past its own
  `-itime`. The fix is `open -a tools/bin/trs80gp.app --args ...` instead of
  exec'ing the binary path; that gets a real WindowServer session (confirmed
  via `sample` and the unified log: `loginwindow`/`runningboardd` track the
  process, an audio session is created, `-p`/`-ip`/`-rB` connect) and every
  test below uses it. A consequence: `open` does not preserve the caller's
  working directory, so flags that write relative-path output files (`-is`,
  `-it`, `-im ... dump`) land somewhere other than the invoking shell's cwd;
  none of the files this research needed showed up under the working
  directory or `$HOME` after an `open -a` launch, and that was not chased
  down further. The harness will need to pass absolute paths everywhere and,
  if it ever needs `-is`/`-it` output, resolve where `open`-launched apps
  actually write before relying on it.
- **The printer tap drops more than "the first byte."** A single early
  write (e.g. a one-shot startup banner) is frequently lost outright, not
  just truncated by one byte — this is a stronger claim than the connect-race
  note above and supersedes it for anything less than a continuous stream. A
  *continuous* high-frequency stream (thousands of writes/sec, as in a tight
  `OUT (F8h),A` loop) reliably gets through once the TCP connection
  completes; sparse writes (a handful of characters, or one write per pass of
  a slower loop) are unreliable even several seconds into a run. Practical
  upshot for the BIOS console driver: a retry loop that reprints on a timer,
  not a one-shot print, is load-bearing on this platform for output too, not
  only for HELLO.

## Model 4 hardware facts for the ROM template

Cross-checked between Pete Cervasio's Model 3/4 I/O port reference and the
sdltrs/xtrs implementation (`src/trs_memory.c`, `src/trs_uart.h`,
`src/trs_interrupt.c`), which agree.

**Reset-time memory map.** `trs_reset` drives `OUT (84h),0`, i.e. memory map 0,
the Model III-compatible map, 64x16 video:

| Range | Contents |
|---|---|
| `0000`–`37FF` | System ROM, 14 KB. sdltrs clamps any `-romfile3` to `3800h` |
| `3800`–`3BFF` | Keyboard matrix (read) |
| `3C00`–`3FFF` | Video RAM, 1 KB window |
| `4000`–`FFFF` | RAM (bank 0) |

**Port 84h (write only, mirrored 84h–87h)** selects everything that matters:

- bits 1:0 — map select: `00` ROM in, Model III video/keyboard; `01` ROM out,
  RAM at `0000`–`37FF`, video/keyboard still at `3C00`/`3800`; `10` Model 4
  layout — RAM `0000`–`F3FF`, keyboard `F400`–`F7FF`, video `F800`–`FFFF`;
  `11` flat 64 KB RAM, no video or keyboard mapped.
- bit 2 — 0 = 64x16, 1 = 80x24. bit 3 — reverse video.
- bits 6:4 — 32 KB bank select for lower/upper halves (128 KB machines).
- bit 7 — video page select in 64x16 mode (the video RAM is 2 KB; only 1 KB is
  windowed at `3C00` in maps 0/1).

**Consequence for our BIOS, and it is the big one.** CP/M needs RAM at page
zero (`0005` BDOS entry, restart vectors). On a Model 4 the system ROM and page
zero RAM are mutually exclusive — there is no shadow-ROM trick like the 4P's
port `9Ch`. So the ROM must **copy itself into RAM and then switch maps**,
which is what Montezuma Micro CP/M does on this machine. Map `10` (RAM
`0000`–`F3FF`, video and keyboard still addressable) is the natural target: a
~61 KB TPA with the console hardware still in the address space, no bank
gymnastics in the console driver. Map `11` buys ~4 KB more and costs a
map-toggle with interrupts off around every screen or key access.

**Keyboard matrix**, memory-mapped at `3800`–`3BFF` (or `F400`–`F7FF` in map
`10`). Address bits 0–7 select rows; a read returns the OR of every selected
row's column bits. Rows: 0 `@ABCDEFG`, 1 `HIJKLMNO`, 2 `PQRSTUVW`, 3 `XYZ`,
4 `01234567`, 5 `89:;,-./`, 6 Enter/Clear/Break/up/down/left/right/Space,
7 LeftShift/RightShift/Ctrl/Caps/F1/F2/F3.

**RS-232 (TR1865), ports E8h–EBh:**

- `E8` out — master reset (value ignored). `E8` in — modem status:
  `80` CTS, `40` DSR, `20` CD, `10` RI, `02` receive-in.
- `E9` out — baud rate, high nibble transmit / low nibble receive. `0E` = 9600,
  `0F` = 19200 (`00`=50 … `07`=1200 … `0C`=4800). (`E9` in is the Model I
  sense switches only; the Model 4 has none.)
- `EA` in — UART status: `80` received-data-available, `40` transmitter-empty,
  `20` overrun, `10` framing, `08` parity.
- `EA` out — control: `80` even parity, `60` word length (`60`=8 bits,
  `20`=7), `10` two stop bits, `08` no parity, `04` **not**-break,
  `02` DTR, `01` RTS.
- `EB` in/out — data register.

Working init, as used in the verified probe: `OUT (E8h),0` then
`LD A,0EEh / OUT (E9h),A` (9600 both ways) then `LD A,6Fh / OUT (EAh),A`
(8N1, not-break, DTR, RTS). Note that trs80gp honours the programmed baud
rate as a throughput limit even over TCP — set 19200 (`FFh` to `E9`) if the
wire protocol needs the headroom.

**Interrupts.** Port `E0` is the maskable interrupt mask (out) / latch (in):
`40` UART error, `20` UART receive, `10` UART send, `04` heartbeat timer,
`02`/`01` cassette. Port `E4` is the NMI mask/latch (FDC INTRQ, motor timeout,
Reset button). Port `EC` in acknowledges the timer; `EC` out carries clock
speed (bit 6: 0 = 2 MHz, 1 = 4 MHz), video waits, I/O bus enable, alternate
character set, double width, cassette motor.

**Other ports we will touch.** `F0`–`F4` FDC (`-dx` disables it),
`F8` printer data with strobe (our console tap), `FF` cassette,
`88`–`8B` CRTC.

**How the stock machine would have handed control over.** The stock ROM sizes
memory, clears video, scans the keyboard for a boot-source override, reads
cylinder 0 sector 1 into `4300h`, and jumps there — on the 4P after
`OUT (9Ch),A` with A=0 switches the boot ROM out. We are not chaining that:
`-rom` replaces the image outright and our code owns `0000` from reset. The
handoff detail matters only if we ever want to boot from a floppy image
instead of from ROM.

## Risks and unknowns

1. **No console expect/send under a custom ROM, and no console input channel
   at all beyond the wire itself (VERIFIED, task 1.1 — no longer an open
   question).** The single biggest divergence from the SIMH harness, and it
   is worse than it looked before task 1.1: the printer-port TCP tap
   (verified, output only) is the only working console channel, `-ip :PORT`
   does **not** deliver keystrokes to a custom ROM under any paste mode
   (OS Injection stalls ~60s on the missing ROM hook and times out; Typing
   and Toggle modes don't stall but also never touch the keyboard matrix),
   and the assumed fallback — a second serial port, `-rB` — **does not exist
   on the Model 4**: trs80gp accepts the flag and the TCP connection, but a
   full 0-255 I/O port sweep from a running Z80 program delivers zero bytes
   to it, meaning no port a ROM can reach is wired to it (Model 4 hardware
   only ever had one RS-232; per the manual, dual serial via `-rA`/`-rB` is
   a Model 2-line feature trs80gp happens to accept the flag for regardless
   of machine type). The Model 4's only real, ROM-reachable, bidirectional
   channel is the single TR1865 UART at `E8h`-`EBh` — the same one the wire
   protocol uses. Full evidence in "Task 1.1: `-ip` and `-rB`, verified"
   below. **This narrows D7**: Model 4 scenarios that need to "type" at a
   prompt have no channel to do it through except the wire protocol itself,
   or `-ik`/software-keyboard-style direct matrix pokes issued from the
   trs80gp UI or a startup script (documented, static, not live-TCP-
   controllable — UNVERIFIED as a scripted-per-scenario mechanism and out of
   this task's scope; worth a look if D7 needs it). The M3 foundry design
   owner should revisit D7 with this in hand.
2. **Closed-source binary breaks the `build-tools.sh` pattern.** No source, no
   reproducible build, no patching if we hit an emulator bug — and the macOS
   app is ad-hoc signed, not notarized, so a downloaded copy needs
   `xattr -d com.apple.quarantine`. Mitigated (M3 task 1.2/1.3):
   `tools/fetch-trs80gp.sh` pins `trs80gp-2.5.7.zip` (25 MB) to SHA-256
   `a994bd5e62a0d09b9f2f259bd3009bf42c361bdb2ac105d557aacfde1a7926d0`, fails
   loudly on any mismatch, and tries a project-controlled mirror before
   upstream — see "Pinned binary and mirror" below.
3. **No headless mode.** trs80gp always opens a window. It ran fine from this
   agent's shell inside a login session, but a CI runner with no window server
   is UNVERIFIED and likely broken. sdltrs has the same problem from the other
   direction.
4. **Connect race drops leading bytes.** Reproduced on every run: the first
   character of each stream vanished. The ROM's HELLO must be retried, and the
   harness needs the `run_linked_sim`-style "emulator never opened the wire"
   escape hatch on this platform too. Mitigated in the built template
   (`machine/bios_m4.asm`) by HELLO's bounded retry loop and, for the
   printer tap specifically, by printing the boot-time auto-report twice
   (`BOOTREPS`) — see "M3 implementation findings" below, which also
   documents a second, unrelated printer-tap loss this research did not
   catch.
5. **Emulated baud throttles the wire.** Unlike the M2SIO under SIMH, trs80gp
   limits throughput to the programmed rate even on a TCP endpoint — a 32 KB
   COM file at 9600 baud is ~30 seconds of wall clock per scenario.
6. **`-rom` size behaviour on Model 4 is loosely specified.** A 95-byte image
   worked; sdltrs clamps to 14 KB and trs80gp's docs say nothing. Assume
   `0000`–`37FF` and do not exceed it.
7. **The map-switch relocation is new code with no analogue in the Altair
   BIOS.** Copy-to-RAM-then-switch is the riskiest part of the Model 4 ROM
   template and deserves its own scenario before the wire work starts.
   Resolved: proved in isolation (task 4.1, `build/probe/m4reloc.asm`) and
   again by the full boot ladder end to end — see "M3 implementation
   findings" below.

## Pinned binary and mirror (M3 tasks 1.2, 1.3)

`tools/fetch-trs80gp.sh` fetches, verifies, and installs trs80gp 2.5.7 into
`tools/bin/`, following the pattern in `tools/build-tools.sh` (which calls it
at the end of its own run) but as a checksum-pinned download rather than a
source build, per ADR-0007 (`docs/adr/0007-trs80gp-pinned-binary.md`).

- **Archive**: `trs80gp-2.5.7.zip`, 25,175,647 bytes.
- **Pinned SHA-256**:
  `a994bd5e62a0d09b9f2f259bd3009bf42c361bdb2ac105d557aacfde1a7926d0`.
- **Mirror** (tried first): GitHub release asset on this repo —
  `https://github.com/pmcfadin/retronix/releases/download/tools-trs80gp-2.5.7/trs80gp-2.5.7.zip`
  (release tag `tools-trs80gp-2.5.7`, created via `gh release create`; this
  succeeded — `gh` was already authenticated in this environment).
- **Upstream** (fallback): `http://48k.ca/trs80gp-2.5.7.zip`.
- Either source is checked against the same pin; a mismatch from either is
  fatal and installs nothing (verified: corrupting the pin in a throwaway
  copy of the script produces a checksum-mismatch failure with a nonzero
  exit, not a silent fallback).
- The script strips `com.apple.quarantine` from the `.app` unconditionally
  (harmless no-op if the attribute is already absent, as it is for a `curl`
  download outside Finder/a browser) and installs
  `tools/bin/trs80gp.app` plus a `tools/bin/trs80gp` symlink to the Mach-O
  inside it.
- There is no reliable "did it install correctly" smoke test: trs80gp has no
  flag that prints a version and exits non-interactively (see "Invocation
  matters" above) — every invocation opens a window. The script confirms the
  binary landed and is executable; that is as far as automated verification
  goes.

## Task 1.1: `-ip` and `-rB`, verified

Both tested against a throwaway probe ROM
(`build/probe/m4probe.asm` → `m4probe.cim`, not part of `machine/`): reset
lands at `0000` (map 0, ROM active), the probe scans all 8 keyboard-matrix
rows (`3801h`, `3802h`, `3804h`, ..., `3880h`) in a tight loop and writes a
`'K'` heartbeat to the printer tap (`F8h`) every pass, plus `'R'<row><mask>`
whenever a row reads non-zero. The heartbeat proves the ROM is alive and
gives a continuous, reliable signal (see "the printer tap drops more than
the first byte" above) that survives the connect race; an `'R'` triple is
unambiguous evidence a keypress reached the matrix.

Launch (the invocation that actually works — see "Invocation matters"
above):

```
open -a tools/bin/trs80gp.app --args \
  -m4 -dx -hx -rom <abs-path>/m4probe.cim \
  -p :<printer-port> -ip :<keyboard-port> \
  [-icmd [ input key ]   |   -icmd [ input toggle ]]
```

Both `:<port>` endpoints are listened on by the test harness first (trs80gp
dials out, per the Endpoints section of the manual); `-icmd [ input MODE ]`
sets the Paste Mode trs80gp uses to interpret anything sent to `-ip` (or
pasted, or `-i`).

**Result: `-ip` does not reach the matrix under any Paste Mode.**

- **Default (OS Injection, `char` mode).** Sending a byte to `-ip` makes the
  printer-tap heartbeat stop *completely* for very close to 60 real seconds
  (trs80gp's default `-itime`, 3600 frames), then resume at the same rate as
  before. This is the automated-input state machine waiting on the stock
  ROM's keyboard-input-routine hook, exactly as documented for `-i`/`-iw`,
  and exactly as dead under a custom ROM. No `'R'` ever appears, before or
  after the stall.
- **Typing (`-icmd [ input key ]`).** Sending a byte to `-ip` causes no
  stall at all (heartbeat continues at an undisturbed rate through and past
  the send) but also no `'R'` — the byte has no observable effect on the
  matrix.
- **Toggle (`-icmd [ input toggle ]`).** Same as Typing: no stall, no `'R'`.
  Toggle mode is supposed to hold a key down until explicitly released,
  which should be trivial to catch in a tight scan loop over a 20-second
  window; it never appeared.

The difference in behavior between `char` mode (stalls) and `key`/`toggle`
modes (don't stall) is itself proof `-icmd [ input ... ]`'s bracket argv
syntax parses correctly here (each mode visibly changes behavior), closing
the "exact bracket quoting is UNVERIFIED" note from the earlier round of
this research. The conclusion is not a syntax problem: `-ip`'s keyboard
stream is fed through the same Paste Mode machinery as `-i`, and none of the
three modes reaches a keyboard matrix that isn't gated behind the stock
ROM's own routines.

**Result: `-rB` accepts a connection on `-m4` but no I/O port reaches it.**

The design doc's assumed fallback was "ROM-owned console input over a
second serial endpoint (`-rB`)". Tested by sweeping every I/O port `00h`
through `FFh` from a Z80 program (`build/probe/m4portsweep.asm`,
fully-unrolled immediate `OUT (n),A` — see the note below on why unrolled,
not self-modifying or `OUT (C),A`) while `-rB :PORT` was the only endpoint
attached: the harness's listener on that port accepts the TCP connection
(so trs80gp treats `-rB` as valid for `-m4`, contradicting the manual's
"most machines have a single serial port ... the Model 2 line has two" —
it looks like the flag is accepted unconditionally, without a
does-this-machine-have-Port-B check), but **zero bytes ever arrive**, over a
20-second capture, sweeping every port continuously. The same sweep program,
pointed at `-p` (printer) instead of `-rB`, delivers a continuous stream of
`F8h` bytes (proving the sweep itself works and does reach real hardware).
Model 4 genuinely has only the one RS-232 (`E8h`-`EBh`); `-rB` is a
process-level flag trs80gp happens not to reject for this machine, not a
real second UART a ROM can address.

Two pitfalls hit while building the port sweep, worth recording so nobody
re-derives them:

- **Sweeping `84h`-`87h` with the port number as the data byte crashes the
  sweep.** Those ports are the Model 4 memory-map-select register (bits 1:0
  of the *value written* choose the map); writing `85h` there selects map 1
  (ROM out, RAM at `0000`-`37FF`) and yanks the running program's own ROM
  out from under it mid-sweep, so instruction fetch immediately starts
  reading uninitialized RAM. The sweep must write `00h` (stay on map 0) at
  those four ports specifically. This is *why* the first sweep attempt
  produced nothing at all, even on the already-proven-working printer tap —
  not a channel problem, a self-inflicted crash. Confirmed by fixing it and
  seeing the printer tap immediately produce a clean, continuous `F8h`
  stream again.
- **`OUT (C),A` (`ED 79`) never reached the printer tap either, even for
  port `F8h`**, in an earlier version of the sweep that used it instead of
  immediate `OUT (n),A`. Root cause not isolated (candidates: `B` register
  garbage putting the full 16-bit `BC` address bus out of the decoded range,
  or the emulator's I/O dispatch not handling that opcode form the same way
  as immediate `OUT`); switched to the immediate form, which is also what
  every other probe here and `machine/bios.asm` already use, and moved on
  rather than chasing an opcode encoding this project doesn't plan to use.

**Chosen Model 4 console channel, settled**: printer tap (`-p :PORT`) for
output, exactly as already documented above and in `design.md`. For input,
there is no scriptable channel independent of the wire — the single TR1865
UART (`-r :PORT`, `E8h`-`EBh`) already used for the wire protocol is the only
one available. Whoever picks up D7 needs this: Model 4 scenarios cannot
simulate "typing at a prompt" as a keystroke stream the way `-ip` was
assumed to allow; interaction has to go through the wire protocol itself, or
through a non-live mechanism (`-ik`, direct keyboard-matrix pokes — VERIFIED
to *exist* as a documented flag in the manual but not exercised here; it
takes a static `row mask` pair on the command line or via script, not a
per-scenario TCP stream, so it is a poor fit for a live harness without
further work).

## M3 implementation findings (post-research, verified)

Three things this research didn't catch, found while building
`machine/bios_m4.asm` (M3 group 4) and closed out by the M3 harness proof
(group 5). All three are VERIFIED against the built template, not the
throwaway probe ROMs above.

**The printer tap loses bytes to the emulated strobe timing, not just to
the TCP connect race.** The "printer tap drops more than the first byte"
finding above is about *sparse* writes racing the TCP connection. Building
the real console driver (task 4.3) surfaced a second, independent hazard:
back-to-back `OUT (F8h),A` writes with **no pacing at all** lose roughly 2
of every 3 bytes to the emulated printer's own strobe timing, a
fixed-stride loss that shows up even on a long-since-connected socket, well
past any connect race. Measured empirically in the task 4.1 proof
(`build/probe/m4reloc.asm`) by sending a known byte sequence unpaced and
counting what the tap actually received. The fix is a per-character
inter-write delay: `machine/bios_m4.asm`'s `putc` does `OUT (PRT),A` then
spins a `PDELAY` (`400h`) countdown before the next character. `400h` is
the smallest tested value that produced zero loss across a multi-second
capture, not a proven-tightest bound. Consequence for the harness: even
with pacing, the very first repetition of the boot-time auto-report can
still catch the tail end of the connect race (a separate hazard, unfixed by
PDELAY since it's about connection timing, not strobe timing), which is
why the ROM prints the report `BOOTREPS` (2) times and any scenario reading
the tap should key off the *last* repetition, guaranteed complete.

**The wire's retry-timeout constant needed a smaller value on this
platform.** `machine/bios.asm`'s Altair template uses an outer-loop bound
of 16 for its wire-timeout polling (`TOUTER`), tuned against SIMH's Altair
timing. Measured empirically against a minted Model 4 image with nothing
on the wire (`build/probe/m4boot_test.py`): 16 takes several minutes of
real wall-clock time on trs80gp's Z80 timing before HELLO's bounded retry
gives up, which is impractical for a scenario. `machine/bios_m4.asm` uses
`TOUTER equ 4` instead — deliberately not the Altair's 16 — which reaches
the Local-Only prompt in about 5 seconds (2 reaches it in about 4). The two
platforms' relationship between this constant and real elapsed time is not
the same, so the two templates carry different values by design, not by
oversight. A genuine HELLO round-trip never approaches this bound on
either platform — it only governs how long a dead link takes to be
declared dead.

**The full boot ladder ran end to end on the platform, confirmed by the
harness.** Relocate-to-RAM, jump into the copy, map switch to Model 4
layout, page-zero vector setup, TR1865 wire bring-up, config-block
read/validate, `DMAP` preload from the block, HELLO with its bounded retry
surviving the connect race's dropped first byte, banner, and the
boot-time auto-report (`config` block dump + `ls /dev`, printed twice) —
all of it runs on a minted `build/retronix-m4.bin` image under trs80gp, not
just on the throwaway probe ROMs this research used. The M3 harness's
`two-machines` scenario is the isolation proof: it mints machine 1002,
boots it under trs80gp against a live server, and asserts the HELLO
reconciled correctly (the console reaches `retronix> ` showing exactly the
minted drive map, distinct from machine 1001's).

A later fix round ported `dir`/`type`/`run` to the Model 4 template
byte-for-byte from `machine/bios.asm` — design.md's originally-accepted
fallback of narrowing the Model 4 shell to `config`/`ls`/`bind` this
milestone turned out not to be needed — and added a linked-boot auto-demo
(`machine/bios_m4.asm`'s `bootdemo`) that exercises the real dispatch path
unprompted: `boot demo: dir`, `boot demo: type about.txt`, `boot demo: run
hello.com`. `run hello.com` fetches an actual CP/M COM file over the wire
and executes it on the TRS-80 — the console's `HELLO, WORLD FROM RETRONIX`
is the program's genuine output,
not a canned string. The `m4-demo` scenario is the oracle-backed proof,
run against a volume that actually carries the library fixtures: one `ok
dir` (3 entries) and two `ok fread` records (`ABOUT.TXT`, `HELLO.COM`).
This remains an **observe-only** proof throughout — the demo exists
specifically because the harness has no scriptable input channel to the
Model 4 (above), so the ROM demonstrates its own shell instead of being
typed at.

Confirmed across ten consecutive harness runs, 2026-09-01 (now eighteen
scenarios a pass, `m4-demo` included) — 180/180 green, no announced
retries, roughly 3.65 minutes per pass with the trs80gp legs dominating
the wall clock.

## Sources

- trs80gp manual and option reference — http://48k.ca/trs80gp.html
- trs80gp 2.5.7 distribution (Windows/mac/linux/rpi binaries) — http://48k.ca/trs80gp-2.5.7.zip
- trs80gp release notes — http://48k.ca/trs80gp-release-notes.html
- trs80gp license status ("closed-source binary-only") — https://slackbuilds.org/repository/15.0/games/trs80gp/
- zmac (same author; already in `tools/build-tools.sh`) — http://48k.ca/zmac.html
- sdltrs — https://gitlab.com/jengun/sdltrs (README.md, BUILDING.md, `src/trs_uart.h`, `src/trs_memory.c`, `src/trs_cmd_rom.c`, `src/trs_interrupt.c`, `src/trs_options.c`)
- sdltrs documentation — https://jengun.gitlab.io/sdltrs
- xtrs — https://www.tim-mann.org/xtrs.html and https://github.com/TimothyPMann/xtrs (`xtrs.man`)
- Model 3/4 I/O ports, Pete Cervasio — http://cpmarchives.classiccmp.org/trs80/mirrors/kjsl/www.kjsl.com/trs80/mod34ioports.html
- Model 4P boot ROM disassembly — https://www.trs-80.com/sub-disassem-rom-m4p.htm
- Model 4 Technical Reference Manual (Tandy, 1983) — https://usermanual.wiki/Document/Model4TechnicalReferenceManual1983Tandy.1156735692.pdf (not fetched; listed for follow-up)
