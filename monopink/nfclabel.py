"""Python model of the label side of the NFC protocol (firmware/src/nfc.c).

The hardware simulator (``--sim``) uses it to answer the "MPNW" test, and the
tests run it side by side with the real C code (native build) to make sure
both behave identically.
"""
import struct

from . import codec, nfc
from .image import pixels_to_planes

ST_READY, ST_RECEIVING, ST_COMPLETE, ST_ERROR = range(4)
E_OK, E_CHIP, E_HEADER, E_PART_CRC, E_ORDER, E_TOO_BIG, E_STREAM_CRC, E_DECODE = range(8)
NOTHING, PART_OK, IMAGE, FAILED = range(4)


class LabelModel:
    def __init__(self, fw_version=0x14):
        self.fw_version = fw_version
        self.flash_desc = None          # copy written when a transfer ends
        self.ram_desc = None            # kept while sleeping, lost on power loss
        self.staging = bytearray(b"\xff" * nfc.STAGING_SIZE)
        self.area = bytearray(nfc.USER_BYTES)
        self.planes = None              # last decoded (bw, red)
        self.flash_desc_writes = 0

    # ---- state -------------------------------------------------------
    @staticmethod
    def _empty():
        return dict(id=0, count=0, next=0, total=0, scrc=0, chunk=0, state=ST_READY, err=E_OK)

    def _load(self):
        if self.ram_desc is None:
            self.ram_desc = dict(self.flash_desc) if self.flash_desc else self._empty()
        return self.ram_desc

    def _save(self, d):
        f = self.flash_desc
        if d["state"] in (ST_COMPLETE, ST_ERROR) and not (f and f["id"] == d["id"] and f["state"] == d["state"]):
            self.flash_desc = dict(d)
            self.flash_desc_writes += 1

    def power_loss(self):
        self.ram_desc = None
        self.prepare()

    def status(self):
        d = self._load()
        return struct.pack("<2sBBBBHBBHHBB", b"MS", nfc.PROTO, self.fw_version, d["state"], d["err"],
                           d["id"], d["next"], d["count"], nfc.MAX_PART_DATA, nfc.STAGING_SIZE, 1, 0)

    def _write_status(self):
        rec = nfc.t2t_area(nfc.ndef_record(2, nfc.STATUS_TYPE, self.status()))
        self.area[0:32] = (rec + bytes(32))[:32]

    def prepare(self):
        """Boot: announce the current status (keeps a pending transfer)."""
        self._write_status()

    # ---- one phone visit ------------------------------------------------
    def phone_write(self, area):
        self.area[:len(area)] = area
        return self.process()

    def _find_part(self):
        for tnf, rtype, payload in nfc.parse_t2t(bytes(self.area)):
            if tnf == 2 and rtype == nfc.PART_TYPE:
                return payload
        return None

    def _handle_part(self, d, p):
        if len(p) < nfc.PART_HDR or p[:2] != b"MK" or p[2] != nfc.PROTO:
            return E_HEADER, False
        pid, idx, count, total, scrc, pcrc, chunk = struct.unpack("<HBBHHHH", p[3:15])
        data = p[nfc.PART_HDR:]
        if total > nfc.STAGING_SIZE:
            return E_TOO_BIG, False
        if (count == 0 or idx >= count or chunk == 0 or chunk > nfc.MAX_PART_DATA
                or chunk * (count - 1) >= total or chunk * count < total):
            return E_HEADER, False
        expect = chunk if idx + 1 < count else total - chunk * (count - 1)
        if len(data) != expect:
            return E_HEADER, False
        same = d["id"] == pid and d["count"] == count
        if idx == 0 and same and d["state"] == ST_COMPLETE:
            return E_OK, False
        if idx == 0 and not (same and d["state"] == ST_RECEIVING):
            d.update(state=ST_RECEIVING, id=pid, count=count, next=0, total=total, scrc=scrc, chunk=chunk)
        elif not same or d["state"] != ST_RECEIVING:
            return E_ORDER, False
        if idx < d["next"]:
            return E_OK, False
        if idx > d["next"]:
            return E_ORDER, False
        self.staging[chunk * idx:chunk * idx + len(data)] = data
        if codec.crc16(data) != pcrc:
            return E_PART_CRC, False
        d["next"] = idx + 1
        d["state"] = ST_RECEIVING
        return E_OK, True

    def process(self):
        d = self._load()
        p = self._find_part()
        if p is None:
            self._write_status()
            return NOTHING
        err, stored = self._handle_part(d, p)
        d["err"] = err
        if err == E_ORDER and d["state"] != ST_RECEIVING:
            d["next"] = 0
        if err == E_OK and d["next"] == d["count"] and d["state"] == ST_RECEIVING:
            stream = bytes(self.staging[:d["total"]])
            if codec.crc16(stream) != d["scrc"]:
                d["err"] = E_STREAM_CRC
            else:
                try:
                    self.planes = pixels_to_planes(codec.decode(stream))
                except ValueError:
                    d["err"] = E_DECODE
            d["state"] = ST_ERROR if d["err"] else ST_COMPLETE
        self._save(d)
        self._write_status()
        if d["err"]:
            return FAILED
        if not stored:
            return NOTHING
        return IMAGE if d["state"] == ST_COMPLETE else PART_OK
