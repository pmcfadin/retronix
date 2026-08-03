#!/usr/bin/env python3
"""M0 harness: bring up server + SIMH, run the spine, assert, tear down.

Three scenarios per pass:
  spine           boot -> HELLO -> drive map -> dir on the bound volume
  server-down     no server: machine must land at the local-only prompt
  unknown-machine server refuses an unprofiled machine ID; machine degrades

Success is asserted against the server's structured JSONL log (the test
oracle) plus SIMH's own expect matcher driving the console — the harness
never scrapes terminal text itself. Exit code 0 iff every assertion passes.
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
SIM_WALL_TIMEOUT = 60  # seconds; runlimit inside the ini is the primary guard


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

    def fail(self, msg: str):
        self.failures.append(msg)

    # -- processes --------------------------------------------------------

    def start_server(self, port: int, config: pathlib.Path | None = None):
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

    def run_sim(self, ini_text: str) -> int:
        ini = self.workdir / f"{self.name}.ini"
        ini.write_text(ini_text)
        console = self.workdir / f"{self.name}-console.txt"
        with open(console, "w") as out:
            sim = subprocess.Popen([str(ALTAIRZ80), str(ini)],
                                   stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=subprocess.STDOUT)
            try:
                return sim.wait(timeout=SIM_WALL_TIMEOUT)
            except subprocess.TimeoutExpired:
                sim.kill()
                sim.wait()
                self.fail("SIMH hit the wall-clock timeout and was killed")
                return -1

    def teardown(self):
        """Deterministic: kill exactly the processes we started."""
        if self.server:
            self.server.terminate()
            try:
                self.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait()
            self.server = None

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
        code = sc.run_sim(base_ini(port) + "\n".join([
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
        code = sc.run_sim(base_ini(port) + "\n".join([
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
        code = sc.run_sim(base_ini(port) + "\n".join([
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
        code = sc.run_sim(base_ini(port) + "\n".join([
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


def run_pass(n: int) -> bool:
    workdir = pathlib.Path(tempfile.mkdtemp(prefix=f"m0-pass{n}-", dir=BUILD))
    ok = True
    for fn in (scenario_spine, scenario_run_com, scenario_type_missing,
               scenario_server_down, scenario_unknown_machine):
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
        print(f"M0 pass {n}/{args.runs}")
        if not run_pass(n):
            print("M0: FAILED")
            return 1
    print(f"M0: all {args.runs} pass(es) green — the spine holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
