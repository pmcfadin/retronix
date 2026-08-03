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

Success is asserted against the server's structured JSONL log (the test
oracle) plus SIMH's own expect matcher driving the console. Positive console
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
IMAGE = ROOT / "build/retronix.bin"
SERVER = ROOT / "server/retronix_server.py"
VOLUME = ROOT / "server/volumes/library"
BUILD = ROOT / "build"
MACHINE_ID = 1001
ROM_VERSION = "0.3.0"
SIM_WALL_TIMEOUT = 60  # seconds; runlimit inside the ini is the primary guard
# Scenarios that halt SIMH mid-run and sleep while the harness moves the
# server around spend most of their wall clock outside `go`, where the ini's
# runlimit does not tick. They get their own, longer wall-clock guard.
SIM_WALL_TIMEOUT_STAGED = 200


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
        self.server_config: pathlib.Path | None = None
        self.console_path: pathlib.Path | None = None

    def fail(self, msg: str):
        self.failures.append(msg)

    # -- processes --------------------------------------------------------

    def start_server(self, port: int, config: pathlib.Path | None = None):
        self.port = port
        self.server_config = config
        ready = self.workdir / f"{self.name}.ready"
        ready.unlink(missing_ok=True)
        cmd = [sys.executable, str(SERVER), "--port", str(port),
               "--log", str(self.log_path), "--ready-file", str(ready)]
        if config:
            cmd += ["--config", str(config)]
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
        self.start_server(self.port, self.server_config)

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


def base_ini(port: int | None, runlimit: int = 30) -> str:
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
        f"load {IMAGE} 0",
        f"runlimit {runlimit} seconds",
    ]
    return "\n".join(lines) + "\n"


def scenario_spine(workdir: pathlib.Path) -> Scenario:
    sc = Scenario("spine", workdir)
    entries = expected_entries()
    last_line = f"{entries[-1][0]} {entries[-1][1]}"
    port = free_port()
    try:
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port) + "\n".join([
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
    try:
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port) + "\n".join([
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
    try:
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port) + "\n".join([
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
    try:
        code = sc.run_sim(base_ini(port=None) + "\n".join([
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
    config = workdir / "unknown-profiles.json"
    config.write_text(json.dumps({
        "volumes": {"library": {"path": str(VOLUME), "kind": "shared"}},
        "machines": {"4242": {"make": "x", "model": "x",
                              "drive_map": {"A": "library"}}},
    }))
    port = free_port()
    try:
        sc.start_server(port, config=config)
        code = sc.run_linked_sim(base_ini(port) + "\n".join([
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
    wire = WireWatch(sc, "ls /dev")
    try:
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port, runlimit=60) + "\n".join([
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
    """`ls /dev` on a local-only boot: wire down, nothing claiming a volume."""
    sc = Scenario("dev-local", workdir)
    try:
        code = sc.run_sim(base_ini(port=None, runlimit=60) + "\n".join([
            'expect "local-only mode"',
            "go 0",
            "sleep 1",
            'send "ls /dev\\r"',
            f'expect "{DEV_CPU}"; continue',
            f'expect "{DEV_CONSOLE}"; continue',
            f'expect "{DEV_WIRE_DOWN}"; continue',
            'expect "a: unbound"; continue',
            'expect "p: unbound" exit 0',
            "cont",
            "exit 1",
        ]) + "\n", timeout=SIM_WALL_TIMEOUT_STAGED)
        if code != 0:
            sc.fail(f"sim exited {code}: local-only /dev didn't report the wire down")
        # A matcher proves presence, never absence: no drive letter may claim
        # a live volume on a machine that never linked.
        if "library" in sc.console_text():
            sc.fail("console: a volume name appears on a local-only boot")
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
        port = free_port()
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port, runlimit=60) + "\n".join([
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
        code = sc.run_sim(base_ini(port=None, runlimit=60) + "\n".join([
            'expect "local-only mode"',
            "go 0",
            "sleep 1",
            'send "config\\r"',
        ] + burned_in + [
            'expect "link state:  local-only mode"; continue',
            'expect "the server profile owns it"; continue',
            'expect "no network bindings" exit 0',
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


def profile_config(workdir: pathlib.Path, name: str, drive_map: dict,
                   volumes: dict | None = None,
                   machine_id: int = MACHINE_ID) -> pathlib.Path:
    """Write a one-off server profile so a scenario can shape the drive map."""
    vols = {"library": {"path": str(VOLUME), "kind": "shared"}}
    vols.update(volumes or {})
    path = workdir / f"{name}-profiles.json"
    path.write_text(json.dumps({
        "volumes": vols,
        "machines": {str(machine_id): {"make": "MITS", "model": "test",
                                       "drive_map": drive_map}},
    }))
    return path


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
    config = profile_config(
        workdir, "multi", {"A": "library", "C": "scratch"},
        volumes={"scratch": {"path": str(scratch), "kind": "private"}})
    port = free_port()
    wire = WireWatch(sc, "config and ls /dev")
    try:
        sc.start_server(port, config=config)
        code = sc.run_linked_sim(base_ini(port, runlimit=90) + "\n".join([
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
    config = profile_config(workdir, "empty", {})
    port = free_port()
    try:
        sc.start_server(port, config=config)
        code = sc.run_linked_sim(base_ini(port, runlimit=60) + "\n".join([
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
    config = profile_config(workdir, "someone-else", {"A": "library"},
                            machine_id=4242)
    port = free_port()
    hellos: list[int] = []

    def count() -> int:
        return sum(1 for r in sc.records() if r["verb"] == "hello")

    def refused_then_kill():
        hellos.append(count())   # the record is written before the machine
        sc.teardown()            # can print, so count it before killing
    try:
        sc.start_server(port, config=config)
        code = sc.run_sim(base_ini(port, runlimit=150) + "\n".join([
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
    survivor = None
    try:
        doomed.start_server(port)
        code = doomed.run_linked_sim(base_ini(port, runlimit=15) + "\n".join([
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
    try:
        sc.start_server(port)
        code = sc.run_linked_sim(base_ini(port, runlimit=150) + "\n".join([
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


def run_pass(n: int) -> bool:
    workdir = pathlib.Path(tempfile.mkdtemp(prefix=f"m0-pass{n}-", dir=BUILD))
    ok = True
    for fn in (scenario_spine, scenario_run_com, scenario_type_missing,
               scenario_server_down, scenario_unknown_machine,
               scenario_dev_linked, scenario_dev_local, scenario_config,
               scenario_multi_binding, scenario_empty_map,
               scenario_bind_refusals, scenario_link_recovery,
               scenario_teardown_after_failure):
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
    if not IMAGE.exists():
        print("build/retronix.bin missing — run `make image` first", file=sys.stderr)
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
