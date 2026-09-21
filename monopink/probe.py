"""Serial protocol of the debug probe.

Speaks the CCLib_proxy protocol (4-byte command, 3-byte answer), so it works
with the MonopInk probe firmware *and* with an original CCLib_proxy sketch.
MonopInk-only extensions (block transfers, pin setup...) are used when
available and emulated otherwise.
"""
import time

try:
    import serial
except ImportError:  # handled by the callers (friendly message)
    serial = None

CMD_ENTER = 0x01
CMD_EXIT = 0x02
CMD_CHIP_ID = 0x03
CMD_STATUS = 0x04
CMD_PC = 0x05
CMD_STEP = 0x06
CMD_EXEC_1 = 0x07
CMD_EXEC_2 = 0x08
CMD_EXEC_3 = 0x09
CMD_RD_CFG = 0x0B
CMD_WR_CFG = 0x0C
CMD_CHPERASE = 0x0D
CMD_RESUME = 0x0E
CMD_HALT = 0x0F
CMD_PING = 0xF0
CMD_INSTR_VER = 0xF1
CMD_INSTR_UPD = 0xF2
CMD_READ_CODE = 0xE1
CMD_READ_XDATA = 0xE2
CMD_WRITE_XDATA = 0xE3
CMD_RESET_RUN = 0xE4
CMD_RELEASE = 0xE5
CMD_SET_PINS = 0xE8
CMD_GET_PINS = 0xE9
CMD_RESET_PINS = 0xEA
CMD_IDENT = 0xEF

ANS_OK = 0x01
ANS_ERROR = 0x02
ANS_READY = 0x03

ERR_NOT_ACTIVE = 0x01
ERR_NOT_DEBUGGING = 0x02
ERR_NOT_WIRED = 0x03
ERR_TIMEOUT = 0x04
ERR_BAD_PINS = 0x10
ERR_UNKNOWN_CMD = 0xFF

READY = "READY"

LED_NONE = 0xFF
LED_DEFAULT = 0xFE


class ProbeError(IOError):
    """Error reported by (or while talking to) the probe."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class Probe:
    """A CCLib-compatible debug probe on a serial port."""

    simulated = False

    def __init__(self, port, timeout=2.0):
        if serial is None:
            raise ProbeError("pyserial is not installed (pip install pyserial)")
        try:
            self.ser = serial.Serial(port, 115200, timeout=timeout, write_timeout=timeout)
        except Exception as e:  # serial.SerialException, OSError...
            raise ProbeError(f"cannot open {port}: {e}")
        self.port = port
        self.kind = None          # 'monopink' | 'cclib'
        self.version = None
        self._sync()

    # ------------------------------------------------------------ plumbing
    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _sync(self):
        """Make sure both ends agree on frame boundaries."""
        time.sleep(0.05)
        self.ser.reset_input_buffer()
        for attempt in range(3):
            try:
                self.ser.write(bytes([CMD_PING, 0, 0, 0]))
                self.ser.flush()
                ans = self.ser.read(3)
                if ans == bytes([ANS_OK, 0, 0]):
                    return
            except Exception:
                pass
            # the probe may still be waiting for the payload of an
            # interrupted command: let its 2 s timeout expire
            time.sleep(2.2 if attempt == 0 else 0.5)
            self.ser.reset_input_buffer()
        self.close()
        raise ProbeError(f"no CCLib/MonopInk probe answering on {self.port}")

    def _read_exact(self, n):
        data = self.ser.read(n)
        if len(data) != n:
            raise ProbeError("the probe stopped answering (timeout)")
        return data

    def _read_frame(self):
        status, hi, lo = self._read_exact(3)
        if status == ANS_ERROR:
            raise ProbeError(self._error_text(lo), code=lo)
        if status == ANS_READY:
            return READY
        if status != ANS_OK:
            raise ProbeError(f"unexpected answer 0x{status:02x} from the probe")
        return (hi << 8) | lo

    @staticmethod
    def _error_text(code):
        return {
            ERR_NOT_ACTIVE: "debugger not initialised",
            ERR_NOT_DEBUGGING: "chip not in debug mode",
            ERR_NOT_WIRED: "the CC2510 is not responding (wiring / power?)",
            ERR_TIMEOUT: "transfer timeout",
            ERR_BAD_PINS: "invalid pin assignment",
            ERR_UNKNOWN_CMD: "command not supported by this probe firmware",
        }.get(code, f"probe error 0x{code:02x}")

    def command(self, cmd, c1=0, c2=0, c3=0):
        self.ser.write(bytes([cmd, c1 & 0xFF, c2 & 0xFF, c3 & 0xFF]))
        self.ser.flush()
        return self._read_frame()

    # ------------------------------------------------------------ identity
    def identify(self):
        """Return ('monopink', version) or ('cclib', None)."""
        try:
            v = self.command(CMD_IDENT)
        except ProbeError as e:
            if e.code == ERR_UNKNOWN_CMD:
                self.kind, self.version = "cclib", None
                return self.kind, self.version
            raise
        if (v >> 8) == ord("M"):
            self.kind, self.version = "monopink", v & 0xFF
        else:
            self.kind, self.version = "cclib", None
        return self.kind, self.version

    @property
    def is_monopink(self):
        if self.kind is None:
            self.identify()
        return self.kind == "monopink"

    def board(self):
        if not self.is_monopink:
            return None
        v = self.command(CMD_IDENT, 1) >> 8
        return {0x20: "RP2040", 0x35: "RP2350"}.get(v, f"0x{v:02x}")

    def ping(self):
        self.command(CMD_PING)
        return True

    # ------------------------------------------------------------ pins
    def get_pins(self):
        if not self.is_monopink:
            return None
        a = self.command(CMD_GET_PINS, 0)
        b = self.command(CMD_GET_PINS, 1)
        c = self.command(CMD_GET_PINS, 2)
        led = c >> 8
        return {
            "rst": a >> 8, "dc": a & 0xFF,
            "dd_i": b >> 8, "dd_o": b & 0xFF,
            "led": None if led == LED_NONE else led,
            "saved": bool(c & 0xFF),
        }

    def set_pins(self, rst, dc, dd_i, dd_o, led=LED_DEFAULT, save=True):
        if not self.is_monopink:
            raise ProbeError("pin setup needs the MonopInk probe firmware")
        if self.command(CMD_SET_PINS) != READY:
            raise ProbeError("probe refused the pin setup")
        self.ser.write(bytes([rst, dc, dd_i, dd_o, LED_NONE if led is None else led,
                              1 if save else 0]))
        self.ser.flush()
        self._read_frame()

    def reset_pins(self):
        self.command(CMD_RESET_PINS)

    # ------------------------------------------------------------ debug interface
    def enter(self):
        return self.command(CMD_ENTER)

    def exit(self):
        return self.command(CMD_EXIT)

    def chip_id(self):
        return self.command(CMD_CHIP_ID)

    def status(self):
        return self.command(CMD_STATUS) & 0xFF

    def pc(self):
        return self.command(CMD_PC)

    def halt(self):
        return self.command(CMD_HALT) & 0xFF

    def resume(self):
        return self.command(CMD_RESUME) & 0xFF

    def read_config(self):
        return self.command(CMD_RD_CFG) & 0xFF

    def write_config(self, cfg):
        return self.command(CMD_WR_CFG, cfg) & 0xFF

    def chip_erase(self):
        return self.command(CMD_CHPERASE) & 0xFF

    def instr_table_version(self):
        return self.command(CMD_INSTR_VER) & 0xFF

    def update_instr_table(self, version, table):
        payload = bytes([version] + list(table) + [0] * (15 - len(table)))
        if self.command(CMD_INSTR_UPD) != READY:
            raise ProbeError("probe refused the instruction table update")
        self.ser.write(payload)
        self.ser.flush()
        if (self._read_frame() & 0xFF) != version:
            raise ProbeError("instruction table update failed")

    def exec(self, *opcodes):
        """Execute one 8051 instruction on the halted CPU; returns A."""
        if len(opcodes) == 1:
            return self.command(CMD_EXEC_1, opcodes[0]) & 0xFF
        if len(opcodes) == 2:
            return self.command(CMD_EXEC_2, opcodes[0], opcodes[1]) & 0xFF
        return self.command(CMD_EXEC_3, *opcodes[:3]) & 0xFF

    # ------------------------------------------------------------ memory
    def _read_block(self, cmd, addr, n):
        out = bytearray()
        while n > 0:
            chunk = min(n, 256)
            self.command(cmd, addr >> 8, addr & 0xFF, chunk & 0xFF)
            out += self._read_exact(chunk)
            addr += chunk
            n -= chunk
        return bytes(out)

    def read_code(self, addr, n):
        if self.is_monopink:
            return self._read_block(CMD_READ_CODE, addr, n)
        out = bytearray()
        self.exec(0x90, addr >> 8, addr & 0xFF)       # MOV DPTR,#addr
        for _ in range(n):
            self.exec(0xE4)                           # CLR A
            out.append(self.exec(0x93))               # MOVC A,@A+DPTR
            self.exec(0xA3)                           # INC DPTR
        return bytes(out)

    def read_xdata(self, addr, n):
        if self.is_monopink:
            return self._read_block(CMD_READ_XDATA, addr, n)
        out = bytearray()
        self.exec(0x90, addr >> 8, addr & 0xFF)
        for _ in range(n):
            out.append(self.exec(0xE0))               # MOVX A,@DPTR
            self.exec(0xA3)
        return bytes(out)

    def write_xdata(self, addr, data):
        data = bytes(data)
        if self.is_monopink:
            for off in range(0, len(data), 256):
                chunk = data[off:off + 256]
                a = addr + off
                if self.command(CMD_WRITE_XDATA, a >> 8, a & 0xFF, len(chunk) & 0xFF) != READY:
                    raise ProbeError("probe refused the XDATA write")
                self.ser.write(chunk)
                self.ser.flush()
                self._read_frame()
            return
        self.exec(0x90, addr >> 8, addr & 0xFF)
        for b in data:
            self.exec(0x74, b)                        # MOV A,#b
            self.exec(0xF0)                           # MOVX @DPTR,A
            self.exec(0xA3)                           # INC DPTR

    # ------------------------------------------------------------ lines
    def reset_run(self, hold=False):
        """Hardware reset, then let the target run (not in debug mode)."""
        if self.is_monopink:
            self.command(CMD_RESET_RUN, 1 if hold else 0)
        else:
            # CCLib_proxy cannot do a plain reset: resume from debug mode
            self.enter()
            self.resume()

    def release(self):
        if self.is_monopink:
            self.command(CMD_RELEASE)
