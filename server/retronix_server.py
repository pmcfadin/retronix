"""RetroNix M0 server: static profiles, one shared volume, HELLO + DIR.

The structured JSONL log is the project's test oracle (PRD §9): one record
per request/response pair, asserted on by the harness — never terminal text.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import socket
import sys
import time

import protocol as p

DRIVE_NAMES = "ABCDEFGHIJKLMNOP"


def to_83(path: pathlib.Path) -> tuple[str, str]:
    """Map a host filename onto a CP/M 8.3 uppercase name."""
    stem = path.stem.upper()[:8]
    ext = path.suffix.lstrip(".").upper()[:3]
    return stem, ext


class Volume:
    def __init__(self, name: str, root: pathlib.Path, kind: str):
        self.name = name
        self.root = root
        self.kind = kind  # "shared" (read-only) — "owned" arrives post-M0

    def entries(self) -> list[tuple[str, str, int]]:
        out = []
        for f in sorted(self.root.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                stem, ext = to_83(f)
                out.append((stem, ext, f.stat().st_size))
        return out


class Profile:
    def __init__(self, machine_id: int, spec: dict, volumes: dict[str, Volume]):
        self.machine_id = machine_id
        self.make = spec.get("make", "")
        self.model = spec.get("model", "")
        # drive map: letter -> Volume
        self.drive_map = {
            letter.upper(): volumes[vol] for letter, vol in spec["drive_map"].items()
        }
        self.reported_rom: tuple | None = None
        self.reported_inventory: dict | None = None


def load_config(path: pathlib.Path) -> tuple[dict[int, Profile], dict[str, Volume]]:
    cfg = json.loads(path.read_text())
    base = path.parent
    volumes = {
        name: Volume(name, (base / v["path"]).resolve(), v["kind"])
        for name, v in cfg["volumes"].items()
    }
    profiles = {
        int(mid): Profile(int(mid), spec, volumes)
        for mid, spec in cfg["machines"].items()
    }
    return profiles, volumes


class Session:
    """Per-connection state: which machine spoke HELLO."""

    def __init__(self):
        self.profile: Profile | None = None


class Server:
    def __init__(self, profiles: dict[int, Profile], log_path: pathlib.Path):
        self.profiles = profiles
        self.log_path = log_path
        self.log_file = open(log_path, "a", buffering=1)

    def log(self, **record):
        record["ts"] = time.time()
        self.log_file.write(json.dumps(record) + "\n")

    # -- handlers ---------------------------------------------------------

    def handle_frame(self, session: Session, function: int, payload: bytes) -> bytes:
        if function == p.FHELLO:
            return self.handle_hello(session, payload)
        if function == p.FDIR:
            return self.handle_dir(session, payload)
        self.log(verb=f"unknown-0x{function:02x}", machine_id=None,
                 result=p.RESULT_NAMES[p.RBADREQ])
        return p.encode(function | p.FRESP, bytes((p.RBADREQ,)))

    def handle_bad_frame(self, reason: str) -> bytes:
        self.log(verb="bad-frame", machine_id=None,
                 result=p.RESULT_NAMES[p.RBADFRM], reason=reason)
        return p.encode(p.FERR, bytes((p.RBADFRM,)))

    def handle_hello(self, session: Session, payload: bytes) -> bytes:
        if len(payload) != 10:
            self.log(verb="hello", machine_id=None,
                     result=p.RESULT_NAMES[p.RBADREQ])
            return p.encode(p.FHELLO | p.FRESP, bytes((p.RBADREQ,)))
        machine_id = int.from_bytes(payload[0:4], "little")
        rom = (payload[4], payload[5], payload[6])
        inventory = {"cpu": "Z80" if payload[7] else "8080",
                     "ram_kb": payload[8], "serial_up": bool(payload[9])}
        profile = self.profiles.get(machine_id)
        if profile is None:
            self.log(verb="hello", machine_id=machine_id,
                     result=p.RESULT_NAMES[p.RUNKMCH])
            return p.encode(p.FHELLO | p.FRESP, bytes((p.RUNKMCH,)))

        profile.reported_rom = rom
        profile.reported_inventory = inventory
        session.profile = profile

        body = bytearray((p.ROK, len(profile.drive_map)))
        for letter, vol in sorted(profile.drive_map.items()):
            flags = 0x01 if vol.kind == "shared" else 0x00  # bit0: read-only
            name = vol.name.encode("ascii")
            body += bytes((DRIVE_NAMES.index(letter), 0x00, flags, len(name)))
            body += name
        self.log(verb="hello", machine_id=machine_id,
                 rom_version=".".join(map(str, rom)), inventory=inventory,
                 drive_map={l: v.name for l, v in profile.drive_map.items()},
                 result=p.RESULT_NAMES[p.ROK])
        return p.encode(p.FHELLO | p.FRESP, bytes(body))

    def handle_dir(self, session: Session, payload: bytes) -> bytes:
        machine_id = session.profile.machine_id if session.profile else None
        if session.profile is None or len(payload) != 1:
            self.log(verb="dir", machine_id=machine_id,
                     result=p.RESULT_NAMES[p.RBADREQ])
            return p.encode(p.FDIR | p.FRESP, bytes((p.RBADREQ,)))
        drive_index = payload[0]
        letter = DRIVE_NAMES[drive_index] if drive_index < 16 else "?"
        vol = session.profile.drive_map.get(letter)
        if vol is None:
            self.log(verb="dir", machine_id=machine_id, drive=letter,
                     result=p.RESULT_NAMES[p.RUNBND])
            return p.encode(p.FDIR | p.FRESP, bytes((p.RUNBND,)))

        entries = vol.entries()
        body = bytearray((p.ROK,)) + len(entries).to_bytes(2, "little")
        for stem, ext, size in entries:
            body += stem.ljust(8).encode("ascii")
            body += ext.ljust(3).encode("ascii")
            body += min(size, 0xFFFFFFFF).to_bytes(4, "little")
        self.log(verb="dir", machine_id=machine_id, drive=letter,
                 volume=vol.name, entry_count=len(entries),
                 result=p.RESULT_NAMES[p.ROK])
        return p.encode(p.FDIR | p.FRESP, bytes(body))

    # -- socket loop ------------------------------------------------------

    def serve(self, host: str, port: int, ready_file: pathlib.Path | None = None):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((host, port))
            srv.listen(1)
            if ready_file:
                ready_file.write_text(str(port))
            self.log(verb="listening", machine_id=None, port=port, result="ok")
            while True:
                conn, _ = srv.accept()
                with conn:
                    self.serve_connection(conn)

    def serve_connection(self, conn: socket.socket):
        session = Session()

        def recv_exact(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                chunk = conn.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("peer closed")
                buf += chunk
            return buf

        while True:
            try:
                function, payload = p.read_frame(recv_exact)
            except ConnectionError:
                return
            except p.FrameError as e:
                conn.sendall(self.handle_bad_frame(str(e)))
                continue
            conn.sendall(self.handle_frame(session, function, payload))


def main(argv=None):
    ap = argparse.ArgumentParser(description="RetroNix M0 server")
    ap.add_argument("--config", default=str(pathlib.Path(__file__).parent / "profiles.json"))
    ap.add_argument("--port", type=int, default=5810)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--log", default="build/server-log.jsonl")
    ap.add_argument("--ready-file", default=None)
    args = ap.parse_args(argv)

    log_path = pathlib.Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    profiles, _ = load_config(pathlib.Path(args.config))
    server = Server(profiles, log_path)
    ready = pathlib.Path(args.ready_file) if args.ready_file else None
    try:
        server.serve(args.host, args.port, ready)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
