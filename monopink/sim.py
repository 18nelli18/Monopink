"""Hardware simulator: a fake Pico probe wired to a fake CC2510 label.

Used by `--sim` (try the whole workflow without hardware) and by the tests.
It emulates just enough of the chip for the real code paths in chip.py to
run: debug lock, chip erase, the flash page routine, XDATA/CODE access and
the MonopInk firmware's refresh sequence (sped up).
"""
import os
import random
import threading
import time

from . import layout as L
from .probe import ProbeError, ERR_NOT_WIRED, READY

REFRESH_SECONDS = 4.0      # the real panel takes ~15 s


class SimChip:
    def __init__(self):
        rnd = random.Random(2510)
        # "SES firmware": random bytes, locked
        self.flash = bytearray(rnd.getrandbits(8) for _ in range(12 * 1024)) + \
            bytearray(b"\xff" * (L.FLASH_SIZE - 12 * 1024))
        self.locked = True
        self.connected = True
        self.chip_id = 0x8104
        self.displayed = None       # image planes last "shown"
        from .nfclabel import LabelModel
        self.nfc = LabelModel()     # the NTAG + firmware NFC protocol
        self.nfc_fd_pullup = True   # board pull-up on FD (wake-up mode 1)
        self.nfc_result = 0
        self.power_up()
        self.reset()

    def power_up(self):
        self.xdata = bytearray(os.urandom(0x10000))
        self.pm3 = False
        self.run_started = None

    def reset(self):
        """External reset.  Like the real chip, the RAM survives a reset,
        except after PM3 where (measured) the mailbox reads back as zeros."""
        if not hasattr(self, "xdata"):
            self.power_up()
        self._update_run()
        if self.pm3:
            self.xdata[L.MAILBOX_ADDR:L.MAILBOX_ADDR + 16] = bytes(16)
            self.pm3 = False
        self.sfr = {}
        self.a = 0
        self.dptr = 0
        self.pc = 0
        self.halted = True
        self.debug = False
        self.erase_done = False
        self.run_mode = "normal"
        # real CC2510 quirk: DEBUG_LOCKED reads 1 after reset until the first
        # debug instruction, even when the chip is not locked
        self.stale_lock = True
        self.run_started = None

    # firmware emulation ------------------------------------------------
    def firmware_present(self):
        return self.flash[L.FW_INFO_ADDR:L.FW_INFO_ADDR + 8] == L.FW_MAGIC

    def _update_run(self):
        if self.run_started is None:
            return
        t = time.time() - self.run_started
        mb = self.xdata
        base = L.MAILBOX_ADDR
        hold = self.run_mode != "normal"
        if self.run_mode == "nfcdiag":
            mb[base + 4] = L.ST_NFC_DIAG_DONE
            return
        if self.run_mode == "nfctest" and self.nfc_result != 2:
            mb[base + 4] = L.ST_NFC_DONE
            return
        if t < 0.3:
            st = L.ST_BOOT
        elif t < 1.3:
            st = L.ST_EPD_READY
        elif t < 1.5:
            st = L.ST_DATA_SENT
        elif t < 1.5 + REFRESH_SECONDS:
            st = L.ST_REFRESHING
        elif t < 1.8 + REFRESH_SECONDS:
            st = L.ST_REFRESH_DONE
        else:
            st = L.ST_IDLE_HOLD if hold else L.ST_EPD_OFF
            if self.run_mode == "nfctest":
                st = L.ST_NFC_DONE
        mb[base + 4] = st
        mb[base + 5] = 0
        mb[base + 10] = 0x10
        if st >= L.ST_REFRESH_DONE:
            ms = int(REFRESH_SECONDS * 1000) + 120
            mb[base + 6], mb[base + 7] = ms & 0xFF, ms >> 8
            total = int((1.8 + REFRESH_SECONDS) * 1000)
            mb[base + 8], mb[base + 9] = total & 0xFF, total >> 8
            bw = bytes(self.flash[L.IMG_BW_ADDR:L.IMG_BW_ADDR + L.PLANE_SIZE])
            red = bytes(self.flash[L.IMG_R_ADDR:L.IMG_R_ADDR + L.PLANE_SIZE])
            self.displayed = (bw, red)
        if st == L.ST_EPD_OFF:          # normal boot: the chip is now in PM3
            self.pm3 = True
            self.run_started = None

    def start(self):
        """CPU starts executing from PC."""
        self.halted = False
        if self.pc == L.XDATA_ROUTINE:
            self._flash_routine()
            self.halted = True
        elif self.pc == 0 and self.firmware_present():
            # boot from reset; a later resume continues where it stopped
            base = L.MAILBOX_ADDR
            magic = bytes(self.xdata[base:base + 4])
            self.run_mode = {L.MAILBOX_HOLD: "watched", L.MAILBOX_BOOT_TEST: "test",
                             L.MAILBOX_NFC_DIAG: "nfcdiag", L.MAILBOX_NFC_TEST: "nfctest"}.get(magic, "normal")
            length = self.xdata[base + 12] | (self.xdata[base + 13] << 8)
            self.xdata[base:base + 4] = bytes(4)          # firmware clears it
            self.xdata[base + 14] = (self.xdata[base + 14] + 1) & 0xFF
            self.run_started = time.time()
            self.pc = 0x0100
            if self.run_mode == "nfcdiag":
                self._nfc_diag()
            elif self.run_mode == "nfctest":
                self._nfc_test(length)

    # NFC ("MPNF" / "MPNW", firmware >= 1.3) -----------------------------
    def _nfc_diag(self):
        d = bytearray(b"\xee" * L.NFCDIAG_SIZE)
        d[0] = 0x01                                  # answers, 1k variant
        d[1] = d[2] = 1 if self.nfc_fd_pullup else 0
        d[3] = 8
        d[4] = 1 if self.nfc_fd_pullup else 2
        d[8:16] = bytes([0x01, 0x00, 0x00, 0x48, 0x08, 0x01, 0x00, 0x00])   # session regs
        d[0x10:0x20] = bytes([0x04, 0xA1, 0xB2, 0xC3, 0xD4, 0xE5, 0xF6, 0x80,
                              0x00, 0x00, 0x00, 0x00, 0xE1, 0x10, 0x6D, 0x00])
        d[0x20:0x30] = bytes(8) + bytes([0, 0, 0, 0, 0, 0, 0, 0xFF])       # dyn. lock, AUTH0
        d[0x30:0x40] = bytes([0x00, 0, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF, 0, 0, 0, 0, 0x07, 0, 0, 0])
        d[0x40:0x50] = bytes([0x01, 0x00, 0xF8, 0x48, 0x08, 0x01, 0x00, 0x00]) + bytes(8)
        self.nfc.prepare()
        d[0x50:0x90] = self.nfc.area[0:64]
        self.xdata[L.NFCDIAG_ADDR:L.NFCDIAG_ADDR + L.NFCDIAG_SIZE] = d

    def _nfc_test(self, length):
        area = bytes(self.xdata[L.XRAM_BUF_B:L.XRAM_BUF_B + min(length, 872)])
        self.nfc_result = self.nfc.phone_write(area)
        self.xdata[L.MAILBOX_ADDR + 11] = self.nfc_result
        self.xdata[L.XRAM_NFC_STATUS:L.XRAM_NFC_STATUS + 16] = self.nfc.status()
        self.xdata[L.XRAM_NFC_INFO:L.XRAM_NFC_INFO + 16] = bytes(16)
        if self.nfc_result == 2:                     # decoded: goes to the picture area
            bw, red = self.nfc.planes
            self.flash[L.IMG_BW_ADDR:L.IMG_BW_ADDR + L.PLANE_SIZE] = bw
            self.flash[L.IMG_R_ADDR:L.IMG_R_ADDR + L.PLANE_SIZE] = red

    def _flash_routine(self):
        r = self.xdata[L.XDATA_ROUTINE:L.XDATA_ROUTINE + 64]
        faddrh = r[2]
        addr = faddrh << 9
        erase = bytes(r[6:9]) == bytes([0x75, 0xAE, 0x01])
        page = self.xdata[L.XDATA_BUF:L.XDATA_BUF + L.PAGE_SIZE]
        if erase:
            self.flash[addr:addr + L.PAGE_SIZE] = b"\xff" * L.PAGE_SIZE
        for i in range(L.PAGE_SIZE):
            self.flash[addr + i] &= page[i]      # flash can only clear bits
        self.pc = L.XDATA_ROUTINE + len(r)

    def halt(self):
        self._update_run()
        self.halted = True

    def status(self):
        st = 0x02
        if self.halted:
            st |= 0x20
        if self.locked or self.stale_lock:
            st |= 0x04
        if self.erase_done:
            st |= 0x80
        return st

    def exec(self, op):
        if self.locked:
            return 0
        self.stale_lock = False
        o = op[0]
        if o == 0x00:
            pass
        elif o == 0x90:
            self.dptr = (op[1] << 8) | op[2]
        elif o == 0xE4:
            self.a = 0
        elif o == 0x93:
            self.a = self.flash[(self.a + self.dptr) & 0x7FFF]
        elif o == 0xA3:
            self.dptr = (self.dptr + 1) & 0xFFFF
        elif o == 0xE0:
            self.a = self.xdata[self.dptr]
        elif o == 0x74:
            self.a = op[1]
        elif o == 0xF0:
            self.xdata[self.dptr] = self.a
        elif o == 0x75:
            self.sfr[op[1]] = op[2]
        elif o == 0xE5:
            if op[1] == 0x82:
                self.a = self.dptr & 0xFF
            elif op[1] == 0x83:
                self.a = self.dptr >> 8
            else:
                self.a = self.sfr.get(op[1], 0)
        elif o == 0x02:
            self.pc = (op[1] << 8) | op[2]
        return self.a


class SimWorld:
    """Shared state: one simulated Pico + one simulated label."""

    def __init__(self):
        self.lock = threading.RLock()
        self.chip = SimChip()
        self.pico_fw = "cclib"          # 'cclib' | 'monopink' | 'blank'
        self.pico_board = "RP2040"
        self.bootsel = False
        self.bootsel_at = None
        self.pins = {"rst": 3, "dc": 4, "dd_i": 6, "dd_o": 7, "led": 25, "saved": False}
        # the label is really wired to these GPIOs
        self.wired = {"rst": 3, "dc": 4, "dd_i": 6, "dd_o": 7}
        self.port = "/dev/sim-pico"

    def reset(self):
        self.__init__()

    # "USB" side -----------------------------------------------------------
    def serial_ports(self):
        if self.bootsel or self.pico_fw == "blank":
            return []
        return [{"device": self.port, "vid": 0x2E8A, "pid": 0x000A,
                 "description": "Pico (simulated)", "is_pico": True}]

    def drives(self):
        if self.bootsel_at and time.time() >= self.bootsel_at:
            self.bootsel, self.bootsel_at = True, None
        if not self.bootsel:
            return []
        bid = "RPI-RP2" if self.pico_board == "RP2040" else "RP2350"
        return [{"path": "/Volumes/" + bid + " (simulated)", "board_id": bid}]

    def touch_1200(self, port):
        if port == self.port and self.pico_fw in ("cclib", "monopink"):
            self.bootsel_at = time.time() + 1.0

    def copy_uf2(self, drive, uf2_path):
        if not self.bootsel:
            raise OSError("drive vanished")
        time.sleep(0.8)
        self.pico_fw = "monopink"
        self.bootsel = False
        # a fresh firmware starts with the default pins
        self.pins = {"rst": 3, "dc": 4, "dd_i": 6, "dd_o": 7, "led": 25, "saved": False}

    def wiring_ok(self):
        p, w = self.pins, self.wired
        return (p["rst"], p["dc"], p["dd_i"]) == (w["rst"], w["dc"], w["dd_i"]) and \
            p["dd_o"] in (w["dd_o"], w["dd_i"])


class SimProbe:
    """Drop-in replacement for probe.Probe backed by a SimWorld."""

    simulated = True

    def __init__(self, world, port):
        if port != world.port or not world.serial_ports():
            raise ProbeError(f"no CCLib/MonopInk probe answering on {port}")
        self.w = world
        self.c = world.chip
        self.port = port
        self.kind = world.pico_fw
        self.version = 1 if self.kind == "monopink" else None
        self.table_version = 2 if self.kind == "monopink" else 1
        time.sleep(0.05)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def _io(self, n=1):
        time.sleep(0.0005 * n)

    def _chip(self):
        """Access to the chip through the debug lines."""
        self._io()
        if not (self.c.connected and self.w.wiring_ok()):
            if self.kind == "monopink":
                raise ProbeError("the CC2510 is not responding (wiring / power?)", code=ERR_NOT_WIRED)
            return None
        if not self.c.debug:
            self.c.reset()
            self.c.debug = True
        return self.c

    # identity / pins
    def identify(self):
        return self.kind, self.version

    @property
    def is_monopink(self):
        return self.kind == "monopink"

    def board(self):
        return self.w.pico_board if self.is_monopink else None

    def ping(self):
        return True

    def get_pins(self):
        return dict(self.w.pins) if self.is_monopink else None

    def set_pins(self, rst, dc, dd_i, dd_o, led=0xFE, save=True):
        if not self.is_monopink:
            raise ProbeError("pin setup needs the MonopInk probe firmware")
        pins = [rst, dc, dd_i, dd_o]
        if any(not 0 <= p <= 29 for p in pins) or len({rst, dc, dd_i}) < 3 or dd_o in (rst, dc):
            raise ProbeError("invalid pin assignment", code=0x10)
        self.w.pins = {"rst": rst, "dc": dc, "dd_i": dd_i, "dd_o": dd_o,
                       "led": 25 if led == 0xFE else (None if led == 0xFF else led),
                       "saved": bool(save)}

    def reset_pins(self):
        self.set_pins(3, 4, 6, 7, save=False)

    # debug interface
    def instr_table_version(self):
        return self.table_version

    def update_instr_table(self, version, table):
        self.table_version = version

    def enter(self):
        self._io()
        if self.c.connected and self.w.wiring_ok():
            self.c.reset()
            self.c.debug = True
        return 0

    def exit(self):
        c = self._chip()
        if c:
            c.start()
            c.debug = False
        return 0

    def chip_id(self):
        c = self._chip()
        return c.chip_id if c else 0

    def status(self):
        c = self._chip()
        return c.status() if c else 0

    def pc(self):
        c = self._chip()
        return c.pc if c else 0

    def halt(self):
        c = self._chip()
        if c:
            c.halt()
            return c.status()
        return 0

    def resume(self):
        c = self._chip()
        if c:
            c.start()
            return c.status()
        return 0

    def read_config(self):
        return 0x22

    def write_config(self, cfg):
        return self.status()

    def chip_erase(self):
        c = self._chip()
        if c:
            time.sleep(0.2)
            c.flash[:] = b"\xff" * L.FLASH_SIZE
            c.locked = False
            c.erase_done = True
            return c.status()
        return 0

    def exec(self, *op):
        c = self._chip()
        return c.exec(op) if c else 0

    def read_code(self, addr, n):
        c = self._chip()
        self._io(n // 64)
        if not c or c.locked:
            return bytes(n)
        c.dptr = addr + n
        return bytes(c.flash[(addr + i) & 0x7FFF] for i in range(n))

    def read_xdata(self, addr, n):
        c = self._chip()
        if not c or c.locked:
            return bytes(n)
        c.dptr = addr + n
        return bytes(c.xdata[addr:addr + n])

    def write_xdata(self, addr, data):
        c = self._chip()
        self._io(len(data) // 64)
        if not c or c.locked:
            return
        c.xdata[addr:addr + len(data)] = bytes(data)
        c.dptr = addr + len(data)

    def reset_run(self, hold=False):
        if self.c.connected and self.w.wiring_ok():
            self.c.reset()
            if not hold:
                self.c.start()

    def release(self):
        pass


_world = None


def world():
    global _world
    if _world is None:
        _world = SimWorld()
    return _world
