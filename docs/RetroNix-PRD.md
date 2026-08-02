# RetroNix — Product Requirements Document

*Working name: RetroNix (a.k.a. retro-mix). Unix, with retro on the front.*

**Status:** Draft v0.1 — scaffold for iteration
**Owner:** Patrick McFadin

---

## 1. Summary

RetroNix is a small operating environment — really a custom CP/M BIOS plus a Unix-flavored shell — that boots on **real** 8080/Z80 machines (TRS-80, Altair, IMSAI, North Star, Cromemco, and other S-100 / CP/M hardware). It runs genuine 8-bit code on genuine silicon, and offloads the painful parts (storage limits, floppy shuffling, isolation) to a serial-connected server. The machine stays authentic; the server removes the friction.

The one-line pitch: **make vintage machines modernly accessible without violating the thing that makes them worth using — real bits on a real CPU.**

**Positioning:** RetroNix is its own system, not a fork or a distribution of an existing project. Individual pieces of what it does have been solved before — separately, by projects that don't talk to each other and aren't trying to be this. The invention is the assembly: one coherent product spanning the wire, the shell, the boot ladder, the library, and the foundry. §11 records what we learn from each precedent, deliberately as *lessons*, not dependencies.

---

## 2. Problem & Motivation

Vintage CP/M-era machines are wonderful but isolated. Storage is scarce and fragile, moving software onto them is a chore, and there's no easy on-ramp for new software. Emulation solves accessibility but throws away authenticity — you're no longer running on the real CPU.

RetroNix targets the gap between those two: keep the real hardware in the loop, but give it a modern backend over the one interface nearly all these machines already have — the serial port.

---

## 3. Goals / Non-Goals

### Goals
- Run real 8080/Z80 code on real hardware; the server never executes the machine's programs for it.
- Present a Unix-flavored experience (familiar prompt, `/dev`, `ls`) layered over CP/M-era hardware.
- Boot gracefully and **never dead-end** — always land somewhere usable, even with no server.
- Use the server as both a filesystem and a software library (a package repo for old iron).
- Let the server mint a per-machine boot ROM once a working config is captured ("ROM foundry").
- Give homebrew developers a frictionless path to distribute new software to these machines.

### Non-Goals (for v1)
- Not an emulator and not remote execution — no cheating the CPU.
- Not a full multi-user/multitasking OS; CP/M single-user semantics are fine.
- Auto-discovery is supported *conceptually* but is not required for v1 (see §6).
- No new hardware that violates the spirit of the machine.

---

## 4. Users

- **Collectors / operators** who want their TRS-80 or S-100 box to be genuinely useful again with a one-flip boot.
- **Homebrew developers** who want to write new software for old machines and have it reachable by everyone.
- **Tinkerers** who enjoy the Unix idiom and want a friendly window into what the hardware actually is.

---

## 5. The Five Pillars

1. **Honor the real CPU.** Real bits on real silicon; no emulation cheating. Program loading is native — the server ships a real COM binary down the wire and the local CPU runs it.
2. **Unix-flavored experience over CP/M-era hardware.** A Unix-y prompt; `/dev` reflects what the self-test found; familiar verbs map onto BIOS/BDOS underneath.
3. **A graceful boot ladder that never dead-ends.** Local-only mode is always available; config is always one command away.
4. **Server as filesystem + software library.** A network "drive" answered over serial; a browsable, runnable catalog of software — the package repo for old hardware.
5. **Server as ROM foundry.** Capture a machine's working config and burn the perfect per-machine boot ROM so the pain happens only once.

---

## 6. Boot Sequence (the graceful ladder)

1. **Power on / self-test.** Bring up the resident BIOS + monitor in high memory (below BDOS, roughly where the CCP lives).
2. **Device discovery → populate `/dev`.** Detect what's real: serial link, floppy controller, network drive if the wire is alive. `ls /dev` shows the honest inventory — diagnostics and familiarity in one gesture.
3. **Check saved config.** In priority order:
   1. Burned-in config (set at ROM-creation time by the foundry).
   2. Config saved to local disk.
   3. Manual config screen (`config` command — always present).
   4. *(Optional / later)* auto-discovery on the wire or subnet.
4. **If a link is found:** wire up the network drive; the full experience is available.
5. **If no link:** still drop to the Unix-y prompt in **local-only mode**. Never a dead end. `config` is always reachable.

*Open question: should a machine auto-connect by default, or wait to be told? Leaning: default to whatever the burned/saved config says; auto-discovery is an opt-in mode, not the default.*

---

## 7. Architecture

### 7.1 On the machine
- **Custom CP/M BIOS** — the swappable hardware-abstraction layer. This is the resident piece (not a DOS-style TSR; CP/M has no clean re-entrant hook for that, and the BIOS is *designed* to be swapped).
- The same ~17 BIOS entry points, but some are real silicon (floppy → real controller) and some are the wire (network drive → serial request). CP/M above it can't tell the difference; it just thinks it has more drives.
- A thin monitor/shell that gives the Unix-y surface.

### 7.2 The wire
- Serial line carries a simple request/response protocol: directory listings, sector/file reads, program fetches, config exchange.
- Because the server sits on the other end of every request, **it sees the whole protocol** — which makes it the natural test oracle (see §9).

### 7.2.1 OPEN DECISION: where to intercept

This is the fork everything else hangs off. Two viable layers:

**BIOS-level (sector-based).** Redirect at the ~17 BIOS entry points. CP/M above is completely unaware.
- *For:* maximum transparency; program loading falls out for free; simplest mental model; nothing above needs to change.
- *Against:* the server sees sector numbers, not filenames — weaker for the library, the foundry, and the test oracle. More round trips per operation.

**BDOS-level (file-based).** Redirect at the CP/M function-call layer, deciding per call whether a device is local or remote. (This is the layer CP/NET chose — see §11.)
- *For:* the server sees files and operations, which is strictly better for a browsable catalog, for config capture, and for asserting against structured data in the agent loop. Fewer, fatter round trips.
- *Against:* more surface area to get right; must handle programs that bypass BDOS; less transparent to software that pokes at the hardware.

*Leaning: BDOS-level, because pillars 4 and 5 both want file-level semantics. But this needs a decision before M0 — the wire protocol shape follows directly from it.*

### 7.3 The server
- **Filesystem service** — answers `dir`/`ls`/read requests for the network drive.
- **Software library / package repo** — a browsable catalog; "run this" fetches the real COM file to local RAM.
- **ROM foundry** — captures a validated config and builds a per-machine boot ROM.
- Runs as an ordinary host program; against an emulator it's just another process on the same machine.

---

## 8. Program Loading

Running a program from the network drive is *free* under the BIOS model: BDOS asks the BIOS for the file's sectors, the BIOS fetches them over serial, the CPU executes natively. No special load-and-jump path required.

---

## 9. Build & Test Strategy (agent-friendly)

- **Emulator-first** to de-risk: iterate in seconds instead of burning EPROMs and juggling null-modem cables.
- **Agent control loop:** bring up → run → evaluate → tear down, hundreds of iterations.
- Selection criteria for the emulator: **headless, scriptable, deterministic, text-capturable, swappable BIOS, socket/pipe serial.**
- **Leading candidate — SIMH AltairZ80** (Schorn build): command-line, script-driven, serial console redirectable to a socket, CP/M BIOS with source. Fastest path to the first round trip.
- **Authentic TRS-80 target — trs80gp:** documented support for a custom CP/M BIOS; good for proving the machine's real personality later.
- **The server is the test oracle:** the agent asserts against the structured protocol the server logs, not against scraped terminal characters — far less brittle.

---

## 10. First Milestone (the spine)

**Power on → custom BIOS prints a banner → opens the serial line → one round trip:** type `dir` on the network drive, the server answers with a directory listing.

If that single exchange works, the whole spine is proven: BIOS hook + wire protocol + server all shook hands. Everything after is adding verbs.

---

## 11. Prior Art — What to Learn From Each

None of these are dependencies. Each solved one slice of the problem; the notes below are what to steal conceptually and what to avoid.

### CP/NET (Digital Research, 1982) — *the closest ancestor*
The only prior system attempting essentially the same thing: CP/M machines getting remote resources over (typically) serial links.
- **Learn:** the NDOS/SNIOS factoring. A fixed logical redirector plus a small, machine-specific I/O shim is the right seam — it's why one design covered wildly different hardware. Our equivalent split should be just as clean.
- **Learn:** CP/NOS, the diskless ROM-resident variant, validates that a machine with no local storage is a legitimate configuration, not a degraded one.
- **Learn:** the message format (destination/source ID, function code, size) is a sane minimal framing to model ours on.
- **Avoid:** it assumed a competent operator doing manual setup. Our boot ladder and foundry exist precisely to eliminate that.
- **Modern reference implementation:** `durgadas311/cpnet-z80` — worth reading for serial framing and timeout handling on real Z80 UARTs. (Note: no license file present as of this writing.)

### DriveWire / pyDriveWire (TRS-80 CoCo) — *serial as a real disk bus*
- **Learn:** it proves the performance envelope. Pushing a bitbanger serial port to usable disk speeds means our latency budget is not the constraint we might fear.
- **Learn:** the server-side instance model — one server, many machines, each with its own set of virtual disks and ports.
- **Not applicable:** 6809 target, so no client code transfers.

### FujiNet — *the product design we're closest to in spirit*
- **Learn:** the config-disk boot flow. A machine that boots into its own configuration UI when unconfigured is exactly our "never dead-end" ladder, already validated with users.
- **Learn:** the N: device abstraction — offloading protocol complexity to the far side so the 8-bit machine stays simple. Our server should absorb complexity the same way.
- **Learn:** the community/distribution story. FujiNet's momentum came from making new software trivially reachable — direct evidence for pillar 4.
- **Not applicable:** it's ESP32 peripheral firmware; nothing transfers as code.

### RomWBW — *the boot and configuration layer*
- **Learn:** hardware discovery printed at boot, listing found device types and media. This is our `/dev` in all but name, and it's the proven UX.
- **Learn:** UNA's approach of persisting setup in NVRAM so one ROM image serves many platforms. Our foundry is the inverse bet (mint a ROM per machine) — worth understanding why they went the other way before we commit.
- **Learn:** drive-letter assignment as a dynamic, user-visible mapping rather than a fixed one.
- **Not applicable:** targets modern RetroBrew/RC2014 boards, not vintage TRS-80/S-100 iron.

### SamaruX — *the Unix surface, already proven on CP/M*
- **Learn:** the BusyBox-style built-in model, and specifically the two-build tradeoff (external commands to save TPA vs. built-ins to save disk). We will face this exact choice.
- **Learn:** named directories via `diralias`, `BINDIR`/`MANPATH` env vars, and startup profiles — a well-judged set of Unix idioms that actually fit CP/M's constraints.
- **Caution:** GPL-2.0-or-later, and built with the author's MESCC compiler. Read it for design; reimplementing keeps our licensing and toolchain free.

### Fuzix — *the road not taken*
A genuine Unix for Z80/8080, with a port model using a customization block plus the CP/M 2.2 BIOS aimed at S-100 machines.
- **Learn:** that porting technique is directly relevant to our multi-machine problem.
- **Why we're not it:** Fuzix *replaces* CP/M and cannot run CP/M `.COM` binaries. That breaks pillar 1. We want Unix *feel* over CP/M *compatibility*; Fuzix chose the opposite trade.

### Licensing note
CP/M and its Digital Research derivatives are now free to use, modify, and redistribute per DRDOS/Bryan Sparks' clarification. Historical DR material is safe to draw on directly. Modern reimplementations each carry their own terms — check before borrowing code rather than ideas.

---

## 12. Open Questions

- **Blocking M0:** BIOS-level vs. BDOS-level redirection (§7.2.1). Everything about the wire protocol follows from this.
- Auto-connect by default vs. wait-for-instruction?
- How much of CP/M (BDOS/CCP) stays resident vs. paged down at boot on RAM-tight machines?
- Discovery mechanism for a serial link vs. a subnet — and how far to take it in v1.
- Wire protocol: framing, error handling, binary-safe transfer (XMODEM/Kermit lessons apply).
- ROM targets: which "modern ROM" (e.g. a large flash / multi-ROM) to standardize the foundry around.
- Config storage format and where it lives when there's no disk.

---

## 13. Roadmap (rough)

- **M0 — Spine:** SIMH + custom BIOS + minimal server; one `dir` round trip.
- **M1 — Filesystem:** full network-drive read path; browse + run a real COM file over the wire.
- **M2 — Boot ladder:** self-test, `/dev`, config screen, local-only fallback.
- **M3 — Foundry:** server captures working config and burns a per-machine ROM.
- **M4 — Library:** push/pull software catalog; homebrew distribution.
- **M5 — Real iron:** validate on a physical TRS-80 / S-100 machine.
