"""MonopInk test-suite (no hardware needed).

    ./monopink.sh setup        # once
    .venv/bin/python -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["MONOPINK_DATA"] = tempfile.mkdtemp(prefix="monopink-test-")

from monopink import layout as L          # noqa: E402
from monopink import hexfile, ops, sim, config as C   # noqa: E402
from monopink import probe as P           # noqa: E402
from monopink.chip import page_routine    # noqa: E402
from monopink.image import (ImageParams, convert, test_pattern, planes_to_pixels,  # noqa: E402
                            WHITE, BLACK, RED)
from monopink.pico import SimEnv          # noqa: E402

from PIL import Image                     # noqa: E402


class QuietReporter(ops.Reporter):
    def __init__(self):
        super().__init__("en")
        self.lines = []
        self.states = []

    def emit(self, level, text):
        self.lines.append((level, text))

    def run_state(self, state, elapsed):
        self.states.append(state)


def solid(color, size=(40, 40)):
    return Image.new("RGB", size, color)


# ====================================================================== formats
class TestHexAndLayout(unittest.TestCase):
    def test_hex_roundtrip(self):
        data = bytes((i * 7) & 0xFF for i in range(3000)) + b"\xff" * 100 + b"\x01\x02"
        mem = hexfile.parse_hex(hexfile.dump_hex(data))
        img = hexfile.to_flash_image(mem, len(data))
        self.assertEqual(bytes(img), data)

    def test_hex_checksum_error(self):
        with self.assertRaises(hexfile.HexError):
            hexfile.parse_hex(":0400000002001632B1\n")

    def test_prebuilt_firmware(self):
        mem = hexfile.load_hex(ops.FIRMWARE_HEX)
        img = hexfile.to_flash_image(mem, L.FLASH_SIZE)
        self.assertEqual(bytes(img[L.FW_INFO_ADDR:L.FW_INFO_ADDR + 8]), L.FW_MAGIC)
        self.assertLess(max(mem), L.IMG_REGION_START, "code must not overlap the picture")
        pages = ops.firmware_pages()
        self.assertIn(0, pages)
        self.assertIn(L.FW_INFO_ADDR & ~(L.PAGE_SIZE - 1), pages)
        self.assertTrue(all(len(v) == L.PAGE_SIZE for v in pages.values()))

    def test_image_region(self):
        bw, red = b"\x11" * L.PLANE_SIZE, b"\x22" * L.PLANE_SIZE
        pages = ops.image_pages(bw, red)
        self.assertEqual(sorted(pages), list(range(0x5000, 0x7C00, 0x400)))
        flat = b"".join(pages[a] for a in sorted(pages))
        self.assertEqual(flat[:L.PLANE_SIZE], bw)
        o = L.IMG_R_ADDR - L.IMG_REGION_START
        self.assertEqual(flat[o:o + L.PLANE_SIZE], red)

    def test_full_hex(self):
        bw, red = b"\x0f" * L.PLANE_SIZE, b"\xf0" * L.PLANE_SIZE
        mem = hexfile.parse_hex(ops.full_hex(bw, red))
        img = hexfile.to_flash_image(mem, L.FLASH_SIZE)
        self.assertEqual(bytes(img[L.IMG_BW_ADDR:L.IMG_BW_ADDR + L.PLANE_SIZE]), bw)
        self.assertEqual(bytes(img[L.IMG_R_ADDR:L.IMG_R_ADDR + L.PLANE_SIZE]), red)
        self.assertEqual(bytes(img[L.FW_INFO_ADDR:L.FW_INFO_ADDR + 8]), L.FW_MAGIC)

    def test_images_c(self):
        src = ops.images_c(b"\x00" * L.PLANE_SIZE, b"\xff" * L.PLANE_SIZE)
        self.assertIn("imageBW[]", src)
        self.assertEqual(src.count("0x"), 2 * L.PLANE_SIZE)

    def test_page_routine_is_the_proven_one(self):
        # routine from CCLib/fishpepper (cc2510.py writeFlashPage), page 0x5000
        expected = [0x75, 0xAD, 0x28, 0x75, 0xAC, 0x00,
                    0x75, 0xAE, 0x01, 0xE5, 0xAE, 0x20, 0xE7, 0xFB,
                    0x90, 0xF0, 0x00, 0x7F, 0x02, 0x7E, 0x00, 0x75, 0xAE, 0x02,
                    0x7D, 0x02, 0xE0, 0xA3, 0xF5, 0xAF, 0xDD, 0xFA,
                    0xE5, 0xAE, 0x20, 0xE6, 0xFB, 0xDE, 0xF1, 0xDF, 0xEF, 0xA5]
        self.assertEqual(list(page_routine(0x5000)), expected)
        self.assertEqual(page_routine(0x7800)[2], 0x3C)


# ====================================================================== image
class TestImage(unittest.TestCase):
    def planes_of(self, rgb, **kw):
        conv = convert(solid(rgb), ImageParams(fit="stretch", mode="threshold", **kw))
        return conv.planes()

    def test_bit_conventions(self):
        bw, red = self.planes_of((255, 255, 255))
        self.assertEqual((set(bw), set(red)), ({0xFF}, {0xFF}))
        bw, red = self.planes_of((0, 0, 0))
        self.assertEqual((set(bw), set(red)), ({0x00}, {0xFF}))
        bw, red = self.planes_of((220, 20, 30))
        self.assertEqual((set(bw), set(red)), ({0xFF}, {0x00}))
        bw, red = self.planes_of((220, 20, 30), use_red=False)
        self.assertEqual(set(red), {0xFF})

    def test_grey_never_turns_red(self):
        for mode in ("dither", "threshold"):
            img = Image.linear_gradient("L").convert("RGB")
            conv = convert(img, ImageParams(mode=mode))
            self.assertEqual(conv.stats()["red"], 0.0, mode)

    def test_levels_mode_grey_to_red(self):
        conv = convert(solid((128, 128, 128)), ImageParams(mode="levels", fit="stretch"))
        self.assertEqual(conv.stats()["red"], 100.0)

    def test_roundtrip_and_sizes(self):
        conv = convert(test_pattern(), ImageParams(mode="threshold", fit="stretch"))
        self.assertEqual(conv.size, (L.EPD_WIDTH, L.EPD_HEIGHT))
        bw, red = conv.planes()
        self.assertEqual(len(bw), L.PLANE_SIZE)
        self.assertEqual(planes_to_pixels(bw, red), conv.panel_pixels())

    def test_landscape_rotation(self):
        img = Image.new("RGB", (L.EPD_HEIGHT, L.EPD_WIDTH), (255, 255, 255))
        img.putpixel((0, 0), (0, 0, 0))                  # design top-left
        conv = convert(img, ImageParams(orientation="landscape", mode="threshold", fit="stretch", sharp=True))
        px = conv.panel_pixels()
        self.assertEqual(px[L.EPD_WIDTH - 1], BLACK)     # -> panel top-right
        self.assertEqual(px.count(BLACK), 1)

    def test_calibration(self):
        img = Image.new("RGB", (L.EPD_WIDTH, L.EPD_HEIGHT), (255, 255, 255))
        img.putpixel((0, 0), (0, 0, 0))
        conv = convert(img, ImageParams(mode="threshold", fit="stretch", sharp=True))
        self.assertEqual(conv.panel_pixels(rotate180=True)[-1], BLACK)
        self.assertEqual(conv.panel_pixels(mirror=True)[L.EPD_WIDTH - 1], BLACK)

    def test_fill_enclosed(self):
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        d.ellipse([10, 10, 90, 90], fill=(0, 0, 0))
        d.ellipse([40, 40, 60, 60], fill=(255, 255, 255))
        conv = convert(img, ImageParams(mode="threshold", fit="stretch", fill_enclosed=True))
        w, h = conv.size
        self.assertEqual(conv.pixels[(h // 2) * w + w // 2], RED)   # the hole
        self.assertEqual(conv.pixels[0], WHITE)                      # background

    def test_params_from_dict(self):
        p = ImageParams.from_dict({"brightness": "250", "use_red": "false", "mode": "bogus",
                                   "black_level": 200, "white_level": 100})
        self.assertEqual(p.brightness, 100)
        self.assertFalse(p.use_red)
        self.assertEqual(p.mode, "dither")
        self.assertGreaterEqual(p.white_level, p.black_level)


# ====================================================================== config
class TestConfig(unittest.TestCase):
    def test_validate_pins(self):
        from monopink.pico import HEADER_GPIOS
        ok = {"rst": 3, "dc": 4, "dd_i": 6, "dd_o": 7}
        self.assertIsNone(C.validate_pins(ok, HEADER_GPIOS))
        self.assertIsNone(C.validate_pins({**ok, "dd_o": 6}, HEADER_GPIOS))    # single wire
        self.assertEqual(C.validate_pins({**ok, "dc": 3}, HEADER_GPIOS), "pins.duplicate")
        self.assertEqual(C.validate_pins({**ok, "rst": 25}, HEADER_GPIOS), "pins.not_on_header")
        self.assertEqual(C.validate_pins({"rst": "x"}), "pins.invalid")


# ====================================================================== probe framing
class FakeSerial:
    """Byte-level imitation of the MonopInk probe firmware (subset)."""

    def __init__(self, *a, **kw):
        self.out = bytearray()
        self.inbuf = bytearray()
        self.pending = None
        self.xdata = bytearray(0x10000)
        self.pins = [3, 4, 6, 7, 25]

    def reset_input_buffer(self):
        self.out.clear()

    def flush(self):
        pass

    def close(self):
        pass

    def frame(self, status, value=0):
        self.out += bytes([status, (value >> 8) & 0xFF, value & 0xFF])

    def read(self, n):
        data, self.out[:] = bytes(self.out[:n]), self.out[n:]
        return data

    def write(self, data):
        self.inbuf += data
        while True:
            if self.pending:
                need, handler = self.pending
                if len(self.inbuf) < need:
                    return
                payload, self.inbuf[:] = bytes(self.inbuf[:need]), self.inbuf[need:]
                self.pending = None
                handler(payload)
                continue
            if len(self.inbuf) < 4:
                return
            cmd, c1, c2, c3 = self.inbuf[:4]
            del self.inbuf[:4]
            self.handle(cmd, c1, c2, c3)

    def handle(self, cmd, c1, c2, c3):
        n = c3 or 256
        addr = (c1 << 8) | c2
        if cmd == P.CMD_PING:
            self.frame(P.ANS_OK)
        elif cmd == P.CMD_IDENT:
            self.frame(P.ANS_OK, 0x2000 if c1 == 1 else (ord("M") << 8) | 1)
        elif cmd == P.CMD_GET_PINS:
            p = self.pins
            self.frame(P.ANS_OK, [(p[0] << 8) | p[1], (p[2] << 8) | p[3], (p[4] << 8) | 1][c1])
        elif cmd == P.CMD_SET_PINS:
            self.frame(P.ANS_READY)

            def done(payload):
                self.pins = list(payload[:5])
                self.frame(P.ANS_OK)
            self.pending = (6, done)
        elif cmd == P.CMD_READ_XDATA:
            self.frame(P.ANS_OK, n)
            self.out += self.xdata[addr:addr + n]
        elif cmd == P.CMD_WRITE_XDATA:
            self.frame(P.ANS_READY)

            def done(payload, addr=addr):
                self.xdata[addr:addr + len(payload)] = payload
                self.frame(P.ANS_OK, len(payload))
            self.pending = (n, done)
        elif cmd == P.CMD_CHIP_ID:
            self.frame(P.ANS_ERROR, P.ERR_NOT_WIRED)
        else:
            self.frame(P.ANS_ERROR, P.ERR_UNKNOWN_CMD)


class TestProbeFraming(unittest.TestCase):
    def setUp(self):
        self._orig = P.serial.Serial
        P.serial.Serial = FakeSerial

    def tearDown(self):
        P.serial.Serial = self._orig

    def test_protocol(self):
        pr = P.Probe("/dev/fake")
        self.assertEqual(pr.identify(), ("monopink", 1))
        self.assertEqual(pr.board(), "RP2040")
        pr.set_pins(5, 6, 8, 8, save=True)
        pins = pr.get_pins()
        self.assertEqual((pins["rst"], pins["dc"], pins["dd_i"], pins["dd_o"]), (5, 6, 8, 8))
        data = bytes(range(256)) * 2 + b"xyz"
        pr.write_xdata(0xF000, data)
        self.assertEqual(pr.read_xdata(0xF000, len(data)), data)
        with self.assertRaises(P.ProbeError) as cm:
            pr.chip_id()
        self.assertEqual(cm.exception.code, P.ERR_NOT_WIRED)


# ====================================================================== workflows
class TestSimWorkflow(unittest.TestCase):
    def setUp(self):
        sim.world().reset()
        self.env = SimEnv()
        self.cfg = C.load()
        for f in (ops.LABEL_IMAGE,):
            if os.path.exists(f):
                os.remove(f)

    def test_full_workflow(self):
        rep = QuietReporter()
        st = ops.install_probe(self.env, self.cfg, rep, wait_bootsel=5)
        self.assertEqual(st["state"], "monopink")
        self.assertTrue(st["pins_match"])

        info = ops.tag_info(self.env, self.cfg, rep)
        self.assertTrue(info["locked"])
        with self.assertRaises(ops.OpError) as cm:
            ops.tag_install(self.env, self.cfg, rep, erase=False)
        self.assertEqual(cm.exception.key, "tag.locked_need_erase")

        res = ops.tag_install(self.env, self.cfg, rep, erase=True)
        # code pages + NFC state page + the 11 picture pages
        self.assertEqual(res["programmed"], len(ops.firmware_pages()) + 11)
        self.assertTrue(res["run"]["finished"])
        self.assertIn(L.ST_REFRESHING, rep.states)

        info = ops.tag_info(self.env, self.cfg, rep)
        self.assertFalse(info["locked"])
        self.assertTrue(info["firmware"]["installed"])

        conv = convert(test_pattern("landscape"), ImageParams(orientation="landscape", mode="threshold"))
        bw, red = conv.planes()
        ops.tag_write_image(self.env, self.cfg, rep, bw, red)
        self.assertEqual(sim.world().chip.displayed, (bw, red))
        self.assertEqual(ops.saved_planes(), (bw, red))

    def test_label_missing(self):
        rep = QuietReporter()
        ops.install_probe(self.env, self.cfg, rep, wait_bootsel=5)
        sim.world().chip.connected = False
        with self.assertRaises(ops.OpError) as cm:
            ops.tag_info(self.env, self.cfg, rep)
        self.assertEqual(cm.exception.key, "tag.not_responding")

    def test_image_needs_firmware(self):
        rep = QuietReporter()
        ops.install_probe(self.env, self.cfg, rep, wait_bootsel=5)
        with self.assertRaises(ops.OpError) as cm:
            ops.tag_write_image(self.env, self.cfg, rep, b"\xff" * L.PLANE_SIZE, b"\xff" * L.PLANE_SIZE)
        self.assertEqual(cm.exception.key, "tag.no_firmware")

    def test_flash_hex(self):
        rep = QuietReporter()
        ops.install_probe(self.env, self.cfg, rep, wait_bootsel=5)
        with open(os.path.join(ROOT, "firmware", "examples", "blink", "blink.hex")) as f:
            text = f.read()
        with self.assertRaises(ops.OpError):
            ops.tag_flash_hex(self.env, self.cfg, rep, text, erase=False)   # locked
        ops.tag_flash_hex(self.env, self.cfg, rep, text, erase=True)
        mem = hexfile.parse_hex(text)
        flash = sim.world().chip.flash
        self.assertTrue(all(flash[a] == b for a, b in mem.items()))
        with self.assertRaises(ops.OpError) as cm:
            ops.tag_flash_hex(self.env, self.cfg, rep, "garbage")
        self.assertEqual(cm.exception.key, "hex.invalid")

    def test_boot_test(self):
        rep = QuietReporter()
        ops.install_probe(self.env, self.cfg, rep, wait_bootsel=5)
        ops.tag_install(self.env, self.cfg, rep, erase=True, run=False)
        res = ops.tag_boot_test(self.env, self.cfg, rep, wait=7)
        self.assertEqual(res["error"], 0)
        self.assertGreater(res["refresh_s"], 3)
        self.assertEqual(res["boots"], 1)
        # a plain reset afterwards ends in PM3: the next debug entry must work
        pr = self.env.open_probe(sim.world().port)
        pr.reset_run()
        time.sleep(7)
        info = ops.tag_info(self.env, self.cfg, rep)
        self.assertTrue(info["firmware"]["installed"])

    def test_ram_survives_reset_but_hold_flag_is_consumed(self):
        rep = QuietReporter()
        ops.install_probe(self.env, self.cfg, rep, wait_bootsel=5)
        ops.tag_install(self.env, self.cfg, rep, erase=True)     # watched run (MPHD)
        chip = sim.world().chip
        self.assertEqual(bytes(chip.xdata[L.MAILBOX_ADDR:L.MAILBOX_ADDR + 4]), bytes(4))

    def test_works_with_original_cclib_proxy(self):
        rep = QuietReporter()          # the simulated Pico starts with CCLib_proxy
        res = ops.tag_install(self.env, self.cfg, rep, erase=True)
        self.assertTrue(res["run"]["finished"])


# ====================================================================== web server
class TestWebServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from monopink.web import server
        sim.world().reset()
        server.APP = server.App(simulate=True)
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def req(self, path, body=None, headers=None, raw=None):
        h = {"X-MonopInk": "1"} if (body is not None or raw is not None) else {}
        h.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if body is not None:
            h.setdefault("Content-Type", "application/json")
        r = urllib.request.Request(self.base + path, data=data, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def job(self, op, args=None):
        code, body = self.req("/api/jobs", {"op": op, "args": args or {}, "lang": "fr"})
        self.assertEqual(code, 200, body)
        jid = json.loads(body)["id"]
        for _ in range(200):
            snap = json.loads(self.req(f"/api/jobs/{jid}")[1])
            if snap["status"] != "running":
                return snap
            time.sleep(0.1)
        self.fail("job did not finish")

    def test_security(self):
        r = urllib.request.Request(self.base + "/api/config", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r)
        self.assertEqual(cm.exception.code, 403)
        code, _ = self.req("/api/state", headers={"Host": "evil.example"})
        self.assertEqual(code, 403)
        code, _ = self.req("/static/../../monopink/cli.py")
        self.assertEqual(code, 404)

    def test_end_to_end(self):
        code, body = self.req("/")
        self.assertEqual(code, 200)
        self.assertIn(b"MonopInk", body)
        state = json.loads(self.req("/api/state")[1])
        self.assertTrue(state["simulate"])

        self.assertEqual(self.job("pico_flash")["status"], "done")
        snap = self.job("tag_install", {"erase": True})
        self.assertEqual(snap["status"], "done", snap)
        self.assertTrue(any("rafraîchi" in l["text"] for l in snap["log"]))   # French log
        self.assertGreater(len(snap["run_states"]), 2)

        buf = io.BytesIO()
        solid((200, 30, 30), (300, 200)).save(buf, "JPEG")
        code, body = self.req("/api/image/upload", raw=buf.getvalue(), headers={"X-Filename": "red.jpg"})
        self.assertEqual(code, 200, body)
        code, body = self.req("/api/image/preview", {"params": {"mode": "threshold"}})
        prev = json.loads(body)
        self.assertEqual(prev["stats"]["red"], 100.0)
        self.assertTrue(prev["preview"].startswith("data:image/png;base64,"))

        snap = self.job("tag_image", {"params": {"mode": "threshold"}})
        self.assertEqual(snap["status"], "done", snap)
        code, _ = self.req("/api/label/preview")
        self.assertEqual(code, 200)
        for fmt in ("png", "hex", "bin", "c"):
            code, _ = self.req(f"/api/image/export?fmt={fmt}")
            self.assertEqual(code, 200, fmt)

    def test_nfc_page_and_jobs(self):
        code, body = self.req("/nfc/")
        self.assertEqual(code, 200)
        self.assertIn(b"nfc.js", body)
        for f in ("nfc.js", "codec.js", "convert.js", "app.css"):
            self.assertEqual(self.req("/nfc/" + f)[0], 200, f)
        self.assertEqual(self.req("/nfc/../../monopink/cli.py")[0], 404)
        self.assertEqual(self.req("/nfc/%2e%2e/%2e%2e/monopink/cli.py")[0], 404)
        code, body = self.req("/api/config", {"nfc_url": "http://example.com/nfc/"})
        self.assertEqual(code, 400)
        code, body = self.req("/api/config", {"nfc_url": "https://example.github.io/MonopInk/nfc/"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["config"]["nfc_url"], "https://example.github.io/MonopInk/nfc/")

        self.assertEqual(self.job("pico_flash")["status"], "done")
        self.assertEqual(self.job("tag_install", {"erase": True})["status"], "done")
        snap = self.job("nfc_info")
        self.assertEqual(snap["status"], "done", snap)
        self.assertEqual(snap["result"]["wake"], "fd")
        self.assertEqual(self.req("/api/image/test-pattern", {"orientation": "portrait"})[0], 200)
        snap = self.job("nfc_send", {"params": {"mode": "threshold", "fit": "stretch"}})
        self.assertEqual(snap["status"], "done", snap)
        self.assertEqual(snap["result"]["parts"], 1)

    def test_bad_upload(self):
        code, body = self.req("/api/image/upload", raw=b"not an image", headers={"X-Lang": "fr"})
        self.assertEqual(code, 400)
        self.assertIn("non support", json.loads(body)["error"])


if __name__ == "__main__":
    unittest.main()
