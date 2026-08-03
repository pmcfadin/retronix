import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import protocol as p
from retronix_server import Server, Session, Volume, Profile, to_83

MACHINE_ID = 1001


def hello_payload(machine_id=MACHINE_ID, rom=(0, 1, 0), cpu=0, ram=64, serial=1):
    return (machine_id.to_bytes(4, "little")
            + bytes(rom) + bytes((cpu, ram, serial)))


class ServerFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        voldir = root / "library"
        voldir.mkdir()
        (voldir / "HELLO.COM").write_bytes(b"\xc9" * 36)
        (voldir / "about.txt").write_text("hi")
        (voldir / "longfilename.markdown").write_text("x")
        vol = Volume("library", voldir, "shared")
        profile = Profile(MACHINE_ID, {"make": "MITS", "model": "Altair",
                                       "drive_map": {"A": "library"}},
                          {"library": vol})
        self.log_path = root / "log.jsonl"
        self.server = Server({MACHINE_ID: profile}, self.log_path)
        self.session = Session()

    def tearDown(self):
        self.server.log_file.close()
        self.tmp.cleanup()

    def log_records(self):
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    def rpc(self, function, payload):
        response = self.server.handle_frame(self.session, function, payload)
        fn, body = p.decode(response)
        return fn, body


class HelloTests(ServerFixture):
    def test_known_machine_gets_drive_map(self):
        fn, body = self.rpc(p.FHELLO, hello_payload())
        self.assertEqual(fn, p.FHELLO | p.FRESP)
        self.assertEqual(body[0], p.ROK)
        self.assertEqual(body[1], 1)  # one binding
        drive_index, kind, flags, name_len = body[2:6]
        self.assertEqual(drive_index, 0)          # A:
        self.assertEqual(kind, 0)                 # network
        self.assertEqual(flags & 0x01, 1)         # read-only
        self.assertEqual(body[6:6 + name_len], b"library")

    def test_inventory_recorded(self):
        self.rpc(p.FHELLO, hello_payload(rom=(1, 2, 3), cpu=1, ram=48))
        profile = self.server.profiles[MACHINE_ID]
        self.assertEqual(profile.reported_rom, (1, 2, 3))
        self.assertEqual(profile.reported_inventory["cpu"], "Z80")
        self.assertEqual(profile.reported_inventory["ram_kb"], 48)
        record = self.log_records()[-1]
        self.assertEqual(record["verb"], "hello")
        self.assertEqual(record["result"], "ok")
        self.assertEqual(record["inventory"]["ram_kb"], 48)

    def test_unknown_machine_refused(self):
        fn, body = self.rpc(p.FHELLO, hello_payload(machine_id=9999))
        self.assertEqual(body[0], p.RUNKMCH)
        self.assertIsNone(self.session.profile)
        self.assertEqual(self.log_records()[-1]["result"], "unknown-machine")

    def test_repeat_hello_is_idempotent(self):
        first = self.rpc(p.FHELLO, hello_payload())
        second = self.rpc(p.FHELLO, hello_payload())
        self.assertEqual(first, second)
        for fn, body in (first, second):
            self.assertEqual(fn, p.FHELLO | p.FRESP)
            self.assertEqual(body[0], p.ROK)
            self.assertEqual(body[1], 1)          # the drive map came back
            name_len = body[5]
            self.assertEqual(body[6:6 + name_len], b"library")
        # the session still serves DIR after the second HELLO
        fn, body = self.rpc(p.FDIR, bytes((0,)))
        self.assertEqual(body[0], p.ROK)
        self.assertEqual(int.from_bytes(body[1:3], "little"), 3)
        verbs = [r["verb"] for r in self.log_records()]
        self.assertEqual(verbs, ["hello", "hello", "dir"])

    def test_malformed_hello(self):
        fn, body = self.rpc(p.FHELLO, b"\x01\x02")
        self.assertEqual(body[0], p.RBADREQ)


class DirTests(ServerFixture):
    def bind(self):
        self.rpc(p.FHELLO, hello_payload())

    def test_dir_lists_83_entries(self):
        self.bind()
        fn, body = self.rpc(p.FDIR, bytes((0,)))
        self.assertEqual(body[0], p.ROK)
        count = int.from_bytes(body[1:3], "little")
        self.assertEqual(count, 3)
        entries = body[3:]
        names = [entries[i * 15:i * 15 + 11].decode() for i in range(count)]
        self.assertIn("HELLO   COM", names)
        self.assertIn("ABOUT   TXT", names)
        self.assertIn("LONGFILEMAR", names)  # truncated to 8.3, uppercased
        sizes = [int.from_bytes(entries[i * 15 + 11:i * 15 + 15], "little")
                 for i in range(count)]
        self.assertIn(36, sizes)

    def test_dir_is_idempotent(self):
        self.bind()
        first = self.server.handle_frame(self.session, p.FDIR, bytes((0,)))
        second = self.server.handle_frame(self.session, p.FDIR, bytes((0,)))
        self.assertEqual(first, second)

    def test_unbound_drive(self):
        self.bind()
        fn, body = self.rpc(p.FDIR, bytes((3,)))  # D: not in map
        self.assertEqual(body[0], p.RUNBND)
        self.assertEqual(self.log_records()[-1]["result"], "unbound-drive")

    def test_dir_before_hello_is_bad_request(self):
        fn, body = self.rpc(p.FDIR, bytes((0,)))
        self.assertEqual(body[0], p.RBADREQ)


class OracleLogTests(ServerFixture):
    def test_one_exchange_two_records(self):
        self.rpc(p.FHELLO, hello_payload())
        self.rpc(p.FDIR, bytes((0,)))
        records = [r for r in self.log_records()
                   if r.get("machine_id") == MACHINE_ID]
        self.assertEqual([r["verb"] for r in records], ["hello", "dir"])
        for r in records:
            self.assertIn("result", r)
            self.assertIn("ts", r)

    def test_bad_frame_logged_and_answered(self):
        response = self.server.handle_bad_frame("checksum mismatch")
        fn, body = p.decode(response)
        self.assertEqual(fn, p.FERR)
        self.assertEqual(body[0], p.RBADFRM)
        self.assertEqual(self.log_records()[-1]["verb"], "bad-frame")


class Nameing83Tests(unittest.TestCase):
    def test_to_83(self):
        self.assertEqual(to_83(Path("hello.com")), ("HELLO", "COM"))
        self.assertEqual(to_83(Path("longfilename.markdown")), ("LONGFILE", "MAR"))
        self.assertEqual(to_83(Path("noext")), ("NOEXT", ""))


if __name__ == "__main__":
    unittest.main()
