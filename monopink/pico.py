"""Raspberry Pi Pico side: serial ports, BOOTSEL drive, UF2 flashing.

Everything that touches the operating system goes through an "environment"
object so the same workflow code runs on real hardware (RealEnv) or on the
simulator (SimEnv).
"""
import glob
import os
import shutil
import string
import sys
import time

from .probe import Probe
from . import sim

RPI_VID = 0x2E8A
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UF2 = {
    "RPI-RP2": os.path.join(ROOT, "pico", "prebuilt", "monopink-probe-rp2040.uf2"),
    "RP2350": os.path.join(ROOT, "pico", "prebuilt", "monopink-probe-rp2350.uf2"),
}

# GPIOs available on the Pico / Pico 2 header (GP23-25 and GP29 are internal)
HEADER_GPIOS = list(range(0, 23)) + [26, 27, 28]


def uf2_for(board_id):
    return UF2.get(board_id)


def _read_board_id(info_path):
    try:
        with open(info_path, "r", errors="replace") as f:
            for line in f:
                if line.lower().startswith("board-id:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


class RealEnv:
    simulated = False

    def serial_ports(self):
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        out = []
        for p in list_ports.comports():
            dev = p.device
            if sys.platform == "darwin" and dev.startswith("/dev/tty."):
                continue
            is_pico = p.vid == RPI_VID
            usb_like = p.vid is not None or any(k in dev.lower() for k in ("usb", "acm"))
            if not usb_like:
                continue          # Bluetooth, debug-console, wlan-debug...
            out.append({"device": dev, "vid": p.vid, "pid": p.pid,
                        "description": p.description or "", "is_pico": is_pico})
        out.sort(key=lambda d: (not d["is_pico"], d["device"]))
        return out

    def drives(self):
        candidates = []
        if sys.platform == "darwin":
            candidates = glob.glob("/Volumes/*/INFO_UF2.TXT")
        elif sys.platform.startswith("win"):
            for letter in string.ascii_uppercase:
                p = f"{letter}:\\INFO_UF2.TXT"
                if os.path.exists(p):
                    candidates.append(p)
        else:
            user = os.environ.get("USER", "*")
            for pat in (f"/media/{user}/*/INFO_UF2.TXT", "/media/*/*/INFO_UF2.TXT",
                        f"/run/media/{user}/*/INFO_UF2.TXT", "/media/*/INFO_UF2.TXT",
                        "/mnt/*/INFO_UF2.TXT"):
                candidates += glob.glob(pat)
        out, seen = [], set()
        for info in candidates:
            d = os.path.dirname(info)
            if d in seen:
                continue
            seen.add(d)
            bid = _read_board_id(info)
            if bid in UF2:
                out.append({"path": d, "board_id": bid})
        return out

    def touch_1200(self, port):
        """Ask an arduino-pico firmware to reboot into BOOTSEL (1200 baud touch)."""
        import serial
        try:
            s = serial.Serial()
            s.port = port
            s.baudrate = 1200
            s.dtr = True
            s.open()
            time.sleep(0.1)
            s.dtr = False
            time.sleep(0.05)
            s.close()
        except Exception:
            pass

    def copy_uf2(self, drive, uf2_path):
        dst = os.path.join(drive, os.path.basename(uf2_path))
        try:
            shutil.copyfile(uf2_path, dst)
        except OSError:
            # the Pico reboots as soon as the last block lands, so the drive
            # can disappear before the OS finishes closing the file
            if os.path.exists(drive):
                raise

    def open_probe(self, port):
        return Probe(port)


class SimEnv:
    simulated = True

    def __init__(self):
        self.w = sim.world()

    def serial_ports(self):
        return self.w.serial_ports()

    def drives(self):
        return self.w.drives()

    def touch_1200(self, port):
        self.w.touch_1200(port)

    def copy_uf2(self, drive, uf2_path):
        self.w.copy_uf2(drive, uf2_path)

    def open_probe(self, port):
        return sim.SimProbe(self.w, port)


def make_env(simulate=False):
    return SimEnv() if simulate else RealEnv()
