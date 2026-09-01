"""RetroNix server: per-machine profile store, shared volumes, HELLO/DIR/FREAD.

The structured JSONL log is the project's test oracle (PRD §9): one record
per request/response pair, asserted on by the harness — never terminal text.

Profiles live one-per-file under `--machines-dir` (design.md's migration
plan, server/machine_store.py); volume definitions live in their own file
(`--volumes-file`), separate from the machine store (specs/server/spec.md
"Machine profiles live in a per-machine store"). The server never creates,
edits identity in, or otherwise writes a profile except through
`reconcile.reconcile_hello` on a HELLO — every other edit belongs to
`server/foundry.py` (ADR-0006, specs/foundry/spec.md).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import socket
import sys
import time

import machine_store as ms
import protocol as p
import reconcile as rc

DRIVE_NAMES = "ABCDEFGHIJKLMNOP"

# The practical CP/M filename charset. The volume root is the trust
# boundary: requests are allowlisted before any path is ever formed.
NAME_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789$_-")


def parse_83(raw: bytes) -> str | None:
    """Validate an 11-byte space-padded 8.3 field -> 'STEM.EXT' or None."""
    if len(raw) != 11:
        return None
    try:
        stem, ext = raw[:8].decode("ascii"), raw[8:].decode("ascii")
    except UnicodeDecodeError:
        return None
    stem, ext = stem.rstrip(" "), ext.rstrip(" ")
    if not stem:
        return None
    for part in (stem, ext):
        if any(c not in NAME_CHARS for c in part):
            return None
    return f"{stem}.{ext}" if ext else stem


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

    def read(self, name83: str, offset: int, length: int) -> bytes | None:
        """Bytes at [offset, offset+length) of the named file, or None if
        absent. Short (or empty) result past EOF — never an error."""
        for f in sorted(self.root.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                stem, ext = to_83(f)
                if (f"{stem}.{ext}" if ext else stem) == name83:
                    data = f.read_bytes()
                    return data[offset:offset + length]
        return None


def load_volumes(path: pathlib.Path) -> dict[str, Volume]:
    """Volume definitions live in their own file, separate from the machine
    store (design.md's migration plan, specs/server/spec.md)."""
    cfg = json.loads(path.read_text())
    base = path.parent
    return {
        name: Volume(name, (base / v["path"]).resolve(), v["kind"])
        for name, v in cfg.items()
    }


def resolve_drive_map(profile: dict, volumes: dict[str, Volume]) -> dict[str, Volume]:
    """profile['drive_map'] (letter -> volume name) resolved to Volume
    objects, skipping any binding whose volume isn't in the loaded set.

    The machine must still boot on an operator error like this — a missing
    volume drops only that one binding — but the drop is silent on the wire
    (the machine just sees an unbound letter), so it is logged loudly here
    to stderr rather than disappearing entirely.
    """
    out = {}
    for letter, vol_name in profile["drive_map"].items():
        vol = volumes.get(vol_name)
        if vol is None:
            print(f"retronix_server: WARNING: machine {profile['machine_id']} "
                  f"drive {letter.upper()}: volume {vol_name!r} not found in "
                  "the volumes file; binding dropped", file=sys.stderr)
            continue
        out[letter.upper()] = vol
    return out


class Session:
    """Per-connection state: which machine spoke HELLO."""

    def __init__(self):
        self.machine_id: int | None = None
        self.profile: dict | None = None       # the reconciled profile dict
        self.drive_map: dict[str, Volume] = {}  # letter -> Volume, from HELLO


class Server:
    def __init__(self, machines_dir: pathlib.Path, volumes: dict[str, Volume],
                log_path: pathlib.Path):
        self.machines_dir = machines_dir
        self.volumes = volumes
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
        if function == p.FREAD:
            return self.handle_fread(session, payload)
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
        cpu_code, ram_kb, serial_up = payload[7], payload[8], bool(payload[9])
        inventory = {"cpu": "Z80" if cpu_code else "8080",
                     "ram_kb": ram_kb, "serial_up": serial_up}

        try:
            profile = ms.load_profile(self.machines_dir, machine_id)
        except ms.ProfileError as e:
            # The wire answer is the same as unknown-machine either way
            # (RUNKMCH is the honest thing to say to the machine), but a
            # malformed profile is a server-side problem, not a genuinely
            # unprovisioned id — flag it distinctly on stderr so an operator
            # doesn't mistake one for the other.
            print(f"retronix_server: WARNING: machine {machine_id}: profile "
                  f"failed to load: {e}", file=sys.stderr)
            profile = None
        if profile is None:
            self.log(verb="hello", machine_id=machine_id,
                     result=p.RESULT_NAMES[p.RUNKMCH])
            return p.encode(p.FHELLO | p.FRESP, bytes((p.RUNKMCH,)))

        # HELLO reconciliation (ADR-0005, server/reconcile.py): the only
        # write the running server performs, and it never touches identity,
        # drive map, link config, or mint state.
        rc.reconcile_hello(profile, rom_version=rom, cpu=cpu_code, ram_kb=ram_kb)
        ms.save_profile(self.machines_dir, profile)

        session.machine_id = machine_id
        session.profile = profile
        session.drive_map = resolve_drive_map(profile, self.volumes)

        body = bytearray((p.ROK, len(session.drive_map)))
        for letter, vol in sorted(session.drive_map.items()):
            flags = 0x01 if vol.kind == "shared" else 0x00  # bit0: read-only
            name = vol.name.encode("ascii")
            body += bytes((DRIVE_NAMES.index(letter), 0x00, flags, len(name)))
            body += name
        self.log(verb="hello", machine_id=machine_id,
                 rom_version=".".join(map(str, rom)), inventory=inventory,
                 drive_map={l: v.name for l, v in session.drive_map.items()},
                 result=p.RESULT_NAMES[p.ROK])
        return p.encode(p.FHELLO | p.FRESP, bytes(body))

    def handle_dir(self, session: Session, payload: bytes) -> bytes:
        machine_id = session.machine_id
        if session.machine_id is None or len(payload) != 1:
            self.log(verb="dir", machine_id=machine_id,
                     result=p.RESULT_NAMES[p.RBADREQ])
            return p.encode(p.FDIR | p.FRESP, bytes((p.RBADREQ,)))
        drive_index = payload[0]
        letter = DRIVE_NAMES[drive_index] if drive_index < 16 else "?"
        vol = session.drive_map.get(letter)
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

    def handle_fread(self, session: Session, payload: bytes) -> bytes:
        machine_id = session.machine_id
        if session.machine_id is None or len(payload) != p.FREAD_REQ_LEN:
            self.log(verb="fread", machine_id=machine_id,
                     result=p.RESULT_NAMES[p.RBADREQ])
            return p.encode(p.FREAD | p.FRESP, bytes((p.RBADREQ,)))
        drive_index = payload[0]
        letter = DRIVE_NAMES[drive_index] if drive_index < 16 else "?"
        name = parse_83(payload[1:12])
        offset = int.from_bytes(payload[12:16], "little")
        length = int.from_bytes(payload[16:18], "little")
        vol = session.drive_map.get(letter)
        if vol is None:
            self.log(verb="fread", machine_id=machine_id, drive=letter,
                     result=p.RESULT_NAMES[p.RUNBND])
            return p.encode(p.FREAD | p.FRESP, bytes((p.RUNBND,)))
        if name is None:
            self.log(verb="fread", machine_id=machine_id, drive=letter,
                     result=p.RESULT_NAMES[p.RBADREQ], reason="bad 8.3 name")
            return p.encode(p.FREAD | p.FRESP, bytes((p.RBADREQ,)))
        data = vol.read(name, offset, length)
        if data is None:
            self.log(verb="fread", machine_id=machine_id, drive=letter,
                     file=name, offset=offset, requested=length,
                     result=p.RESULT_NAMES[p.RFNF])
            return p.encode(p.FREAD | p.FRESP, bytes((p.RFNF,)))
        self.log(verb="fread", machine_id=machine_id, drive=letter,
                 file=name, offset=offset, requested=length,
                 actual=len(data), result=p.RESULT_NAMES[p.ROK])
        body = bytes((p.ROK,)) + len(data).to_bytes(2, "little") + data
        return p.encode(p.FREAD | p.FRESP, body)

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
    ap = argparse.ArgumentParser(description="RetroNix server")
    ap.add_argument("--machines-dir",
                    default=str(pathlib.Path(__file__).parent / "machines"))
    ap.add_argument("--volumes-file",
                    default=str(pathlib.Path(__file__).parent / "volumes.json"))
    ap.add_argument("--port", type=int, default=5810)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--log", default="build/server-log.jsonl")
    ap.add_argument("--ready-file", default=None)
    args = ap.parse_args(argv)

    log_path = pathlib.Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    volumes = load_volumes(pathlib.Path(args.volumes_file))
    server = Server(pathlib.Path(args.machines_dir), volumes, log_path)
    ready = pathlib.Path(args.ready_file) if args.ready_file else None
    try:
        server.serve(args.host, args.port, ready)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
