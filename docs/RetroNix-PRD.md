# RetroNix — Product Requirements Document

*Working name: RetroNix (a.k.a. retro-mix). Unix, with retro on the front.*

**Status:** Draft v0.2 — core architecture decided; decisions live in `docs/adr/`, vocabulary in `CONTEXT.md`
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
5. **Server as ROM foundry.** Provisioning starts on the server: create a machine profile, and the foundry mints boot media (EPROM or boot floppy image) with the BIOS, link config, and machine ID baked in. Machines are born configured; re-mints are one click (ADR-0005).

---

## 6. Boot Sequence (the graceful ladder)

1. **Power on / self-test.** Bring up the resident BIOS + monitor in high memory (below BDOS, roughly where the CCP lives).
2. **Device discovery → populate `/dev`.** Detect what's real: serial link, floppy controller, network drive if the wire is alive. `ls /dev` shows the honest inventory — diagnostics and familiarity in one gesture.
3. **Resolve config.** In priority order:
   1. Burned-in config (baked at mint time: link config + machine ID + cached drive map).
   2. Config cached on local disk (refreshed automatically whenever the server updates the map).
   3. Manual config screen (`config` command — always present).
4. **If configured, HELLO.** The machine presents its machine ID, ROM version, and self-test inventory; the server answers with the profile's current drive map and binds the network drives. Session config is reconciled every boot; drift from the burned ROM flags the profile for re-mint (ADR-0005).
5. **If no link:** still drop to the Unix-y prompt in **local-only mode**. Never a dead end. Dead binds degrade gracefully; re-binding after the server returns is one command, not a reboot. `config` is always reachable.

*Resolved: config decides. An unconfigured machine never probes the wire on its own; auto-discovery, if it ever exists, is an explicit action inside `config`, not ambient boot behavior.*

---

## 7. Architecture

### 7.1 On the machine

RetroNix *ships* CP/M rather than requiring it — the minted boot media carries the whole stack. A bone-stock 1982 `.COM` file runs unmodified and cannot tell a network drive from a floppy.

- **Custom CP/M BIOS** (ours) — the swappable hardware-abstraction layer, driving real silicon only.
- **BDOS** (genuine CP/M) — untouched; programs call `0005h` exactly as they did in 1982.
- **Redirector** (ours) — sits in front of BDOS and routes each call per the drive map: local drive → real BDOS/BIOS, network drive → the wire (ADR-0001). This is CP/NET's NDOS/SNIOS factoring, reimplemented.
- **Shell** (ours) — the Unix-flavored surface wrapping the CCP. Namespace is `/<drive>/<file>`, exactly two levels, with `/dev` as the synthetic self-test inventory; both `/b/readme.txt` and `b:readme.txt` are accepted, and COM programs receive pure CP/M command tails (ADR-0004).

### 7.2 The wire
- Strict request/response: the machine initiates every exchange, the server never speaks unprompted, exactly one outstanding request at a time. Every booted session opens with a HELLO.
- Length-prefixed binary frames modeled on CP/NET's header (format/version byte, function code, 16-bit payload length, raw payload, checksum) — never escaped, so COM binaries transfer without XMODEM-style encoding. Errors are in-band codes the redirector maps onto honest BDOS error returns. Timeout and bounded retry live in the redirector, so every verb is idempotent and the server holds no cursors (ADR-0003).
- Because the server sits on the other end of every request, **it sees the whole protocol** — which makes it the natural test oracle (see §9).

### 7.2.1 DECIDED: intercept at the BDOS level

The redirector hooks CP/M's function-call layer, deciding per call whether a device is local or remote (ADR-0001). Three of the five pillars — library, foundry, test oracle — need file semantics; sector-level interception would starve the server of them and multiply round trips. CP/NET validated this layer across heterogeneous hardware. Consequence: programs that bypass BDOS and bang the BIOS directly (copy-protected commercial software, low-level disk tools) don't see network drives; software distributed through the library must be BDOS-clean.

### 7.3 The server
- **Filesystem service** — exports named **volumes**, each either *shared* (read-only, any machine may bind it) or *owned* (writable, bound by at most one machine; the server refuses a second bind — ADR-0002). The per-machine drive map binds CP/M drive letters to volumes; on a diskless machine even A: is a network drive.
- **Software library / package repo** — a browsable catalog on a shared volume; "run this" fetches the real COM file to local RAM. Publishing into the library happens server-side, never through a CP/M drive.
- **ROM foundry** — machine profiles plus minting. Create a profile (make, model, hardware details) → machine ID assigned → boot media minted. For hardware the catalog can't fully predict (S-100 card mixes), the first mint is a probe build; HELLO report-backs refine the profile and the next mint is exact (ADR-0005).
- Runs as an ordinary host program; against an emulator it's just another process on the same machine.

---

## 8. Program Loading

Running a program from a network drive rides the normal CP/M load path: the CCP (our shell) loads COM files via BDOS sequential reads, the redirector routes those reads over the wire, and the CPU executes the bytes natively. Cheap rather than literally free — a deliberate consequence of ADR-0001's file-level interception, and still no special load-and-jump path.

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

## 12. Decisions & Deferrals

All formerly open questions are resolved or explicitly deferred. Decisions live in `docs/adr/`; vocabulary in `CONTEXT.md`.

**Resolved:**
- Interception layer: BDOS-level (ADR-0001).
- Volume model: shared read-only vs. owned writable, server-enforced (ADR-0002).
- Wire protocol shape: machine-initiated, one outstanding request, binary frames, idempotent verbs (ADR-0003).
- Auto-connect: config decides; no ambient probing (§6).
- Shell namespace: `/<drive>/<file>`, no fake hierarchy (ADR-0004).
- Config: link config burned locally; drive map server-authoritative, reconciled at HELLO in three tiers; config-only over the wire in v1 (ADR-0005).
- Invariant: the ROM alone must always boot to a usable local-only prompt — the wire is never load-bearing for boot.
- Minting: one ROM template per platform, copied and stamped with a fixed-address, versioned config block (magic, block version, machine ID, link config, cached drive map, checksum). No assembler on the mint path; mints are byte-deterministic and drift is a byte comparison (ADR-0006).
- Machine identity: read from the stamped block at cold boot, not from assembly-time constants. The block's cached drive map pre-populates the retained map before the wire is touched, so local-only mode shows intended bindings as dead rather than an empty map (ADR-0006).
- Operator surface: a foundry CLI (`new`, `list`, `show`, `mint`) owns every profile mutation; the running server only reads the store and writes back reconciliation results.
- Profile store: one committed JSON file per machine; machine IDs sequential from 1001 against an explicit high-water mark, never reused.
- Refine loop: probe → exact entirely on the existing HELLO payload — no new verbs, codes, or formats.
- Second emulator platform: trs80gp for the TRS-80 Model 4, taken as a checksum-pinned binary rather than built from source, with the sdltrs + socat relay as the fallback (ADR-0007).

**Deferred (deliberately, nothing downstream blocked):**
- BDOS/CCP residency vs. paging on RAM-tight machines — the emulator will answer this empirically during implementation.
- EPROM/flash media targets — per-profile catalog data, an M3 concern (ADR-0005 makes this a data problem, not an architecture problem).
- Network boot of system software (CP/NOS-style thin ROM) — post-v1; the HELLO/profile machinery already carries everything it would need.

---

## 13. Roadmap (rough)

- **M0 — Spine:** SIMH + custom BIOS + minimal server; boot banner → HELLO against a machine profile → drive map returned → one `dir` on a bound volume.
- **M1 — Filesystem:** full network-drive read path; browse + run a real COM file over the wire.
- **M2 — Boot ladder:** self-test, `/dev`, config screen, local-only fallback.
- **M3 — Foundry:** machine profiles + minting; probe build → HELLO report-back → refine → exact re-mint.
- **M4 — Library:** push/pull software catalog; homebrew distribution.
- **M5 — Real iron:** validate on a physical TRS-80 / S-100 machine.
