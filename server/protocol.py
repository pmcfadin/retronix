"""RetroNix wire protocol v0 — server-side constants and frame codec.

Mirrored in machine/protocol.inc; the two files MUST stay in lockstep.
Frame shape and semantics: ADR-0003. HELLO reconciliation: ADR-0005.

Frame: [version][function][len-lo][len-hi][payload...][checksum]
checksum = two's complement of the 8-bit sum of every preceding byte,
so summing an entire frame (checksum included) yields 0.
"""

PVER = 0x01  # protocol version 0 wire tag

# Function codes — requests (machine -> server)
FHELLO = 0x01
FDIR = 0x02

# Responses carry (request code | 0x80); payload byte 0 is the result code.
FRESP = 0x80
FERR = 0xFF  # bad-frame response (request code unknowable)

# Result codes — closed v0 table
ROK = 0x00
RBADFRM = 0x01  # checksum/length failure
RUNKMCH = 0x02  # HELLO from a machine ID with no profile
RUNBND = 0x03   # DIR for a drive letter the map does not bind
RBADREQ = 0x04  # well-framed but malformed payload

RESULT_NAMES = {
    ROK: "ok",
    RBADFRM: "bad-frame",
    RUNKMCH: "unknown-machine",
    RUNBND: "unbound-drive",
    RBADREQ: "bad-request",
}

HEADER_LEN = 4
MAX_PAYLOAD = 0xFFFF


class FrameError(Exception):
    """Raised when an incoming frame fails length or checksum validation."""


def checksum(data: bytes) -> int:
    return (-sum(data)) & 0xFF


def encode(function: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload too large for a v0 frame")
    head = bytes((PVER, function, len(payload) & 0xFF, len(payload) >> 8))
    body = head + payload
    return body + bytes((checksum(body),))


def decode(frame: bytes) -> tuple[int, bytes]:
    """Return (function, payload) or raise FrameError."""
    if len(frame) < HEADER_LEN + 1:
        raise FrameError("frame shorter than header + checksum")
    if frame[0] != PVER:
        raise FrameError(f"unknown protocol version {frame[0]:#x}")
    declared = frame[2] | (frame[3] << 8)
    if len(frame) != HEADER_LEN + declared + 1:
        raise FrameError("length field does not match frame size")
    if sum(frame) & 0xFF != 0:
        raise FrameError("checksum mismatch")
    return frame[1], frame[4:-1]


def read_frame(recv) -> tuple[int, bytes]:
    """Read one frame from a blocking byte source.

    `recv(n)` must return exactly n bytes or raise. Returns (function, payload);
    raises FrameError on validation failure.
    """
    head = recv(HEADER_LEN)
    declared = head[2] | (head[3] << 8)
    rest = recv(declared + 1)
    frame = head + rest
    # decode revalidates version/length and verifies the checksum
    return decode(frame)
