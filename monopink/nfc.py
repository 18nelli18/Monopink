"""NFC picture upload protocol (host side, mirrors firmware/src/nfc.c).

The phone (Web NFC) writes one NDEF message per tap:
    MIME record "x/mpk", payload = 15-byte part header + data
and the label answers with a MIME record "x/mps" (16-byte status).
Used by the tests and by the host-simulated upload (``monopink nfc-send``);
docs/nfc/codec.js + nfc.js implement the phone side in the browser, and
nfclabel.py is a Python model of the label side (for --sim).
"""
import os
import struct

from . import codec

PART_TYPE = b"x/mpk"
STATUS_TYPE = b"x/mps"
PROTO = 1
PART_HDR = 15
USER_BYTES = 872            # CC E1 10 6D 00
MAX_PART_DATA = USER_BYTES - 40     # margin under the Android NDEF capacity
STAGING_SIZE = 0x1800

STATES = {0: "ready", 1: "receiving", 2: "complete", 3: "error"}
ERRORS = {0: "ok", 1: "chip", 2: "header", 3: "part_crc", 4: "order",
          5: "too_big", 6: "stream_crc", 7: "decode"}


def split_stream(stream, chunk=MAX_PART_DATA, image_id=None):
    """Return the list of part payloads for a compressed stream."""
    if len(stream) > STAGING_SIZE:
        raise ValueError(f"stream too big ({len(stream)} > {STAGING_SIZE} bytes)")
    if image_id is None:
        image_id = int.from_bytes(os.urandom(2), "little")
    count = max(1, -(-len(stream) // chunk))
    if count > 255:
        raise ValueError("too many parts")
    scrc = codec.crc16(stream)
    parts = []
    for i in range(count):
        data = stream[i * chunk:(i + 1) * chunk]
        hdr = b"MK" + struct.pack("<BHBBHHHH", PROTO, image_id, i, count, len(stream),
                                  scrc, codec.crc16(data), chunk)
        parts.append(hdr + data)
    return parts


def ndef_record(tnf, rtype, payload, mb=True, me=True):
    short = len(payload) < 256
    hdr = (0x80 if mb else 0) | (0x40 if me else 0) | (0x10 if short else 0) | tnf
    out = bytes([hdr, len(rtype)])
    out += bytes([len(payload)]) if short else struct.pack(">I", len(payload))
    return out + rtype + payload


def t2t_area(message):
    """Type 2 Tag data area: NDEF TLV + terminator (what the phone writes)."""
    if len(message) < 0xFF:
        tlv = bytes([0x03, len(message)])
    else:
        tlv = bytes([0x03, 0xFF]) + struct.pack(">H", len(message))
    return tlv + message + b"\xfe"


def part_area(payload):
    return t2t_area(ndef_record(2, PART_TYPE, payload))


def parse_t2t(area):
    """Records of the NDEF message in a T2T data area: [(tnf, type, payload)]."""
    off = 0
    while off < len(area):
        t = area[off]
        off += 1
        if t == 0x00:
            continue
        if t == 0xFE:
            return []
        n = area[off]
        off += 1
        if n == 0xFF:
            n = struct.unpack(">H", area[off:off + 2])[0]
            off += 2
        if t == 0x03:
            return _parse_records(area[off:off + n])
        off += n
    return []


def _parse_records(msg):
    out, off = [], 0
    while off + 3 <= len(msg):
        hdr, tl = msg[off], msg[off + 1]
        if hdr & 0x10:
            pl = msg[off + 2]
            p = off + 3
        else:
            pl = struct.unpack(">I", msg[off + 2:off + 6])[0]
            p = off + 6
        il = 0
        if hdr & 0x08:
            il = msg[p]
            p += 1
        rtype = msg[p:p + tl]
        payload = msg[p + tl + il:p + tl + il + pl]
        out.append((hdr & 7, rtype, payload))
        off = p + tl + il + pl
        if hdr & 0x40:
            break
    return out


def parse_status(payload):
    if len(payload) < 16 or payload[:2] != b"MS":
        return None
    return {
        "proto": payload[2],
        "firmware": f"{payload[3] >> 4}.{payload[3] & 15}",
        "state": STATES.get(payload[4], payload[4]),
        "error": ERRORS.get(payload[5], payload[5]),
        "image_id": struct.unpack("<H", payload[6:8])[0],
        "next": payload[8],
        "count": payload[9],
        "max_part": struct.unpack("<H", payload[10:12])[0],
        "max_stream": struct.unpack("<H", payload[12:14])[0],
    }


def status_from_area(area):
    for tnf, rtype, payload in parse_t2t(area):
        if tnf == 2 and rtype == STATUS_TYPE:
            return parse_status(payload)
    return None


def encode_planes_pixels(pixels, chunk=MAX_PART_DATA, image_id=None):
    """Compress panel pixels and split them: returns (stream, parts)."""
    stream = codec.encode(pixels)
    return stream, split_stream(stream, chunk, image_id)
