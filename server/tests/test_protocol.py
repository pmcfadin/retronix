import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import protocol as p


class FrameCodecTests(unittest.TestCase):
    def test_roundtrip(self):
        for payload in (b"", b"\x00", bytes(range(256)), b"x" * 5000):
            frame = p.encode(p.FDIR, payload)
            fn, out = p.decode(frame)
            self.assertEqual(fn, p.FDIR)
            self.assertEqual(out, payload)

    def test_frame_sums_to_zero(self):
        frame = p.encode(p.FHELLO, b"\x01\x02\x03")
        self.assertEqual(sum(frame) & 0xFF, 0)

    def test_corrupt_checksum_rejected(self):
        frame = bytearray(p.encode(p.FDIR, b"abc"))
        frame[-1] ^= 0xFF
        with self.assertRaises(p.FrameError):
            p.decode(bytes(frame))

    def test_corrupt_payload_rejected(self):
        frame = bytearray(p.encode(p.FDIR, b"abc"))
        frame[5] ^= 0x01
        with self.assertRaises(p.FrameError):
            p.decode(bytes(frame))

    def test_length_mismatch_rejected(self):
        frame = p.encode(p.FDIR, b"abc")
        with self.assertRaises(p.FrameError):
            p.decode(frame + b"\x00")
        with self.assertRaises(p.FrameError):
            p.decode(frame[:-2])

    def test_bad_version_rejected(self):
        frame = bytearray(p.encode(p.FDIR, b""))
        frame[0] = 0x7E
        with self.assertRaises(p.FrameError):
            p.decode(bytes(frame))

    def test_read_frame_from_stream(self):
        frame = p.encode(p.FHELLO, b"payload")
        buf = bytearray(frame)

        def recv(n):
            out = bytes(buf[:n])
            del buf[:n]
            return out

        fn, payload = p.read_frame(recv)
        self.assertEqual((fn, payload), (p.FHELLO, b"payload"))
        self.assertEqual(len(buf), 0)


if __name__ == "__main__":
    unittest.main()
