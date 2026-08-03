import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import protocol as p
from retronix_server import parse_83
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_handlers import ServerFixture, hello_payload, MACHINE_ID


def fread_payload(name: str, ext: str, offset=0, length=512, drive=0):
    field = name.ljust(8).encode("ascii", "replace") + ext.ljust(3).encode("ascii", "replace")
    return bytes((drive,)) + field + offset.to_bytes(4, "little") + length.to_bytes(2, "little")


class Parse83Tests(unittest.TestCase):
    def test_valid_names(self):
        self.assertEqual(parse_83(b"HELLO   COM"), "HELLO.COM")
        self.assertEqual(parse_83(b"A       "  + b"   "), "A")
        self.assertEqual(parse_83(b"X$_-8   TXT"), "X$_-8.TXT")

    def test_traversal_and_junk_rejected(self):
        for raw in (b"../../..PWD", b"..      COM", b"A/B     COM",
                    b"A\\B     COM", b"HE LLO  COM", b"hello   com",
                    b"\x00AAAAAAACOM", b"           "):
            self.assertIsNone(parse_83(raw), raw)


class FreadTests(ServerFixture):
    """ServerFixture volume: HELLO.COM (36 x 0xC9), about.txt ('hi'),
    longfilename.markdown ('x')."""

    def bind(self):
        self.rpc(p.FHELLO, hello_payload())

    def test_read_at_offset(self):
        self.bind()
        fn, body = self.rpc(p.FREAD, fread_payload("HELLO", "COM", offset=9, length=16))
        self.assertEqual(fn, p.FREAD | p.FRESP)
        self.assertEqual(body[0], p.ROK)
        self.assertEqual(int.from_bytes(body[1:3], "little"), 16)
        self.assertEqual(body[3:], b"\xc9" * 16)

    def test_short_read_at_eof(self):
        self.bind()
        fn, body = self.rpc(p.FREAD, fread_payload("HELLO", "COM", offset=30, length=512))
        self.assertEqual(body[0], p.ROK)
        self.assertEqual(int.from_bytes(body[1:3], "little"), 6)

    def test_zero_bytes_past_eof_is_ok(self):
        self.bind()
        fn, body = self.rpc(p.FREAD, fread_payload("HELLO", "COM", offset=4096))
        self.assertEqual(body[0], p.ROK)
        self.assertEqual(int.from_bytes(body[1:3], "little"), 0)
        self.assertEqual(body[3:], b"")

    def test_repeat_read_identical(self):
        self.bind()
        req = fread_payload("ABOUT", "TXT")
        first = self.server.handle_frame(self.session, p.FREAD, req)
        second = self.server.handle_frame(self.session, p.FREAD, req)
        self.assertEqual(first, second)

    def test_file_not_found(self):
        self.bind()
        fn, body = self.rpc(p.FREAD, fread_payload("NOPE", "COM"))
        self.assertEqual(body[0], p.RFNF)
        self.assertEqual(self.log_records()[-1]["result"], "file-not-found")

    def test_traversal_is_bad_request_and_untouched(self):
        self.bind()
        fn, body = self.rpc(p.FREAD, fread_payload("../../..", "PWD"))
        self.assertEqual(body[0], p.RBADREQ)
        self.assertEqual(self.log_records()[-1]["reason"], "bad 8.3 name")

    def test_unbound_drive(self):
        self.bind()
        fn, body = self.rpc(p.FREAD, fread_payload("HELLO", "COM", drive=3))
        self.assertEqual(body[0], p.RUNBND)

    def test_before_hello_is_bad_request(self):
        fn, body = self.rpc(p.FREAD, fread_payload("HELLO", "COM"))
        self.assertEqual(body[0], p.RBADREQ)

    def test_oracle_record_shape(self):
        self.bind()
        self.rpc(p.FREAD, fread_payload("HELLO", "COM", offset=0, length=512))
        rec = self.log_records()[-1]
        self.assertEqual(rec["verb"], "fread")
        self.assertEqual(rec["machine_id"], MACHINE_ID)
        self.assertEqual((rec["drive"], rec["file"]), ("A", "HELLO.COM"))
        self.assertEqual((rec["offset"], rec["requested"], rec["actual"]),
                         (0, 512, 36))
        self.assertEqual(rec["result"], "ok")

    def test_malformed_length_is_bad_request(self):
        self.bind()
        fn, body = self.rpc(p.FREAD, b"\x00short")
        self.assertEqual(body[0], p.RBADREQ)


if __name__ == "__main__":
    unittest.main()
