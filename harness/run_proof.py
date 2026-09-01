#!/usr/bin/env python3
"""RetroNix harness: bring up server + SIMH, run the ladder, assert, tear down.

Scenarios per pass, in order:
  spine           boot -> HELLO -> drive map -> dir on the bound volume
  run-com         COM files fetched over the wire execute on the CPU
  type-missing    type a text file; run a file that isn't there
  server-down     no server: machine must land at the local-only prompt
  unknown-machine server refuses an unprofiled machine ID; machine degrades
  dev-linked      `ls /dev` with the link up: devices + bound drive letters
  dev-local       `ls /dev` on a local-only boot: wire down, nothing bound
  config          `config` in both link states, wire untouched either way
  multi-binding   a two-drive map retained whole; A stays the default drive
  empty-map       a profile that binds nothing is still a live link
  bind-refusals   ls outside /dev, bind refused, bind with nobody listening
  link-recovery   live link -> server killed -> honest failure -> one `bind`
  teardown-after-failure
                  a staged restart that fails still leaves nothing behind
  two-machines    mint 1001 (Altair) + 1002 (Model 4), boot each in turn,
                  each HELLO/console shows only its own identity+bindings;
                  1002's own boot demo asserted markers-plus-honest-failure
                  (its map deliberately carries no library fixtures)
  m4-demo         Model 4 boot demo's real dispatch path against a volume
                  that does carry the fixtures: real dir/type/run success,
                  the "HELLO, WORLD FROM RETRONIX" line, oracle-backed
  probe-loop      unknown-RAM profile -> mint -> boot -> needs-remint ->
                  re-mint -> boot -> exact, flag clear
  drift           edit a profile after minting; the unchanged image still
                  serves the edited map, and needs-remint ends up set
  block-integrity a booted mint's `config` matches what the foundry stamped

Every Altair scenario mints its own boot media through server/foundry.py
(task 5.2) rather than loading a hand-copied image; the two-machines
scenario also drives trs80gp for the Model 4 leg, a second emulator target
with a ROM-owned console channel (ADR-0007) — it never types, since no
scriptable input channel survives a custom ROM (docs/research/
trs80-model4-emulation.md); it reads the boot-time auto-report off the
printer tap instead. Only one emulator process runs at a time, ever.

Success is asserted against the server's structured JSONL log (the test
oracle) plus SIMH's own expect matcher driving the console (or, for the
Model 4 leg, the printer-tap capture read the same way). Positive console
claims are always SIMH matches; the harness reads the console file only for
the two things a matcher cannot express — a marker's *absence* (no second
banner, no volume name in local-only mode) and the mid-run triggers that
drive server stop/restart. Exit code 0 iff every assertion passes.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALTAIRZ80 = ROOT / "tools/bin/altairz80"
SERVER = ROOT / "server/retronix_server.py"
FOUNDRY = ROOT / "server/foundry.py"
VOLUME = ROOT / "server/volumes/library"
BUILD = ROOT / "build"
DEFAULT_MACHINES_DIR = ROOT / "server/machines"
DEFAULT_VOLUMES_FILE = ROOT / "server/volumes.json"
MACHINE_ID = 1001
ROM_VERSION = "0.4.0"
SIM_WALL_TIMEOUT = 60  # seconds; runlimit inside the ini is the primary guard
# Scenarios that halt SIMH mid-run and sleep while the harness moves the
# server around spend most of their wall clock outside `go`, where the ini's
# runlimit does not tick. They get their own, longer wall-clock guard.
SIM_WALL_TIMEOUT_STAGED = 200

# -- trs80gp (Model 4) target -------------------------------------------
TRS80GP = ROOT / "tools/bin/trs80gp.app"
M4_MACHINE_ID = 1002
# Model 4 boot reaches the prompt ~3s (unminted/linked) to ~5.5s (link
# timeout, machine/bios_m4.asm's TOUTER=4) after launch (design.md Risks;
# docs/research/trs80-model4-emulation.md), plus the link-up boot demo's
# own paced printer output (dir + type + run, each character PDELAY-gated
# — see machine/bios_m4.asm's putc). Generous like the SIMH staged
# timeout, not tight against the measured number.
M4_WALL_TIMEOUT = 40

# Per-platform link config, ROM template, and config-block location/size:
# imported from the server rather than hand-copied. These used to be a
# harness-side "mirror" of server/foundry.py's PLATFORM_DEFAULTS and
# server/configblock.py's TEMPLATE_BLOCK_OFFSET/BLOCK_RESERVED_LEN — plain
# data, untested against the originals, and free to drift silently. The
# "drives the foundry like an operator" rationale (machines_store(),
# mint()) is about the *write* path — shelling out to server/foundry.py's
# CLI verbs rather than calling Python functions, so the harness exercises
# the same interface an operator would — and doesn't apply to reading
# static schema constants, so those are imported directly, the same
# sys.path-insert pattern server/tests/*.py already uses.
sys.path.insert(0, str(ROOT / "server"))
import configblock as cb   # noqa: E402  (after the sys.path insert above)
import foundry as fdy      # noqa: E402

PLATFORM_ALTAIR = "altair-m2sio"
PLATFORM_MODEL4 = "trs80-model4-tr1865"
assert {PLATFORM_ALTAIR, PLATFORM_MODEL4} <= set(fdy.PLATFORM_DEFAULTS), (
    "harness platform names drifted from server/foundry.py's PLATFORM_DEFAULTS: "
    f"have {sorted(fdy.PLATFORM_DEFAULTS)}")

PLATFORM_LINK_DEFAULTS = {name: dict(d["link"]) for name, d in fdy.PLATFORM_DEFAULTS.items()}
PLATFORM_ROM_TEMPLATE = {name: d["rom_template"] for name, d in fdy.PLATFORM_DEFAULTS.items()}
CFGBLK_OFFSET = {name: cb.TEMPLATE_BLOCK_OFFSET[d["platform_id"]]
                 for name, d in fdy.PLATFORM_DEFAULTS.items()}
CFGBLK_RESERVED_LEN = cb.BLOCK_RESERVED_LEN


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


TRS80GP_PROC_PATTERN = "trs80gp.app/Contents/MacOS/trs80gp"


def kill_stray_trs80gp() -> None:
    """One emulator process at a time, ever (design.md's Non-Goals). A
    blanket pkill by the app's own executable path is safe under that
    invariant and is the only teardown available: `open -a ... --args`
    detaches the real process, so nothing here ever gets its PID back
    (docs/research/trs80-model4-emulation.md's "Invocation matters")."""
    subprocess.run(["pkill", "-f", TRS80GP_PROC_PATTERN],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def trs80gp_running() -> bool:
    return subprocess.run(["pgrep", "-f", TRS80GP_PROC_PATTERN],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def mint(workdir: pathlib.Path, machine_id: int, *,
         machines_dir: pathlib.Path | None = None,
         volumes_file: pathlib.Path | None = None,
         out_dir: pathlib.Path | None = None) -> pathlib.Path:
    """Mint `machine_id`'s profile into boot media via the foundry CLI.

    Formalizes what group 3 did ad hoc (mint, then copy over
    build/retronix.bin): every scenario mints its own image into a
    scenario-scoped temp dir and points SIMH's `load` at that file, rather
    than at one shared, hand-copied binary. Defaults to the server's
    committed store (server/machines, server/volumes.json) so a scenario
    that builds no store of its own still boots a byte-faithful mint of the
    profile the server itself reads.
    """
    machines_dir = machines_dir or DEFAULT_MACHINES_DIR
    volumes_file = volumes_file or DEFAULT_VOLUMES_FILE
    out_dir = out_dir or (workdir / "mint")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(FOUNDRY), "--machines-dir", str(machines_dir),
         "--volumes-file", str(volumes_file), "mint", str(machine_id),
         "--out-dir", str(out_dir)],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"foundry mint {machine_id} failed: "
                           f"{result.stderr.strip() or result.stdout.strip()}")
    return out_dir / f"{machine_id}.bin"


def mint_default(workdir: pathlib.Path, machine_id: int = None) -> pathlib.Path:
    """Mint from the server's own committed store — the image a scenario
    wants when it starts the server with no `--machines-dir` override."""
    return mint(workdir, MACHINE_ID if machine_id is None else machine_id)


def read_profile(machines_dir: pathlib.Path, machine_id: int) -> dict | None:
    """A profile straight off disk. The harness deliberately never imports
    server/machine_store.py (it drives the store only through the foundry
    and server CLIs, like an operator would — see machines_store()'s own
    comment); this is that same convention applied to a plain read."""
    path = machines_dir / f"{machine_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def write_profile(machines_dir: pathlib.Path, profile: dict) -> None:
    """Write a profile back whole, same shape server/machine_store.py's
    save_profile uses — for a scenario that plays the operator's part of
    editing a profile directly (the drift scenario)."""
    (machines_dir / f"{profile['machine_id']}.json").write_text(
        json.dumps(profile, indent=2) + "\n")

# CFGBLK_OFFSET/CFGBLK_RESERVED_LEN are defined near the top of the file
# now, imported from server/configblock.py rather than hand-copied here —
# used below only to prove a re-mint touches nothing outside the reserved
# region (scenario_probe_loop).


def expected_entries() -> list[tuple[str, int]]:
    """What DIR should print, derived from the volume directory itself."""
    out = []
    for f in sorted(VOLUME.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            stem = f.stem.upper()[:8]
            ext = f.suffix.lstrip(".").upper()[:3]
            name = f"{stem}.{ext}" if ext else stem
            out.append((name, f.stat().st_size))
    return out


class Scenario:
    def __init__(self, name: str, workdir: pathlib.Path):
        self.name = name
        self.workdir = workdir
        self.failures: list[str] = []
        self.server: subprocess.Popen | None = None
        self.log_path = workdir / f"{name}-log.jsonl"
        self.port: int | None = None
        self.server_machines_dir: pathlib.Path | None = None
        self.server_volumes_file: pathlib.Path | None = None
        self.console_path: pathlib.Path | None = None

    def fail(self, msg: str):
        self.failures.append(msg)

    # -- processes --------------------------------------------------------

    def start_server(self, port: int, machines_dir: pathlib.Path | None = None,
                     volumes_file: pathlib.Path | None = None):
        self.port = port
        self.server_machines_dir = machines_dir
        self.server_volumes_file = volumes_file
        ready = self.workdir / f"{self.name}.ready"
        ready.unlink(missing_ok=True)
        cmd = [sys.executable, str(SERVER), "--port", str(port),
               "--log", str(self.log_path), "--ready-file", str(ready)]
        if machines_dir:
            cmd += ["--machines-dir", str(machines_dir)]
        if volumes_file:
            cmd += ["--volumes-file", str(volumes_file)]
        self.server = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        deadline = time.time() + 5
        while time.time() < deadline:
            if ready.exists():
                return
            if self.server.poll() is not None:
                raise RuntimeError(f"[{self.name}] server died at startup")
            time.sleep(0.05)
        raise RuntimeError(f"[{self.name}] server never became ready")

    def restart_server(self):
        """Retire the current lifetime and open another on the same port.

        Same port and same oracle log, so assertions span both lifetimes.
        Retiring first is what makes this safe to call from a watch: the
        successor cannot lose a race to bind a port its predecessor still
        holds, whether or not the scenario already killed it.
        """
        if self.port is None:
            raise RuntimeError(f"[{self.name}] restart before any start")
        self.teardown()
        self.start_server(self.port, self.server_machines_dir, self.server_volumes_file)

    def run_sim(self, ini_text: str, watches: list[tuple[str, object]] | None = None,
                tag: str = "", timeout: int = SIM_WALL_TIMEOUT) -> int:
        """Run one SIMH session, optionally acting on console markers.

        `watches` is an ordered list of (marker, callback). The harness tails
        the console file SIMH is writing and fires each callback the first
        time its marker appears after the previous one — that is what lets a
        scenario stop or restart the server while SIMH keeps running. Pair a
        marker with an ini that halts on the same text (an `expect` with no
        `; continue`) and a `sleep`: SIMH is then frozen while the callback
        does its work, so there is no race between the two.
        """
        stem = f"{self.name}{tag}"
        ini = self.workdir / f"{stem}.ini"
        ini.write_text(ini_text)
        console = self.workdir / f"{stem}-console.txt"
        self.console_path = console
        pending = list(watches or [])
        seen = 0
        with open(console, "w") as out:
            sim = subprocess.Popen([str(ALTAIRZ80), str(ini)],
                                   stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=subprocess.STDOUT)
            deadline = time.time() + timeout
            while True:
                try:
                    return sim.wait(timeout=0.05)
                except subprocess.TimeoutExpired:
                    pass
                while pending:
                    marker, action = pending[0]
                    hit = self.console_text().find(marker, seen)
                    if hit < 0:
                        break
                    seen = hit + len(marker)
                    pending.pop(0)
                    action()
                if time.time() >= deadline:
                    sim.kill()
                    sim.wait()
                    self.fail("SIMH hit the wall-clock timeout and was killed")
                    return -1

    def run_linked_sim(self, ini_text: str, **kw) -> int:
        """run_sim for a session whose boot HELLO must reach the server.

        Roughly once in a hundred attached sessions AltairZ80's outbound
        `connect=` never completes: the server logs its `listening` line and
        nothing else, the machine exhausts its bounded HELLO retries, and the
        prompt comes up local-only. Both ends behaved — not one byte crossed
        the wire, so the fault is the emulator's socket. When the oracle shows
        exactly that signature (no record at all for this machine), the
        session is run once more against the same server, keeping the first
        attempt's console under a `-noconnect` name. The retry prints, so it
        can never turn a real regression into a silent pass.
        """
        mark = len(self.failures)
        code = self.run_sim(ini_text, **kw)
        if any(r.get("machine_id") == MACHINE_ID for r in self.records()):
            return code
        print(f"         ! {self.name}: the emulator never opened the wire; "
              "retrying the session once")
        self.console_path.rename(
            self.console_path.with_name(f"{self.console_path.stem}-noconnect.txt"))
        del self.failures[mark:]
        return self.run_sim(ini_text, **kw)

    def run_m4(self, image: pathlib.Path, wire_port: int,
              timeout: int = M4_WALL_TIMEOUT) -> int:
        """Boot a minted Model 4 image under trs80gp and capture its
        printer-tap console. Parallel to run_sim, for the second emulator
        target (task 5.1).

        OBSERVE-ONLY, per the resolved open question in design.md: no
        scriptable input channel exists under a custom ROM
        (docs/research/trs80-model4-emulation.md, task 1.1 — `-ip` and
        `-rB` are both dead), so this never types. The template's own
        boot-time auto-report (machine/bios_m4.asm's `bootrep`, printed
        BOOTREPS=2 times) is the only evidence, and this method just reads
        it off the printer tap until the prompt appears, the same way
        run_sim reads SIMH's console file.

        `wire_port` is the RetroNix server's own listening port — trs80gp
        dials out to it with `-r`, exactly parallel to SIMH's `attach
        m2sio1 connect=`. The printer tap (`-p`) is a second, plain byte-
        capture socket this method owns. Both must be listening before the
        emulator launches, since trs80gp dials out to each end (verified:
        the harness listens first, trs80gp connects — see the research
        doc's "Invocation matters" note for why `open -a ... --args` is
        required instead of exec'ing the binary directly).

        Teardown (kill the detached process, close the socket) always
        happens, success or failure, and is verified by re-checking that
        no trs80gp process survives — the design's "one emulator process
        at a time, ever" makes a blanket pkill safe rather than needing to
        track a child PID `open` never hands back.
        """
        if not TRS80GP.exists():
            self.fail(f"tools/bin/trs80gp.app is missing — run "
                     "tools/fetch-trs80gp.sh to fetch the pinned binary")
            return 2

        printer_port = free_port()
        console = self.workdir / f"{self.name}-m4-console.txt"
        self.console_path = console
        console.write_bytes(b"")

        kill_stray_trs80gp()  # defensive: a prior crashed run left nothing
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", printer_port))
        listener.listen(1)
        cmd = ["open", "-a", str(TRS80GP), "--args",
               "-m4", "-dx", "-hx", "-rom", str(image.resolve()),
               "-r", f":{wire_port}", "-p", f":{printer_port}"]
        code = 0
        try:
            try:
                subprocess.run(cmd, check=True, timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                self.fail(f"[{self.name}] `open -a trs80gp` did not return")
                return 5
            except subprocess.CalledProcessError as e:
                self.fail(f"[{self.name}] failed to launch trs80gp: {e}")
                return 6

            listener.settimeout(15)
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                self.fail(f"[{self.name}] the printer tap never connected — "
                         "trs80gp did not come up")
                return 3

            with conn:
                conn.settimeout(0.5)
                data = bytearray()
                deadline = time.time() + timeout
                prompt_at = None
                with open(console, "wb") as out:
                    while time.time() < deadline:
                        try:
                            chunk = conn.recv(4096)
                        except socket.timeout:
                            continue
                        if not chunk:
                            break  # trs80gp closed the tap
                        data += chunk
                        out.write(chunk)
                        out.flush()
                        if b"retronix> " in data:
                            if prompt_at is None:
                                prompt_at = time.time()
                            # a grace period past the first sighting: the
                            # tap's connect race can still drop the very
                            # first BOOTREPS repetition even with per-
                            # character pacing (research doc), so give the
                            # second, guaranteed-complete one time to land
                            elif time.time() - prompt_at > 2.0:
                                break
                if prompt_at is None:
                    self.fail(f"[{self.name}] never reached the prompt within "
                             f"{timeout}s ({len(data)} bytes captured)")
                    code = 4
        finally:
            listener.close()
            kill_stray_trs80gp()
            deadline = time.time() + 5
            while trs80gp_running() and time.time() < deadline:
                time.sleep(0.2)
            if trs80gp_running():
                self.fail(f"[{self.name}] a trs80gp process survived teardown")
        return code

    def teardown(self):
        """Deterministic: kill exactly the processes we started.

        Whichever server lifetime is current gets killed — a scenario that
        stopped and restarted the server leaves no more behind than one that
        never touched it, on success and on failure alike.
        """
        if self.server:
            self.server.terminate()
            try:
                self.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait()
            self.server = None

    # -- console ----------------------------------------------------------

    def console_text(self) -> str:
        """The console SIMH wrote, byte for byte.

        Read as bytes and decoded by hand: text mode would fold the CR LF the
        ROM actually emits into a bare LF, and some markers need the pair to
        tell one message from another that starts the same way.
        """
        if not self.console_path or not self.console_path.exists():
            return ""
        return self.console_path.read_bytes().decode("utf-8", errors="replace")

    # -- oracle -----------------------------------------------------------

    def records(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]


def base_ini(port: int | None, image: pathlib.Path, runlimit: int = 30) -> str:
    lines = [
        "set cpu 8080",
        "set ptr disabled",
        "set ptp disabled",
        "set m2sio1 enabled",
        "set m2sio1 dtr",
    ]
    if port is not None:
        lines.append(f"attach m2sio1 connect=127.0.0.1:{port};notelnet")
    lines += [
        f"load {image} 0",
        f"runlimit {runlimit} seconds",
    ]
    return "\n".join(lines) + "\n"


def scenario_spine(workdir: pathlib.Path) -> Scenario:
    sc = Scenario("spine", workdir)
    entries = expected_entries()
    last_line = f"{entries[-1][0]} {entries[-1][1]}"
    port = free_port()
    image = mint_default(workdir)
    try:
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port, image) + "\n".join([
            'expect "retronix> " send "dir\\r"; continue',
            f'expect "{last_line}" exit 0',
            "go 0",
            "exit 1",
        ]) + "\n")
        if code != 0:
            sc.fail(f"sim exited {code}: boot->HELLO->dir did not complete")
        recs = [r for r in sc.records() if r.get("machine_id") == MACHINE_ID]
        hello = [r for r in recs if r["verb"] == "hello"]
        if len(hello) != 1 or hello[0]["result"] != "ok":
            sc.fail(f"oracle: expected one ok hello, got {hello}")
        else:
            inv = hello[0].get("inventory", {})
            for field in ("cpu", "ram_kb", "serial_up"):
                if field not in inv:
                    sc.fail(f"oracle: hello inventory missing {field}")
            if hello[0].get("drive_map") != {"A": "library"}:
                sc.fail(f"oracle: unexpected drive map {hello[0].get('drive_map')}")
        dirs = [r for r in recs if r["verb"] == "dir"]
        if len(dirs) != 1 or dirs[0]["result"] != "ok":
            sc.fail(f"oracle: expected one ok dir, got {dirs}")
        elif dirs[0]["entry_count"] != len(entries):
            sc.fail(f"oracle: dir count {dirs[0]['entry_count']} != {len(entries)}")
    finally:
        sc.teardown()
    return sc


def file_size(name: str) -> int:
    return (VOLUME / name).stat().st_size


def assert_tiling(sc: Scenario, name: str, size: int):
    """The FREAD offsets for `name` must tile the file exactly."""
    reads = [r for r in sc.records()
             if r["verb"] == "fread" and r.get("file") == name]
    if any(r["result"] != "ok" for r in reads):
        sc.fail(f"oracle: non-ok fread for {name}: {reads}")
        return
    offsets = [r["offset"] for r in reads]
    if offsets != sorted(offsets) or (offsets and offsets[0] != 0):
        sc.fail(f"oracle: {name} offsets don't start at 0 ascending: {offsets}")
        return
    expect_off = 0
    for r in reads:
        if r["offset"] != expect_off:
            sc.fail(f"oracle: {name} offset gap at {r['offset']} (expected {expect_off})")
            return
        expect_off += r["actual"]
    if expect_off != size:
        sc.fail(f"oracle: {name} reads total {expect_off}, file is {size}")


def scenario_run_com(workdir: pathlib.Path) -> Scenario:
    """The payoff: COM files fetched over the wire execute on the CPU."""
    sc = Scenario("run-com", workdir)
    port = free_port()
    image = mint_default(workdir)
    try:
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port, image) + "\n".join([
            'expect "retronix> " send "run hello.com\\r"; continue',
            'expect "WORLD FROM RETRONIX" send "\\rrun big.com\\r"; continue',
            'expect "BIG OK" exit 0',
            "go 0",
            "exit 1",
        ]) + "\n")
        if code != 0:
            sc.fail(f"sim exited {code}: COM programs didn't run")
        assert_tiling(sc, "HELLO.COM", file_size("HELLO.COM"))
        assert_tiling(sc, "BIG.COM", file_size("BIG.COM"))
    finally:
        sc.teardown()
    return sc


def scenario_type_missing(workdir: pathlib.Path) -> Scenario:
    sc = Scenario("type-missing", workdir)
    port = free_port()
    image = mint_default(workdir)
    try:
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port, image) + "\n".join([
            'expect "retronix> " send "type about.txt\\r"; continue',
            'expect "M0 fixture" send "\\rrun nope.com\\r"; continue',
            'expect "file not found" exit 0',
            "go 0",
            "exit 1",
        ]) + "\n")
        if code != 0:
            sc.fail(f"sim exited {code}: type/missing-file flow failed")
        types = [r for r in sc.records()
                 if r["verb"] == "fread" and r.get("file") == "ABOUT.TXT"]
        if not types or types[0]["result"] != "ok":
            sc.fail(f"oracle: expected ok ABOUT.TXT read, got {types}")
        missing = [r for r in sc.records()
                   if r["verb"] == "fread" and r.get("file") == "NOPE.COM"]
        if not missing or missing[-1]["result"] != "file-not-found":
            sc.fail(f"oracle: expected file-not-found for NOPE.COM, got {missing}")
    finally:
        sc.teardown()
    return sc


def scenario_server_down(workdir: pathlib.Path) -> Scenario:
    sc = Scenario("server-down", workdir)
    image = mint_default(workdir)
    try:
        code = sc.run_sim(base_ini(None, image) + "\n".join([
            'expect "local-only mode" exit 0',
            "go 0",
            "exit 1",
        ]) + "\n")
        if code != 0:
            sc.fail(f"sim exited {code}: machine never reached local-only mode")
    finally:
        sc.teardown()
    return sc


def scenario_unknown_machine(workdir: pathlib.Path) -> Scenario:
    sc = Scenario("unknown-machine", workdir)
    machines_dir, volumes_file, _ = machines_store(
        workdir, "unknown", {"A": "library"}, machine_id=4242)
    # The booted image still carries machine identity 1001 (minted from the
    # default store, which has that profile) -- the server it dials is
    # pointed at a *different* store that lacks 1001, which is the refusal
    # this scenario exercises.
    image = mint_default(workdir)
    port = free_port()
    try:
        sc.start_server(port, machines_dir=machines_dir, volumes_file=volumes_file)
        code = sc.run_linked_sim(base_ini(port, image) + "\n".join([
            'expect "local-only mode" exit 0',
            "go 0",
            "exit 1",
        ]) + "\n")
        if code != 0:
            sc.fail(f"sim exited {code}: refused machine didn't degrade cleanly")
        hellos = [r for r in sc.records() if r["verb"] == "hello"]
        if not hellos or hellos[0]["result"] != "unknown-machine":
            sc.fail(f"oracle: expected unknown-machine refusal, got {hellos}")
    finally:
        sc.teardown()
    return sc


# ---------------------------------------------------------------- M2 rungs
#
# `ls /dev` and `config` read the boot self-test and the retained drive map
# and touch neither wire nor disk. The console is therefore the only place
# their output can be asserted, and the oracle log is the evidence that they
# produced it without asking anyone. Markers are short stable substrings:
# the content of a /dev line is normative, its column layout is not.

DEV_CPU = "cpu      8080"
DEV_RAM = "ram      63 KB"   # what the self-test finds on this emulator
DEV_CONSOLE = "console  sio, status port 10h"
DEV_WIRE_UP = "data port 13h, link up"
DEV_WIRE_DOWN = "data port 13h, link down"
LINKED_BOOT = "link up: drive A: bound"
# For scenarios that need a linked boot: if the machine lands local-only the
# run can never pass, so stop there with a distinct code instead of running
# out the clock on expects that will never match.
LOCAL_ONLY_BAILOUT = 'expect "local-only mode" exit 3'


def never_linked(code: int) -> str:
    """Spell out SIMH's bailout code where a scenario reports its failure."""
    return " (the boot HELLO never linked)" if code == 3 else ""


class WireWatch:
    """Proof that a local command sent nothing while it ran.

    A local command's output can only be asserted on the console, so the
    oracle's job is the negative: the record count taken with SIMH frozen at
    the linked prompt must still be the count when the run is over. Pass
    `take` as a run_sim watch on the boot message; call `check` afterwards.
    """

    def __init__(self, sc: Scenario, what: str):
        self.sc = sc
        self.what = what
        self.before: int | None = None
        self.after: int | None = None

    def take(self):
        self.before = len(self.sc.records())

    def seal(self):
        """Close the window early, when wire work legitimately follows."""
        self.after = len(self.sc.records())

    def check(self):
        if self.before is None:
            self.sc.fail("the machine never reported a bound drive at boot")
            return
        after = self.after if self.after is not None else len(self.sc.records())
        gained = after - self.before
        if gained:
            self.sc.fail(f"oracle: {self.what} put {gained} record(s) on the "
                         "wire; it must send nothing")


def scenario_dev_linked(workdir: pathlib.Path) -> Scenario:
    """`ls /dev` with the link up: devices, wire up, the bound letter."""
    sc = Scenario("dev-linked", workdir)
    port = free_port()
    image = mint_default(workdir)
    wire = WireWatch(sc, "ls /dev")
    try:
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port, image, runlimit=60) + "\n".join([
            # Halt on the boot HELLO's own message so the before-picture of
            # the oracle is taken with SIMH frozen at the prompt. If the
            # machine lands local-only instead, bail out at once rather than
            # letting a scenario that can no longer pass eat its wall clock.
            LOCAL_ONLY_BAILOUT,
            f'expect "{LINKED_BOOT}"',
            "go 0",
            "sleep 2",
            'send "ls /dev\\r"',
            f'expect "{DEV_CPU}"; continue',
            f'expect "{DEV_RAM}"; continue',
            f'expect "{DEV_CONSOLE}"; continue',
            f'expect "{DEV_WIRE_UP}"; continue',
            'expect "a: library"; continue',
            'expect "b: unbound"; continue',
            'expect "p: unbound" exit 0',
            "cont",
            "exit 1",
        ]) + "\n",
            watches=[(LINKED_BOOT, wire.take)],
            timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: ls /dev didn't show the inventory and bindings"
                    + never_linked(code))
        wire.check()
    finally:
        sc.teardown()
    return sc


def scenario_dev_local(workdir: pathlib.Path) -> Scenario:
    """`ls /dev` on a local-only boot: wire down, baked bindings dead.

    Since M3, the config block preloads DMAP/MAPCNT before HELLO is ever
    attempted (design.md D6). A local-only boot never reaches HELLO to
    overwrite that preload, so machine 1001's baked binding (A: library)
    is still there -- honestly reported as dead (machine/bios.asm's pdent),
    not hidden as "unbound". This replaces the pre-M3 contract this
    scenario used to assert (local-only == no bindings at all).
    """
    sc = Scenario("dev-local", workdir)
    image = mint_default(workdir)
    try:
        code = sc.run_sim(base_ini(None, image, runlimit=60) + "\n".join([
            'expect "local-only mode"',
            "go 0",
            "sleep 1",
            'send "ls /dev\\r"',
            f'expect "{DEV_CPU}"; continue',
            f'expect "{DEV_CONSOLE}"; continue',
            f'expect "{DEV_WIRE_DOWN}"; continue',
            'expect "a: library (dead)"; continue',
            'expect "b: unbound"; continue',
            'expect "p: unbound" exit 0',
            "cont",
            "exit 1",
        ]) + "\n", timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: local-only /dev didn't report the wire down"
                    " and the baked binding as dead")
        # A matcher proves presence, never absence: the baked binding may
        # only ever appear marked dead, never as a live claim on a volume.
        text = sc.console_text()
        live = text.count("a: library") - text.count("a: library (dead)")
        if live > 0:
            sc.fail("console: a baked binding claims a live volume in local-only mode")
        if sc.records():
            sc.fail(f"oracle: a local-only boot logged {len(sc.records())} record(s)")
    finally:
        sc.teardown()
    return sc


def scenario_config(workdir: pathlib.Path) -> Scenario:
    """`config` on both rungs of the ladder: same facts, honest link state."""
    sc = Scenario("config", workdir)
    wire = WireWatch(sc, "config")
    burned_in = [
        f'expect "machine id:  {MACHINE_ID}"; continue',
        f'expect "rom version: {ROM_VERSION}"; continue',
        'expect "link config: wire acia, ports 12h/13h"; continue',
    ]
    try:
        image = mint_default(workdir)
        port = free_port()
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port, image, runlimit=60) + "\n".join([
            LOCAL_ONLY_BAILOUT,
            f'expect "{LINKED_BOOT}"',
            "go 0",
            "sleep 2",
            'send "config\\r"',
        ] + burned_in + [
            'expect "link state:  up"; continue',
            'expect "the server profile owns it"; continue',
            'expect "a: library" exit 0',
            "cont",
            "exit 1",
        ]) + "\n",
            watches=[(LINKED_BOOT, wire.take)],
            tag="-linked", timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: config with the link up was incomplete"
                    + never_linked(code))

        sc.teardown()
        # Same minted image, no server: the block's baked binding preloads
        # DMAP before HELLO is ever attempted, and a local-only boot never
        # reaches a HELLO to overwrite it (design.md D6). The spec-correct
        # M3 report is the binding shown dead, not the pre-M3 "no network
        # bindings" (that read was only ever true for an *empty* map).
        code = sc.run_sim(base_ini(None, image, runlimit=60) + "\n".join([
            'expect "local-only mode"',
            "go 0",
            "sleep 1",
            'send "config\\r"',
        ] + burned_in + [
            'expect "link state:  local-only mode"; continue',
            'expect "the server profile owns it"; continue',
            'expect "a: library (dead)" exit 0',
            "cont",
            "exit 1",
        ]) + "\n", tag="-local", timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: config in local-only mode was incomplete")
        # Read-only, on both rungs: the boot HELLO is the only wire traffic
        # either leg is allowed to have produced.
        wire.check()
    finally:
        sc.teardown()
    return sc


def profile_json(machine_id: int, drive_map: dict, make: str = "MITS",
                 model: str = "test", platform: str = PLATFORM_ALTAIR,
                 declared: dict | None = None) -> dict:
    """One machine profile, schema-v1 shaped (server/machine_store.py)."""
    return {
        "schema": 1,
        "machine_id": machine_id,
        "identity": {"make": make, "model": model, "notes": ""},
        "platform": platform,
        "rom_template": PLATFORM_ROM_TEMPLATE[platform],
        "link": dict(PLATFORM_LINK_DEFAULTS[platform]),
        "drive_map": drive_map,
        "state": "probe",
        "hardware": {
            "declared": dict(declared or {"cpu": 0, "ram_kb": 0, "console": 0}),
            "observed": {"cpu": None, "ram_kb": None, "console": None,
                         "rom_version": None, "last_seen": None},
        },
        "mint": {"block_checksum": None, "block_sha256": None,
                 "minted_at": None, "rom_version": None, "stamped": None},
        "needs_remint": False,
    }


def machines_store(workdir: pathlib.Path, name: str, drive_map: dict,
                   volumes: dict | None = None,
                   machine_id: int = MACHINE_ID,
                   platform: str = PLATFORM_ALTAIR,
                   declared: dict | None = None,
                   ) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Write a one-off machines dir + volumes file so a scenario can shape
    the drive map — the harness-side mirror of server/machine_store.py's
    per-machine store, now that the server reads `--machines-dir` rather
    than a single combined `--config` file (design.md's migration plan) —
    and mint an image from that same store, so the boot media's baked
    identity/link/map always matches the profile the server will answer
    HELLO from. Returns (machines_dir, volumes_file, image_path)."""
    machines_dir = workdir / f"{name}-machines"
    machines_dir.mkdir(exist_ok=True)
    (machines_dir / f"{machine_id}.json").write_text(
        json.dumps(profile_json(machine_id, drive_map, platform=platform,
                                declared=declared)))
    vols = {"library": {"path": str(VOLUME), "kind": "shared"}}
    vols.update(volumes or {})
    volumes_file = workdir / f"{name}-volumes.json"
    volumes_file.write_text(json.dumps(vols))
    image = mint(workdir, machine_id, machines_dir=machines_dir,
                volumes_file=volumes_file, out_dir=workdir / f"{name}-mint")
    return machines_dir, volumes_file, image


def scratch_volume(workdir: pathlib.Path) -> pathlib.Path:
    """A second volume, so a profile can bind more than one drive letter."""
    vol = workdir / "scratch"
    vol.mkdir(exist_ok=True)
    (vol / "NOTES.TXT").write_text("second volume\r\n")
    return vol


def scenario_multi_binding(workdir: pathlib.Path) -> Scenario:
    """A map wider than one letter: all of it retained, A still the default."""
    sc = Scenario("multi-binding", workdir)
    entries = expected_entries()
    last_line = f"{entries[-1][0]} {entries[-1][1]}"
    scratch = scratch_volume(workdir)
    machines_dir, volumes_file, image = machines_store(
        workdir, "multi", {"A": "library", "C": "scratch"},
        volumes={"scratch": {"path": str(scratch), "kind": "private"}})
    port = free_port()
    wire = WireWatch(sc, "config and ls /dev")
    try:
        sc.start_server(port, machines_dir=machines_dir, volumes_file=volumes_file)
        code = sc.run_linked_sim(base_ini(port, image, runlimit=90) + "\n".join([
            LOCAL_ONLY_BAILOUT,
            f'expect "{LINKED_BOOT}"',
            "go 0",
            "sleep 2",
            # config reports every binding the response carried, not just
            # the one the shell happens to address.
            'send "config\\r"',
            'expect "link state:  up"; continue',
            'expect "a: library"; continue',
            'expect "c: scratch"',
            "cont",
            # /dev tells the same story letter by letter, and the letters
            # between the two bindings are honestly unbound.
            'send "ls /dev\\r"',
            f'expect "{DEV_WIRE_UP}"; continue',
            'expect "a: library"; continue',
            'expect "b: unbound"; continue',
            'expect "c: scratch"; continue',
            'expect "p: unbound"',
            "cont",
            # The wider map does not move the default drive.
            'send "dir\\r"',
            f'expect "{last_line}"',
            "cont",
            # And a bind on a live link re-runs HELLO and adopts the map
            # again — no reboot, no banner.
            'send "bind\\r"',
            'expect "link up - bound drives:"; continue',
            'expect "c: scratch" exit 0',
            "cont",
            "exit 1",
        ]) + "\n",
            watches=[(LINKED_BOOT, wire.take), ("p: unbound", wire.seal)],
            timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: the two-drive map wasn't retained end to end"
                    + never_linked(code))
        wire.check()
        if sc.console_text().count("RetroNix ROM") != 1:
            sc.fail("console: bind on a live link reprinted the boot banner")
        both = {"A": "library", "C": "scratch"}
        hellos = [r for r in sc.records() if r["verb"] == "hello"]
        if len(hellos) != 2 or any(h["result"] != "ok" for h in hellos):
            sc.fail(f"oracle: expected two ok hellos (boot and re-bind), got {hellos}")
        elif any(h.get("drive_map") != both for h in hellos):
            sc.fail(f"oracle: map not carried whole: {[h.get('drive_map') for h in hellos]}")
        dirs = [r for r in sc.records() if r["verb"] == "dir"]
        if len(dirs) != 1 or dirs[0].get("drive") != "A" or dirs[0].get("volume") != "library":
            sc.fail(f"oracle: dir should still address the first bound drive, got {dirs}")
        elif dirs[0]["entry_count"] != len(entries):
            sc.fail(f"oracle: dir count {dirs[0]['entry_count']} != {len(entries)}")
    finally:
        sc.teardown()
    return sc


def scenario_empty_map(workdir: pathlib.Path) -> Scenario:
    """A profile that binds nothing: still linked, and says so plainly."""
    sc = Scenario("empty-map", workdir)
    machines_dir, volumes_file, image = machines_store(workdir, "empty", {})
    port = free_port()
    try:
        sc.start_server(port, machines_dir=machines_dir, volumes_file=volumes_file)
        code = sc.run_linked_sim(base_ini(port, image, runlimit=60) + "\n".join([
            'expect "link up: no network drives bound"',
            "go 0",
            "sleep 2",
            'send "config\\r"',
            'expect "link state:  up"; continue',
            'expect "no network bindings"',
            "cont",
            'send "ls /dev\\r"',
            f'expect "{DEV_WIRE_UP}"; continue',
            'expect "a: unbound"; continue',
            'expect "p: unbound" exit 0',
            "cont",
            "exit 1",
        ]) + "\n", timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: an empty map didn't read as a live link")
        # An empty map is a live link, not Local-Only Mode. Absence again, so
        # the console file rather than the matcher.
        text = sc.console_text()
        if "local-only" in text:
            sc.fail("console: a bound-nothing link claimed local-only mode")
        if "library" in text:
            sc.fail("console: a drive letter claims a volume the map never bound")
        hellos = [r for r in sc.records() if r["verb"] == "hello"]
        if len(hellos) != 1 or hellos[0]["result"] != "ok" or hellos[0].get("drive_map"):
            sc.fail(f"oracle: expected one ok hello binding nothing, got {hellos}")
    finally:
        sc.teardown()
    return sc


def scenario_bind_refusals(workdir: pathlib.Path) -> Scenario:
    """The paths where the ladder does not climb, and says why."""
    sc = Scenario("bind-refusals", workdir)
    # A profile for somebody else: the server is reachable and answers, and
    # the answer is no — which must not be reported as silence.
    machines_dir, volumes_file, _ = machines_store(
        workdir, "someone-else", {"A": "library"}, machine_id=4242)
    # The booted image carries identity 1001 (this scenario's whole point
    # is a server that answers but has no profile for it); mint that from
    # the default store, same as scenario_unknown_machine.
    image = mint_default(workdir)
    port = free_port()
    hellos: list[int] = []

    def count() -> int:
        return sum(1 for r in sc.records() if r["verb"] == "hello")

    def refused_then_kill():
        hellos.append(count())   # the record is written before the machine
        sc.teardown()            # can print, so count it before killing
    try:
        sc.start_server(port, machines_dir=machines_dir, volumes_file=volumes_file)
        code = sc.run_sim(base_ini(port, image, runlimit=150) + "\n".join([
            'expect "local-only mode"',
            "go 0",
            "sleep 1",
            # Only /dev is listable, and any other path is told so.
            'send "ls /usr\\r"',
            'expect "only /dev is listable in this ROM version"',
            "cont",
            # Refused, not timed out: the server's own answer, on the console.
            'send "bind\\r"',
            'expect "bind refused: the server has no profile for this machine id"',
            "cont",
            # SIMH is frozen while the server goes away for good.
            "sleep 3",
            # Now there is nobody, and the machine must say that instead,
            # bounded, and come back to a usable prompt.
            'send "bind\\r"',
            'expect "bind failed: no response from the server"; continue',
            'expect "no server link - local-only mode"; continue',
            'expect "retronix> " exit 0',
            "cont",
            "exit 1",
        ]) + "\n",
            watches=[("only /dev is listable", lambda: hellos.append(count())),
                     ("bind refused", refused_then_kill)],
            timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: a refusal or a silence wasn't reported honestly")
        if sc.console_text().count("RetroNix ROM") != 1:
            sc.fail("console: a failed bind rebooted the machine")
        # The refusal must be the server's answer to *this* bind, so count
        # HELLO records either side of it rather than trusting a total: the
        # boot HELLO against the same refusing server is a separate proof
        # (scenario_unknown_machine) and must not be load-bearing here.
        if len(hellos) != 2:
            sc.fail("the run never reached the bind refusal")
        elif hellos[1] - hellos[0] != 1:
            sc.fail(f"oracle: bind should have logged exactly one HELLO, "
                    f"logged {hellos[1] - hellos[0]}")
        refusals = [r["result"] for r in sc.records() if r["verb"] == "hello"]
        if not refusals or any(r != "unknown-machine" for r in refusals):
            sc.fail(f"oracle: every HELLO here should be refused, got {refusals}")
    finally:
        sc.teardown()
    return sc


def scenario_teardown_after_failure(workdir: pathlib.Path) -> Scenario:
    """The teardown guarantee, proven on the path that actually risks it.

    Two consecutive green runs show nothing leaks when scenarios pass. This
    one stages a restart and then *fails* — the case where a half-finished
    scenario could strand the second server lifetime — and passes only when
    the doomed run leaves no process alive and no socket on its port.
    """
    sc = Scenario("teardown-after-failure", workdir)
    doomed = Scenario("doomed-restart", workdir)
    port = free_port()
    image = mint_default(workdir)
    survivor = None
    try:
        doomed.start_server(port)
        code = doomed.run_linked_sim(base_ini(port, image, runlimit=15) + "\n".join([
            LOCAL_ONLY_BAILOUT,
            f'expect "{LINKED_BOOT}"',
            "go 0",
            # The staged restart lands during this freeze, and then the run
            # gives up with the second server lifetime still listening.
            "sleep 3",
            "exit 1",
        ]) + "\n",
            watches=[(LINKED_BOOT, doomed.restart_server)],
            timeout=60)
        if code == 0:
            sc.fail("the doomed run was supposed to fail and did not")
        survivor = doomed.server
        if survivor is None:
            sc.fail("the staged restart never happened, so nothing was proven")
    finally:
        doomed.teardown()
        sc.teardown()
    if survivor is not None and survivor.poll() is None:
        sc.fail("teardown left the restarted server running after a failed run")
    # Probe the port the way the server itself binds it (SO_REUSEADDR): that
    # steps over the TIME_WAIT a closed connection leaves behind, which is not
    # a leak, while still refusing if a listener is genuinely still up.
    try:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
            probe.listen(1)
    except OSError as e:
        sc.fail(f"teardown left a listener bound on port {port}: {e}")
    return sc


# ------------------------------------------------------- M2: link recovery
#
# Task 3.1, answered by measurement rather than by reading the source, and
# the answer took three parts.
#
# Does AltairZ80's M2SIO re-establish its outbound `connect=` after the peer
# closes? **Yes.** With `set m2sio1 debug=connect` the SIMH log shows
# `tmxr_poll_conn() - establishing outgoing connection` retried on a backoff
# for as long as the listener is gone, and `... established` the moment a
# server returns on the same port. Nothing in the harness has to re-attach.
#
# Second: when the server dies, the MC6850 model latches DCD inactive
# (`s100_2sio.c`: `dcdl`, cleared only by a master reset or a data-port
# read), so the machine keeps reading no carrier even after SIMH has quietly
# re-dialled. That is what `bind` has to see through.
#
# Third, and the one that actually broke recovery: bytes the machine wrote
# into the dead ACIA during the failing `dir` sat in SIMH's transmit buffer
# and were flushed the instant the socket came back — arriving ahead of the
# re-bind HELLO and wedging the server mid-frame, so `bind` timed out against
# a server that was up and listening. Both are fixed in machine/bios.asm:
# `wtx` now gates transmission on carrier as well as TDRE, so a dead link
# swallows no bytes and there is nothing stale to flush; and `bind` clears
# the latched carrier loss with a data-port read instead of a master reset,
# then waits bounded for the re-dial rather than tearing down the connection
# SIMH just made.
#
# So this scenario runs the requirement's real shape: a live link, a server
# killed underneath it, an honest failure, the server back on the same port
# and the same oracle log, and one `bind` — no reboot — to get the wire back.


def scenario_link_recovery(workdir: pathlib.Path) -> Scenario:
    """Live link -> server dies -> honest failure -> server back -> `bind`."""
    sc = Scenario("link-recovery", workdir)
    entries = expected_entries()
    last_line = f"{entries[-1][0]} {entries[-1][1]}"
    port = free_port()
    image = mint_default(workdir)
    try:
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port, image, runlimit=150) + "\n".join([
            LOCAL_ONLY_BAILOUT,
            # A working wire first: whatever fails later really was a live
            # link, not a boot that never came up.
            'expect "retronix> " send "dir\\r"; continue',
            f'expect "{last_line}"',
            "go 0",
            # SIMH is frozen here while the harness takes the server away.
            "sleep 3",
            # Nothing on this wire is unprompted (ADR-0003), so the machine
            # learns the link is gone only by asking and being met with
            # silence — and it must say so rather than invent a listing.
            'send "dir\\r"',
            'expect "wire error: no response"',
            "cont",
            # A binding the retained map still holds, with the link gone, is
            # dead — named, not hidden, and distinguishable from a letter
            # that was never bound at all. No wire is touched to say so.
            'send "ls /dev\\r"',
            f'expect "{DEV_WIRE_DOWN}"; continue',
            'expect "a: library (dead)"; continue',
            'expect "b: unbound"',
            "cont",
            # Frozen again while the server comes back on the same port,
            # writing to the same oracle log as the lifetime it replaces.
            "sleep 4",
            # One command, no reboot. The bounded carrier wait inside `bind`
            # is what costs the wall clock here — around thirteen seconds.
            'send "bind\\r"',
            'expect "link up - bound drives:"; continue',
            'expect "a: library"',
            "cont",
            # And the wire works exactly as it did before the drop.
            'send "dir\\r"',
            f'expect "{last_line}" exit 0',
            "cont",
            "exit 1",
        ]) + "\n",
            watches=[(last_line, sc.teardown),
                     ("wire error: no response", sc.restart_server)],
            timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: bind did not bring the dead link back"
                    + never_linked(code))
        # Recovery without a reboot. A matcher cannot assert absence, so the
        # banner count is read off the console SIMH wrote.
        banners = sc.console_text().count("RetroNix ROM")
        if banners != 1:
            sc.fail(f"console: {banners} boot banners — the prompt was restarted")
        # One log, two server lifetimes, in order: each `listening` record
        # opens a lifetime, and each lifetime must carry a whole exchange.
        recs = sc.records()
        listens = [i for i, r in enumerate(recs) if r["verb"] == "listening"]
        if len(listens) != 2 or listens[0] != 0:
            sc.fail("oracle: expected one log spanning two server lifetimes, got "
                    f"{[r['verb'] for r in recs]}")
        else:
            halves = (("before the restart", recs[listens[0]:listens[1]]),
                      ("after the restart", recs[listens[1]:]))
            for label, half in halves:
                mine = [r for r in half if r.get("machine_id") == MACHINE_ID]
                shape = [(r["verb"], r["result"]) for r in mine]
                if shape != [("hello", "ok"), ("dir", "ok")]:
                    sc.fail(f"oracle: {label} expected an ok hello then an ok "
                            f"dir, got {shape}")
                    continue
                if mine[0].get("drive_map") != {"A": "library"}:
                    sc.fail(f"oracle: {label} drive map is "
                            f"{mine[0].get('drive_map')}")
                if mine[1]["entry_count"] != len(entries):
                    sc.fail(f"oracle: {label} dir count {mine[1]['entry_count']} "
                            f"!= {len(entries)}")
    finally:
        sc.teardown()
    return sc


# ------------------------------------------------------------- M3: foundry
#
# Every scenario below mints its own boot media (task 5.2) rather than
# relying on a hand-copied image, and the oracle log remains the authority
# per PRD §9 — console text backs it up but never stands alone, except on
# the Model 4 where the console is the only channel that exists at all
# (design.md's resolved open question: OBSERVE-ONLY, no scriptable input).


def scenario_two_machines(workdir: pathlib.Path) -> Scenario:
    """Two machines of different makes, minted with different drive maps,
    booted in turn against one server: each HELLO carries only its own
    machine id, and neither console shows the other's bindings (task 5.3).

    Sequential by construction — SIMH for 1001, then trs80gp for 1002 —
    which is also the "one emulator process at a time" the design commits
    to (Non-Goals: "Running both emulators at once").
    """
    sc = Scenario("two-machines", workdir)
    scratch = scratch_volume(workdir)
    machines_dir = workdir / "two-machines-machines"
    machines_dir.mkdir(exist_ok=True)
    volumes_file = workdir / "two-machines-volumes.json"
    volumes_file.write_text(json.dumps({
        "library": {"path": str(VOLUME), "kind": "shared"},
        "scratch": {"path": str(scratch), "kind": "private"},
    }))
    write_profile(machines_dir, profile_json(
        MACHINE_ID, {"A": "library"}, platform=PLATFORM_ALTAIR))
    write_profile(machines_dir, profile_json(
        M4_MACHINE_ID, {"B": "scratch"}, platform=PLATFORM_MODEL4,
        make="Tandy", model="TRS-80 Model 4"))
    mint_dir = workdir / "two-machines-mint"
    altair_image = mint(workdir, MACHINE_ID, machines_dir=machines_dir,
                       volumes_file=volumes_file, out_dir=mint_dir)
    m4_image = mint(workdir, M4_MACHINE_ID, machines_dir=machines_dir,
                    volumes_file=volumes_file, out_dir=mint_dir)
    port = free_port()
    try:
        sc.start_server(port, machines_dir=machines_dir, volumes_file=volumes_file)

        code = sc.run_linked_sim(base_ini(port, altair_image, runlimit=60) + "\n".join([
            LOCAL_ONLY_BAILOUT,
            f'expect "{LINKED_BOOT}"',
            "go 0",
            "sleep 2",
            'send "ls /dev\\r"',
            'expect "a: library"; continue',
            'expect "p: unbound" exit 0',
            "cont",
            "exit 1",
        ]) + "\n", tag="-1001", timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: machine 1001 didn't reach its own "
                    "/dev listing" + never_linked(code))
        if "scratch" in sc.console_text() or f"machine id:  {M4_MACHINE_ID}" in sc.console_text():
            sc.fail("console: machine 1001 saw machine 1002's identity or binding")

        # Same running server, sequentially, machine 1002 next.
        m4code = sc.run_m4(m4_image, port)
        if m4code != 0:
            sc.fail(f"trs80gp exited {m4code}: machine 1002 never reached its prompt")
        m4_text = sc.console_text()
        if f"machine id:  {M4_MACHINE_ID}" not in m4_text:
            sc.fail("console: machine 1002's auto-report never showed its own machine id")
        if "b: scratch" not in m4_text:
            sc.fail("console: machine 1002's auto-report never showed its own binding")
        if "a: library" in m4_text or f"machine id:  {MACHINE_ID}" in m4_text:
            sc.fail("console: machine 1002 saw machine 1001's identity or binding")

        # Boot-time demo (dir/type/run over the real dispatch path,
        # machine/bios_m4.asm's bootdemo, link-up only). Machine 1002's own
        # binding is "scratch", deliberately NOT the library fixtures used
        # elsewhere — pointing it at library would blur this scenario's
        # whole point (map isolation: 1001 sees only "library", 1002 sees
        # only "scratch"), so this asserts the three markers fire exactly
        # once each over the real dispatch path, then their honest failure
        # (scratch carries no about.txt/hello.com) rather than the success
        # transcript — the success path (real dir listing, real file text,
        # the "HELLO, WORLD" run) is proven separately, on a volume that
        # actually carries those fixtures.
        for marker in ("boot demo: dir", "boot demo: type about.txt",
                       "boot demo: run hello.com"):
            got = m4_text.count(marker)
            if got != 1:
                sc.fail(f"console: expected exactly one {marker!r} in the boot "
                        f"demo, got {got}")
        if "NOTES.TXT 15" not in m4_text:
            sc.fail("console: the boot demo's dir didn't list machine 1002's own volume")
        if m4_text.count("file not found") != 2:
            sc.fail("console: expected two honest file-not-found lines from the "
                    f"demo (scratch carries no library fixtures), got "
                    f"{m4_text.count('file not found')}")
        if "HELLO, WORLD FROM RETRONIX" in m4_text:
            sc.fail("console: machine 1002 printed a success line for a file "
                    "its own volume doesn't have")
    finally:
        sc.teardown()

    hellos = [r for r in sc.records() if r["verb"] == "hello"]
    for mid, want_map in ((MACHINE_ID, {"A": "library"}), (M4_MACHINE_ID, {"B": "scratch"})):
        mine = [h for h in hellos if h.get("machine_id") == mid]
        if len(mine) != 1 or mine[0]["result"] != "ok":
            sc.fail(f"oracle: expected exactly one ok hello for {mid}, got {mine}")
        elif mine[0].get("drive_map") != want_map:
            sc.fail(f"oracle: machine {mid} hello carried "
                    f"{mine[0].get('drive_map')}, want {want_map}")

    # The demo's own wire traffic, oracle-authoritative (PRD §9): one ok
    # dir on machine 1002's own volume, then two honest file-not-found
    # freads — the console's "file not found" lines backed by the actual
    # protocol exchange, not just matching text.
    m4_dirs = [r for r in sc.records()
              if r["verb"] == "dir" and r.get("machine_id") == M4_MACHINE_ID]
    if len(m4_dirs) != 1 or m4_dirs[0]["result"] != "ok" or m4_dirs[0].get("volume") != "scratch":
        sc.fail(f"oracle: expected one ok dir on scratch for machine "
                f"{M4_MACHINE_ID}, got {m4_dirs}")
    m4_freads = [r for r in sc.records()
                if r["verb"] == "fread" and r.get("machine_id") == M4_MACHINE_ID]
    missing = sorted(r.get("file") for r in m4_freads)
    if len(m4_freads) != 2 or any(r["result"] != "file-not-found" for r in m4_freads) \
            or missing != ["ABOUT.TXT", "HELLO.COM"]:
        sc.fail(f"oracle: expected two file-not-found freads (ABOUT.TXT, "
                f"HELLO.COM) for machine {M4_MACHINE_ID}, got {m4_freads}")
    return sc


def scenario_m4_demo(workdir: pathlib.Path) -> Scenario:
    """The Model 4 boot-time demo's real dispatch path, proven against a
    volume that actually carries the library fixtures — the success
    transcript scenario_two_machines deliberately doesn't exercise (its
    own machine boots against "scratch", to keep the map-isolation point
    crisp). dir/type/run all succeed for real here: a real directory
    listing, the real text of about.txt, and the "HELLO, WORLD FROM
    RETRONIX" line hello.com prints once it's actually loaded and run —
    the same synthetic-command path (kwcmp/fnparse/dircmd/typecmd/runcmd)
    an operator's own typing would take (machine/bios_m4.asm's bootdemo).
    Oracle stays the authority (PRD §9): one ok dir, two ok freads.
    """
    sc = Scenario("m4-demo", workdir)
    machines_dir, volumes_file, image = machines_store(
        workdir, "m4demo", {"A": "library"}, machine_id=M4_MACHINE_ID,
        platform=PLATFORM_MODEL4)
    port = free_port()
    try:
        sc.start_server(port, machines_dir=machines_dir, volumes_file=volumes_file)
        code = sc.run_m4(image, port)
        if code != 0:
            sc.fail(f"trs80gp exited {code}: the m4-demo boot never reached its prompt")
    finally:
        sc.teardown()

    text = sc.console_text()
    for marker in ("boot demo: dir", "boot demo: type about.txt",
                   "boot demo: run hello.com"):
        got = text.count(marker)
        if got != 1:
            sc.fail(f"console: expected exactly one {marker!r} in the boot "
                    f"demo, got {got}")
    entries = expected_entries()
    last_line = f"{entries[-1][0]} {entries[-1][1]}"
    if last_line not in text:
        sc.fail(f"console: the boot demo's dir never listed {last_line!r}")
    if "M0 fixture" not in text:
        sc.fail("console: the boot demo's type never printed about.txt's real contents")
    if "HELLO, WORLD FROM RETRONIX" not in text:
        sc.fail("console: the boot demo's run never printed hello.com's real output")

    dirs = [r for r in sc.records()
           if r["verb"] == "dir" and r.get("machine_id") == M4_MACHINE_ID]
    if len(dirs) != 1 or dirs[0]["result"] != "ok" or dirs[0]["entry_count"] != len(entries):
        sc.fail(f"oracle: expected one ok dir over {len(entries)} entries, got {dirs}")
    freads = [r for r in sc.records()
             if r["verb"] == "fread" and r.get("machine_id") == M4_MACHINE_ID]
    ok_files = {r.get("file") for r in freads if r["result"] == "ok"}
    if not {"ABOUT.TXT", "HELLO.COM"} <= ok_files:
        sc.fail(f"oracle: expected ok freads for ABOUT.TXT and HELLO.COM, got {freads}")
    return sc


def scenario_probe_loop(workdir: pathlib.Path) -> Scenario:
    """A profile born with unknown RAM: mint -> boot -> HELLO records the
    observed facts and flags needs-remint -> re-mint reconciles -> boot
    again -> exact, flag clear — the refine loop end to end, driven only
    by HELLO (design.md, server/reconcile.py), task 5.4.
    """
    sc = Scenario("probe-loop", workdir)
    machines_dir = workdir / "probe-machines"
    machines_dir.mkdir(exist_ok=True)
    volumes_file = workdir / "probe-volumes.json"
    volumes_file.write_text(json.dumps({"library": {"path": str(VOLUME), "kind": "shared"}}))
    machine_id = MACHINE_ID
    # declared.ram_kb left at its default 0 -- the sentinel for "not yet
    # asserted" (server/reconcile.py's SENTINEL_FIELDS); everything else
    # is a normal declared value.
    write_profile(machines_dir, profile_json(machine_id, {"A": "library"}))
    mint_dir = workdir / "probe-mint"
    port = free_port()
    try:
        image1 = mint(workdir, machine_id, machines_dir=machines_dir,
                      volumes_file=volumes_file, out_dir=mint_dir / "1")
        fresh = read_profile(machines_dir, machine_id)
        if fresh["state"] != "probe" or fresh["needs_remint"]:
            sc.fail(f"foundry: a fresh mint should be probe/clean, got "
                    f"{fresh['state']}/{fresh['needs_remint']}")

        sc.start_server(port, machines_dir=machines_dir, volumes_file=volumes_file)
        code = sc.run_linked_sim(base_ini(port, image1, runlimit=60) + "\n".join([
            LOCAL_ONLY_BAILOUT,
            f'expect "{LINKED_BOOT}" exit 0',
            "go 0",
            "exit 1",
        ]) + "\n", tag="-probe", timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: the probe boot didn't link" + never_linked(code))
        sc.teardown()

        after_boot1 = read_profile(machines_dir, machine_id)
        if after_boot1 is None:
            sc.fail("the profile disappeared after the probe boot")
        else:
            if not after_boot1["needs_remint"]:
                sc.fail("foundry: an unknown-RAM boot should have set needs_remint")
            if after_boot1["hardware"]["observed"]["ram_kb"] is None:
                sc.fail("foundry: HELLO should have recorded the observed RAM")

        image2 = mint(workdir, machine_id, machines_dir=machines_dir,
                      volumes_file=volumes_file, out_dir=mint_dir / "2")
        after_mint2 = read_profile(machines_dir, machine_id)
        if after_mint2["needs_remint"]:
            sc.fail("foundry: re-mint should have cleared needs_remint immediately")
        if after_boot1 is not None and after_mint2["hardware"]["declared"]["ram_kb"] != \
                after_boot1["hardware"]["observed"]["ram_kb"]:
            sc.fail("foundry: re-mint should stamp the observed RAM as the new declared value")

        sc.start_server(port, machines_dir=machines_dir, volumes_file=volumes_file)
        code = sc.run_linked_sim(base_ini(port, image2, runlimit=60) + "\n".join([
            LOCAL_ONLY_BAILOUT,
            f'expect "{LINKED_BOOT}" exit 0',
            "go 0",
            "exit 1",
        ]) + "\n", tag="-exact", timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: the re-minted boot didn't link" + never_linked(code))

        final = read_profile(machines_dir, machine_id)
        if final["state"] != "exact" or final["needs_remint"]:
            sc.fail(f"foundry: expected exact/clear after the second boot, got "
                    f"{final['state']}/{final['needs_remint']}")

        # Re-minting is deterministic and block-scoped (spec's own scenario
        # name): every byte outside the config block is identical between
        # the two mints, and any difference lies inside the block — which
        # this re-checks end to end rather than trusting task 2.4's
        # template-equality guarantee on faith. Hardware facts reconciled
        # by the refine loop live in the profile, not the block (design.md's
        # layout table has no hardware-fact field), so for this profile's
        # hardware-only refinement (unknown RAM, nothing else) the two
        # blocks are legitimately byte-identical too — the strongest case
        # of "any difference lies inside the block", not a violation of it.
        b1, b2 = image1.read_bytes(), image2.read_bytes()
        off = CFGBLK_OFFSET[PLATFORM_ALTAIR]
        outside1 = b1[:off] + b1[off + CFGBLK_RESERVED_LEN:]
        outside2 = b2[:off] + b2[off + CFGBLK_RESERVED_LEN:]
        if outside1 != outside2:
            sc.fail("foundry: the two mints differ outside the config block")
    finally:
        sc.teardown()
    return sc


def scenario_drift(workdir: pathlib.Path) -> Scenario:
    """Edit a profile's drive map after minting, boot the unchanged image,
    and confirm the response carries the edited map while the profile ends
    with needs-remint set — the running session is correct even though the
    burned ROM is stale (design.md, task 5.5).
    """
    sc = Scenario("drift", workdir)
    scratch = scratch_volume(workdir)
    # declared.ram_kb set to the real value up front so RAM reconciliation
    # can't independently flag needs_remint — this scenario isolates drift.
    machines_dir, volumes_file, image = machines_store(
        workdir, "drift", {"A": "library"},
        declared={"cpu": 0, "ram_kb": 63, "console": 0})
    machine_id = MACHINE_ID
    port = free_port()
    try:
        profile = read_profile(machines_dir, machine_id)
        profile["drive_map"]["C"] = "scratch"
        write_profile(machines_dir, profile)
        vols = json.loads(volumes_file.read_text())
        vols["scratch"] = {"path": str(scratch), "kind": "private"}
        volumes_file.write_text(json.dumps(vols))

        sc.start_server(port, machines_dir=machines_dir, volumes_file=volumes_file)
        code = sc.run_linked_sim(base_ini(port, image, runlimit=60) + "\n".join([
            LOCAL_ONLY_BAILOUT,
            f'expect "{LINKED_BOOT}"',
            "go 0",
            "sleep 2",
            'send "ls /dev\\r"',
            'expect "a: library"; continue',
            'expect "c: scratch" exit 0',
            "cont",
            "exit 1",
        ]) + "\n", timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: the edited map wasn't served off the "
                    "unchanged (stale) image" + never_linked(code))
    finally:
        sc.teardown()

    hellos = [r for r in sc.records() if r["verb"] == "hello"]
    if len(hellos) != 1 or hellos[0]["result"] != "ok":
        sc.fail(f"oracle: expected one ok hello, got {hellos}")
    elif hellos[0].get("drive_map") != {"A": "library", "C": "scratch"}:
        sc.fail(f"oracle: hello should carry the edited map, got "
                f"{hellos[0].get('drive_map')}")

    after = read_profile(machines_dir, machine_id)
    if after is None:
        sc.fail("the profile disappeared after the drift boot")
    else:
        if not after["needs_remint"]:
            sc.fail("foundry: an edited-then-booted profile should end needs_remint")
        if after["state"] != "probe":
            sc.fail(f"foundry: a drifted profile should not read exact, got {after['state']}")

    result = subprocess.run(
        [sys.executable, str(FOUNDRY), "--machines-dir", str(machines_dir),
         "--volumes-file", str(volumes_file), "list"],
        capture_output=True, text=True)
    if "needs-remint" not in result.stdout:
        sc.fail(f"foundry list didn't flag the drifted profile: {result.stdout!r}")
    return sc


def scenario_block_integrity(workdir: pathlib.Path) -> Scenario:
    """A booted mint's `config` report matches what the foundry stamped:
    machine id, link config, and baked bindings, and the block reads valid
    (design.md "The stamped block is proven against the machine's own
    report", task 5.6). Altair, typed `config` — the Model 4 side of this
    same proof (machine id + its own binding, off the auto-report) is
    already covered by scenario_two_machines.
    """
    sc = Scenario("block-integrity", workdir)
    scratch = scratch_volume(workdir)
    machines_dir, volumes_file, image = machines_store(
        workdir, "integrity", {"A": "library", "B": "scratch"},
        volumes={"scratch": {"path": str(scratch), "kind": "private"}},
        declared={"cpu": 0, "ram_kb": 63, "console": 0})
    profile = read_profile(machines_dir, MACHINE_ID)
    link = profile["link"]
    port_lo = f'{link["port_base"]:02x}h'
    port_hi = f'{link["port_base"] + 1:02x}h'
    mode_hex = f'{link["mode"]:02x}h'
    port = free_port()
    try:
        sc.start_server(port, machines_dir=machines_dir, volumes_file=volumes_file)
        code = sc.run_linked_sim(base_ini(port, image, runlimit=60) + "\n".join([
            LOCAL_ONLY_BAILOUT,
            f'expect "{LINKED_BOOT}"',
            "go 0",
            "sleep 2",
            'send "config\\r"',
            f'expect "machine id:  {MACHINE_ID}"; continue',
            'expect "config block: valid, format 1"; continue',
            f'expect "link config: wire acia, ports {port_lo}/{port_hi}, '
                f'mode {mode_hex}, machine-initiated"; continue',
            'expect "a: library"; continue',
            'expect "b: scratch" exit 0',
            "cont",
            "exit 1",
        ]) + "\n", timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: config didn't report the stamped block"
                    + never_linked(code))
    finally:
        sc.teardown()
    return sc


def run_pass(n: int) -> bool:
    workdir = pathlib.Path(tempfile.mkdtemp(prefix=f"m0-pass{n}-", dir=BUILD))
    ok = True
    for fn in (scenario_spine, scenario_run_com, scenario_type_missing,
               scenario_server_down, scenario_unknown_machine,
               scenario_dev_linked, scenario_dev_local, scenario_config,
               scenario_multi_binding, scenario_empty_map,
               scenario_bind_refusals, scenario_link_recovery,
               scenario_teardown_after_failure,
               scenario_two_machines, scenario_m4_demo, scenario_probe_loop,
               scenario_drift, scenario_block_integrity):
        sc = fn(workdir)
        status = "PASS" if not sc.failures else "FAIL"
        print(f"  [{status}] {sc.name}")
        for msg in sc.failures:
            print(f"         - {msg}")
        ok = ok and not sc.failures
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()
    if not (ROOT / "build/retronix.bin").exists():
        print("build/retronix.bin missing — run `make image` first", file=sys.stderr)
        return 2
    if not (ROOT / "build/retronix-m4.bin").exists():
        print("build/retronix-m4.bin missing — run `make image-m4` first", file=sys.stderr)
        return 2
    BUILD.mkdir(exist_ok=True)
    for n in range(1, args.runs + 1):
        print(f"proof pass {n}/{args.runs}")
        if not run_pass(n):
            print("proof: FAILED")
            return 1
    print(f"proof: all {args.runs} pass(es) green — the ladder holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
