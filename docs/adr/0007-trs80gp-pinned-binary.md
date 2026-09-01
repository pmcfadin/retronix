# TRS-80 Model 4 emulation uses trs80gp, pinned as a binary

`tools/build-tools.sh` builds every tool from source, and trs80gp cannot: it
is closed-source binary-only freeware. It gets an exception. `tools/` will
fetch `trs80gp-2.5.7.zip` against a pinned SHA-256, strip the quarantine
attribute the ad-hoc-signed app arrives with, and mirror the archive, because
upstream keeps only the last few releases online.

The exception is worth it because trs80gp is the only Model 4 emulator that
boots an arbitrary ROM *and* bridges the emulated RS-232 straight to a TCP
socket with no relay process. It dials out with `-r :PORT` in exactly the
shape AltairZ80's `attach m2sio1 connect=host:port` does, so the harness's
scenario runner keeps its structure across both platforms instead of growing
a second transport model. This was verified locally: a hand-assembled ROM
booted under `-m4`, drove the TR1865 at ports E8–EB, and its bytes arrived on
a listening Python socket (`docs/research/trs80-model4-emulation.md`).

The fallback, if trs80gp becomes untenable, is sdltrs plus a `socat` PTY
relay. sdltrs is BSD-2 and builds from source on macOS, and it takes the same
kind of ROM override — but its serial is a Unix tty only, so every scenario
would carry a relay process, and it has no scripting layer at all. We take
the binary over the relay.

Four caveats are accepted, not waved away. Without source there is no
patching around an emulator bug and no reproducible build; the checksum pin
and the mirror are the whole mitigation. The emulator's expect/send
automation is wired to the stock ROM's keyboard hook and goes dead under our
ROM, so console output is captured through the printer port as a second TCP
endpoint (`-p :PORT`) — which is closer to the PRD's "assert against the
protocol, not scraped terminal characters" than screen scraping ever was;
`-ip :PORT` was verified dead under a custom ROM (it waits on the stock
ROM's hook), and so was the assumed `-rB` fallback (accepted but wired to
nothing — the Model 4 only ever had one RS-232), so no scriptable console
input exists: interactive and real-iron input use a keyboard-matrix driver,
and headless proof rides the boot-time auto-report over the tap. trs80gp is not headless — it opens a window, so a CI runner
without a window server is out of reach for now. And the first byte of each
TCP stream is lost to a connect race on every run, which makes the BIOS's
HELLO retry loop load-bearing on this platform rather than merely prudent.
