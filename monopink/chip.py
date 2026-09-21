"""CC2510 operations over a debug probe: identify, erase, program, verify, run.

Flash programming uses the page routine documented by TI (SWRA124) and
ported by fishpepper to CCLib: the page is staged in XDATA RAM, a tiny 8051
routine is copied next to it and executed from RAM.  No DMA needed.
"""
import time

from . import layout as L

# Debug instruction table for the CC111x / CC251x family (CCLib "version 2")
INSTR_TABLE_VERSION = 2
INSTR_TABLE_CC251X = [0x44, 0x4C, 0x24, 0x1D, 0x55, 0x56, 0x57, 0x68, 0x28, 0x34, 0x5C, 0x14]

# Debug status bits (SWRA124)
ST_CHIP_ERASE_DONE = 0x80
ST_PCON_IDLE = 0x40
ST_CPU_HALTED = 0x20
ST_POWER_MODE_0 = 0x10
ST_HALT_STATUS = 0x08
ST_DEBUG_LOCKED = 0x04
ST_OSC_STABLE = 0x02
ST_STACK_OVERFLOW = 0x01

STATUS_BITS = [
    (0x80, "CHIP_ERASE_DONE"), (0x40, "PCON_IDLE"), (0x20, "CPU_HALTED"),
    (0x10, "POWER_MODE_0"), (0x08, "HALT_STATUS"), (0x04, "DEBUG_LOCKED"),
    (0x02, "OSCILLATOR_STABLE"), (0x01, "STACK_OVERFLOW"),
]

CHIP_NAMES = {0x81: "CC2510", 0x01: "CC1110", 0x91: "CC2511", 0x11: "CC1111"}


class TagError(Exception):
    """Problem with the label itself.  `key` is an i18n message key."""

    def __init__(self, key, **kw):
        super().__init__(key)
        self.key = key
        self.kw = kw


def decode_status(st):
    return [name for bit, name in STATUS_BITS if st & bit]


def parse_mailbox(mb):
    if not mb:
        return {"state": None, "error": None, "refresh_ms": None, "total_ms": None, "finished": False}
    return {
        "state": mb[4],
        "error": mb[5],
        "refresh_ms": mb[6] | (mb[7] << 8),
        "total_ms": mb[8] | (mb[9] << 8),
        "fw_version": mb[10],
        "boots": mb[14],
        "finished": mb[4] in (L.ST_EPD_OFF, L.ST_IDLE_HOLD),
    }


def page_routine(addr, erase=True):
    """8051 routine (run from XDATA) that programs one 1 KB flash page."""
    wpp = L.PAGE_SIZE // L.WORD_SIZE
    r = [
        0x75, 0xAD, ((addr >> 8) // L.WORD_SIZE) & 0x7E,   # MOV FADDRH,#page
        0x75, 0xAC, 0x00,                                  # MOV FADDRL,#0
    ]
    if erase:
        r += [
            0x75, 0xAE, 0x01,                              # MOV FLC,#01 (erase)
            0xE5, 0xAE,                                    # wait: MOV A,FLC
            0x20, 0xE7, 0xFB,                              #       JB ACC.7,wait
        ]
    r += [
        0x90, L.XDATA_BUF >> 8, L.XDATA_BUF & 0xFF,        # MOV DPTR,#buffer
        0x7F, (wpp >> 8) & 0xFF,                           # MOV R7,#hi
        0x7E, wpp & 0xFF,                                  # MOV R6,#lo
        0x75, 0xAE, 0x02,                                  # MOV FLC,#02 (write)
        0x7D, L.WORD_SIZE,                                 # loop: MOV R5,#2
        0xE0,                                              # word: MOVX A,@DPTR
        0xA3,                                              #       INC DPTR
        0xF5, 0xAF,                                        #       MOV FWDATA,A
        0xDD, 0xFA,                                        #       DJNZ R5,word
        0xE5, 0xAE,                                        # busy: MOV A,FLC
        0x20, 0xE6, 0xFB,                                  #       JB ACC.6,busy
        0xDE, 0xF1,                                        #       DJNZ R6,loop
        0xDF, 0xEF,                                        #       DJNZ R7,loop
        0xA5,                                              # breakpoint -> halt
    ]
    return bytes(r)


class CC2510:
    def __init__(self, probe, rep=None):
        self.p = probe
        self.rep = rep
        self.chip_id = None
        self.status = None
        self._locked = True

    # ------------------------------------------------------------ helpers
    def _cancel_point(self):
        if self.rep is not None:
            self.rep.check_cancel()

    def _progress(self, done, total):
        if self.rep is not None:
            self.rep.progress(done, total)

    # ------------------------------------------------------------ identify
    def connect(self):
        """Enter debug mode and identify the chip.  Raises TagError."""
        from .probe import ProbeError, ERR_NOT_WIRED
        if self.p.instr_table_version() != INSTR_TABLE_VERSION:
            self.p.update_instr_table(INSTR_TABLE_VERSION, INSTR_TABLE_CC251X)
        # Measured on hardware: a chip sleeping in PM3 often misses the first
        # debug-entry sequence (its regulator is off), the reset wakes it up
        # and the next attempt works.  So try a few times.
        cid = 0
        for attempt in range(4):
            try:
                self.p.enter()
                cid = self.p.chip_id()
            except ProbeError as e:
                if e.code != ERR_NOT_WIRED:
                    raise
                cid = 0
            if cid not in (0x0000, 0xFFFF):
                break
            time.sleep(0.05 + 0.1 * attempt)
        if cid in (0x0000, 0xFFFF):
            raise TagError("tag.not_responding")
        if (cid >> 8) != 0x81:
            raise TagError("tag.unsupported_chip", chip=f"0x{cid:04x}")
        self.chip_id = cid
        self.refresh_status()
        return self.info()

    def info(self):
        st = self.status
        return {
            "chip_id": f"0x{self.chip_id:04x}",
            "chip": CHIP_NAMES.get(self.chip_id >> 8, "?"),
            "revision": self.chip_id & 0xFF,
            "status": st,
            "status_bits": decode_status(st),
            "locked": self.locked,
        }

    def refresh_status(self):
        """Read the debug status and find out whether the chip is locked.

        Measured on a real CC2510: right after entering debug mode the status
        reports DEBUG_LOCKED until the first debug instruction is executed,
        even on an unlocked chip.  So we run harmless instructions first: a
        locked chip refuses them (only CHIP_ERASE / status / chip ID work),
        which is the real test.
        """
        self.p.exec(0x00)                                    # NOP
        works = self.p.exec(0x74, 0xA5) == 0xA5 and self.p.exec(0x74, 0x5A) == 0x5A
        self.status = self.p.status()
        self._locked = not works
        return self.status

    @property
    def locked(self):
        return self._locked

    def firmware_info(self):
        """Return the MonopInk firmware version installed, or None."""
        if self.locked:
            return None
        raw = self.p.read_code(L.FW_INFO_ADDR, 16)
        if raw[:8] != L.FW_MAGIC:
            start = self.p.read_code(0, 16)
            blank = all(b == 0xFF for b in raw + start)
            return {"installed": False, "blank": blank}
        return {
            "installed": True,
            "version": f"{raw[8]}.{raw[9]}",
            "layout": raw[10],
            "width": raw[11],
            "height": (raw[12] << 8) | raw[13],
        }

    # ------------------------------------------------------------ erase
    def mass_erase(self):
        """Chip erase: wipes the flash AND clears the debug lock."""
        self.p.enter()
        self.p.chip_erase()
        time.sleep(0.2)
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.p.status() & ST_CHIP_ERASE_DONE:
                break
            time.sleep(0.05)
        time.sleep(0.1)
        # the lock state is re-read at reset
        self.p.enter()
        self.refresh_status()
        if self.locked:
            raise TagError("tag.erase_failed")
        if self.p.read_code(0, 64) != b"\xff" * 64:
            raise TagError("tag.erase_failed")

    # ------------------------------------------------------------ flash
    def write_page(self, addr, data, erase=True):
        if addr % L.PAGE_SIZE or len(data) != L.PAGE_SIZE:
            raise ValueError("write_page needs one aligned 1 KB page")
        self.p.halt()
        self.p.write_xdata(L.XDATA_BUF, data)
        self.p.write_xdata(L.XDATA_ROUTINE, page_routine(addr, erase))
        self.p.exec(0x75, 0xC7, 0x51)                     # MOV MEMCTR,#51h
        self.p.exec(0x02, L.XDATA_ROUTINE >> 8, L.XDATA_ROUTINE & 0xFF)  # LJMP routine
        self.p.resume()
        deadline = time.time() + 3
        while True:
            if self.p.status() & ST_CPU_HALTED:
                break
            if time.time() > deadline:
                raise TagError("tag.flash_timeout", addr=f"0x{addr:04x}")
            time.sleep(0.01)
        self.p.halt()

    def program(self, pages, verify=True):
        """pages: {page_address: 1024 bytes}.  Writes, then verifies."""
        addrs = sorted(pages)
        total = len(addrs) * (2 if verify else 1)
        done = 0
        self.p.enter()
        for a in addrs:
            self._cancel_point()
            self.write_page(a, pages[a])
            done += 1
            self._progress(done, total)
        if verify:
            self.p.enter()          # reset: nothing stale in the flash cache
            for a in addrs:
                self._cancel_point()
                got = self.p.read_code(a, L.PAGE_SIZE)
                if got != bytes(pages[a]):
                    bad = next(i for i in range(L.PAGE_SIZE) if got[i] != pages[a][i])
                    raise TagError("tag.verify_failed", addr=f"0x{a + bad:04x}")
                done += 1
                self._progress(done, total)

    def read_flash(self, addr=0, size=L.FLASH_SIZE):
        out = bytearray()
        step = 1024
        for off in range(0, size, step):
            self._cancel_point()
            out += self.p.read_code(addr + off, min(step, size - off))
            self._progress(off + step, size)
        return bytes(out)

    # ------------------------------------------------------------ run
    def _read_mailbox(self):
        """Read the firmware mailbox from a halted CPU, preserving A/DPTR."""
        a = self.p.exec(0x00)                  # NOP -> returns A
        dpl = self.p.exec(0xE5, 0x82)          # MOV A,DPL
        dph = self.p.exec(0xE5, 0x83)          # MOV A,DPH
        mb = self.p.read_xdata(L.MAILBOX_ADDR, L.MAILBOX_SIZE)
        self.p.exec(0x90, dph, dpl)            # MOV DPTR,#saved
        self.p.exec(0x74, a)                   # MOV A,#saved
        return mb

    def run_monitored(self, on_state=None, timeout=90):
        """Reset, run the firmware in debug mode and follow the refresh.

        Returns a dict with the final state, error code and timings.
        """
        self.p.enter()
        self.p.write_xdata(L.MAILBOX_ADDR, L.MAILBOX_HOLD + bytes(L.MAILBOX_SIZE - 4))
        self.p.resume()
        t0 = time.time()
        last = None
        mb = None
        while time.time() - t0 < timeout:
            self._cancel_point()
            time.sleep(0.4)
            self.p.halt()
            mb = self._read_mailbox()
            self.p.resume()
            state = mb[4]
            if state != last:
                last = state
                if on_state:
                    on_state(state, time.time() - t0)
            if state in (L.ST_EPD_OFF, L.ST_IDLE_HOLD):
                break
        result = parse_mailbox(mb)
        result["elapsed"] = round(time.time() - t0, 1)
        return result

    def start_boot_test(self):
        """Plain reset (no debug mode), like a label on batteries.

        The firmware is told through the RAM (which survives a reset) to stay
        awake at the end instead of entering PM3, so that the result can be
        read after the next debug entry."""
        self.p.enter()
        self.p.write_xdata(L.MAILBOX_ADDR, L.MAILBOX_BOOT_TEST + bytes(L.MAILBOX_SIZE - 4))
        self.p.reset_run(hold=False)

    def read_boot_test(self):
        self.connect()
        return parse_mailbox(self.p.read_xdata(L.MAILBOX_ADDR, L.MAILBOX_SIZE))
