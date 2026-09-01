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
checksum-pinned universal binary (arm64 is native, no Rosetta). And its
expect/send layer (`-iw` / `-i`) is **tied to the stock ROM's keyboard hook**
and goes dead under a custom ROM (VERIFIED). The console channel therefore has
to be a byte stream we own: I verified the **printer port as a second TCP
endpoint** (`-p :PORT`, `OUT (0F8h),A`), which gives the harness a clean
console tap with no screen scraping at all — arguably better than SIMH's
`expect`, and squarely in line with the PRD's "assert against the protocol,
not scraped terminal characters."

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
| Second byte channel | Printer port `-p :PORT` (VERIFIED), second serial `-rB`, keyboard `-ip` | printer → stdout | printer → stdout |
| Console scripting | `-iw` wait-for-screen, `-i`/`-if` send, `-it` text-VRAM dump, `-is` screenshot, `-ib` script file, `-ix` exit, `-itime` timeout — all VERIFIED working under the **stock** ROM, all dead under a custom ROM | none | none (only the `zbx` debugger) |
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
  the HELLO handshake must be retried, not fire-and-forget.
- Automation under the **stock** ROM: `-id 120 -is -it -ix` exits 0 in 1.4 s
  and writes `trs80-0.gif` plus a 2048-byte `trs80-text-0.bin` (raw video RAM,
  64-column rows, plain ASCII for the printable range — trivially greppable).
- Automation under a **custom** ROM: the same flags produce nothing. `-iw`,
  `-id`, `-is`, `-it` all stall until `-itime` expires, then the queue is
  abandoned; with `-itime 0` it hangs forever. Tried `-icmd [ input key ]` and
  `[ input toggle ]` (matrix-level typing modes, which should not need a ROM
  hook) with no change — though the exact bracket quoting for `-icmd` is
  UNVERIFIED and is worth one more attempt before this is called settled.

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

1. **No console expect/send under a custom ROM.** The single biggest
   divergence from the SIMH harness. Mitigation is the printer-port TCP tap
   (verified) or a second serial port (`-rB`, documented); both mean the ROM
   must deliberately mirror console output. Whether `-ip :PORT` (keyboard
   input from a TCP endpoint) works without the stock ROM hook is UNVERIFIED
   and is the cheapest thing to test next — it would restore keystroke
   injection.
2. **Closed-source binary breaks the `build-tools.sh` pattern.** No source, no
   reproducible build, no patching if we hit an emulator bug — and the macOS
   app is ad-hoc signed, not notarized, so a downloaded copy needs
   `xattr -d com.apple.quarantine`. We would be pinning `trs80gp-2.5.7.zip`
   (25 MB) by checksum. Upstream keeps only the last few versions online, so
   vendoring the binary or hosting a mirror is prudent.
3. **No headless mode.** trs80gp always opens a window. It ran fine from this
   agent's shell inside a login session, but a CI runner with no window server
   is UNVERIFIED and likely broken. sdltrs has the same problem from the other
   direction.
4. **Connect race drops leading bytes.** Reproduced on every run: the first
   character of each stream vanished. The ROM's HELLO must be retried, and the
   harness needs the `run_linked_sim`-style "emulator never opened the wire"
   escape hatch on this platform too.
5. **Emulated baud throttles the wire.** Unlike the M2SIO under SIMH, trs80gp
   limits throughput to the programmed rate even on a TCP endpoint — a 32 KB
   COM file at 9600 baud is ~30 seconds of wall clock per scenario.
6. **`-rom` size behaviour on Model 4 is loosely specified.** A 95-byte image
   worked; sdltrs clamps to 14 KB and trs80gp's docs say nothing. Assume
   `0000`–`37FF` and do not exceed it.
7. **The map-switch relocation is new code with no analogue in the Altair
   BIOS.** Copy-to-RAM-then-switch is the riskiest part of the Model 4 ROM
   template and deserves its own scenario before the wire work starts.

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
