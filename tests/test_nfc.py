"""NFC picture upload: codec, protocol, label firmware, phone page, simulator.

    .venv/bin/python -m unittest tests.test_nfc -v

The firmware tests compile firmware/src/nfc.c + codec.c natively (needs a C
compiler) and run them against a mock NTAG; the JavaScript tests need Node.
Both are skipped when the tool is missing.
"""
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("MONOPINK_DATA", tempfile.mkdtemp(prefix="monopink-test-"))   # never touch data/

from monopink import codec, nfc, nfclabel, ops, sim, layout as L, config as C   # noqa: E402
from monopink.image import (ImageParams, convert, test_pattern, planes_to_pixels,   # noqa: E402
                            pixels_to_planes)
from monopink.pico import SimEnv          # noqa: E402

from PIL import Image, ImageDraw          # noqa: E402

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
NODE = shutil.which("node")


def photo(size=(400, 300), seed=1):
    """Synthetic 'photo': gradient + coloured discs (no external file)."""
    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(size[1]):
        v = int(255 * y / size[1])
        d.line([(0, y), (size[0], y)], fill=(v, 255 - v // 2, 128))
    for _ in range(40):
        x, y, r = rnd.randrange(size[0]), rnd.randrange(size[1]), rnd.randrange(5, 40)
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(rnd.randrange(256) for _ in range(3)))
    return img


SIMPLE = convert(test_pattern(), ImageParams(mode="threshold", fit="stretch"))
BIG = convert(photo(), ImageParams(mode="dither", orientation="landscape"))


# ====================================================================== codec
class TestCodec(unittest.TestCase):
    def test_crc16_ccitt_false(self):
        self.assertEqual(codec.crc16(b"123456789"), 0x29B1)

    def test_roundtrip(self):
        for conv in (SIMPLE, BIG):
            px = conv.panel_pixels()
            stream = codec.encode(px)
            self.assertEqual(stream[0], 0x01)
            self.assertEqual(codec.decode(stream), list(px))

    def test_solid_and_noise(self):
        n = L.EPD_WIDTH * L.EPD_HEIGHT
        rnd = random.Random(7)
        for px in ([0] * n, [1] * n, [2] * n, [rnd.randrange(3) for _ in range(n)]):
            self.assertEqual(codec.decode(codec.encode(px)), px)

    def test_compression(self):
        self.assertLess(len(codec.encode(SIMPLE.panel_pixels())), 1000)
        self.assertLess(len(codec.encode(BIG.panel_pixels())), nfc.STAGING_SIZE)

    def test_planes_helpers(self):
        px = BIG.panel_pixels()
        self.assertEqual(planes_to_pixels(*pixels_to_planes(px)), list(px))


# ====================================================================== protocol helpers
class TestProtocol(unittest.TestCase):
    def test_parts_fit_the_ndef_area(self):
        stream, parts = nfc.encode_planes_pixels(BIG.panel_pixels(), image_id=0x1234)
        self.assertGreater(len(parts), 1)
        self.assertEqual(b"".join(p[nfc.PART_HDR:] for p in parts), stream)
        for i, p in enumerate(parts):
            area = nfc.part_area(p)
            self.assertLessEqual(len(area), nfc.USER_BYTES)
            recs = nfc.parse_t2t(area)
            self.assertEqual(recs, [(2, nfc.PART_TYPE, p)])
            pid, idx, count, total, scrc, pcrc, chunk = struct.unpack("<HBBHHHH", p[3:15])
            self.assertEqual((pid, idx, count, total), (0x1234, i, len(parts), len(stream)))
            self.assertEqual(scrc, codec.crc16(stream))
            self.assertEqual(pcrc, codec.crc16(p[nfc.PART_HDR:]))
            self.assertEqual(chunk, nfc.MAX_PART_DATA)

    def test_too_big(self):
        with self.assertRaises(ValueError):
            nfc.split_stream(bytes(nfc.STAGING_SIZE + 1))

    def test_status_record(self):
        m = nfclabel.LabelModel()
        m.prepare()
        st = nfc.status_from_area(bytes(m.area))
        self.assertEqual(st["state"], "ready")
        self.assertEqual(st["firmware"], "1.3")
        self.assertEqual(st["max_part"], nfc.MAX_PART_DATA)
        self.assertEqual(st["max_stream"], nfc.STAGING_SIZE)
        # exactly what the firmware writes into NTAG blocks 1-2
        self.assertEqual(bytes(m.area[:10]), bytes([0x03, 0x18, 0xD2, 0x05, 0x10]) + b"x/mps")
        self.assertEqual(m.area[26], 0xFE)


# ====================================================================== label firmware (C)
@unittest.skipUnless(CC, "no C compiler")
class TestFirmwareNative(unittest.TestCase):
    """The real firmware/src/nfc.c + codec.c against a mock NTAG and flash,
    side by side with the Python model (monopink/nfclabel.py)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="monopink-nfc-")
        src = os.path.join(ROOT, "firmware", "src")
        cls.nfc_bin = os.path.join(cls.tmp, "nfc_test")
        cls.codec_bin = os.path.join(cls.tmp, "codec_test")
        for out, main, extra in ((cls.nfc_bin, "nfc_test.c", ["nfc.c", "codec.c"]),
                                 (cls.codec_bin, "codec_test.c", ["codec.c"])):
            r = subprocess.run([CC, "-O1", "-Wall", "-Wno-unused-function", "-o", out,
                                os.path.join(HERE, "native", main)] + [os.path.join(src, f) for f in extra],
                               capture_output=True, text=True)
            if r.returncode:
                raise RuntimeError(r.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # scenario items: bytes = phone writes an area; "reboot"; "poll"; ("write", area)
    def run_fw(self, items):
        blob = b""
        for it in items:
            if it == "reboot":
                blob += struct.pack("<H", 0xFFFF)
            elif it == "poll":
                blob += struct.pack("<H", 0xFFFE)
            elif isinstance(it, tuple):
                blob += struct.pack("<H", 0x8000 | len(it[1])) + it[1]
            else:
                blob += struct.pack("<H", len(it)) + it
        scen = os.path.join(self.tmp, "scen.bin")
        planes = os.path.join(self.tmp, "planes.bin")
        with open(scen, "wb") as f:
            f.write(blob)
        r = subprocess.run([self.nfc_bin, scen, planes], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().splitlines()
        self.assertTrue(lines[0].startswith("prepare status"))
        steps = []
        for line in lines[1:]:
            w = line.split()
            if w[0] == "result":
                steps.append((int(w[1]), bytes.fromhex(w[3]), bytes.fromhex(w[5])))
            elif w[0] == "poll":
                steps.append(("poll", int(w[1])))
            else:
                steps.append((w[0],))
        with open(planes, "rb") as f:
            region = f.read()
        o = L.IMG_R_ADDR - L.IMG_BW_ADDR
        counts = dict(kv.split(": ") for kv in r.stderr.strip().split(", "))
        return lines[0], steps, (region[:L.PLANE_SIZE], region[o:o + L.PLANE_SIZE]), counts

    def run_model(self, items):
        m = nfclabel.LabelModel()
        m.prepare()
        steps = []
        for it in items:
            if it == "reboot":
                m.power_loss()
                steps.append(("reboot",))
            elif it == "poll" or isinstance(it, tuple):
                if isinstance(it, tuple):
                    m.area[:len(it[1])] = it[1]
                    steps.append(("written",))
            else:
                r = m.phone_write(it)
                steps.append((r, m.status(), bytes(m.area[:32])))
        return steps, m

    def check_same(self, items):
        """Run a scenario on the C firmware and the Python model; they must agree."""
        prep, fw_steps, planes, counts = self.run_fw(items)
        model_steps, m = self.run_model(items)
        fw_cmp = [s for s in fw_steps if s[0] != "poll"]
        self.assertEqual(fw_cmp, model_steps)
        self.assertEqual(int(counts["state page"]), m.flash_desc_writes)
        return fw_steps, planes, counts

    def parts(self, conv, image_id, chunk=nfc.MAX_PART_DATA):
        return nfc.encode_planes_pixels(conv.panel_pixels(), chunk=chunk, image_id=image_id)[1]

    def test_prepare_formats_the_tag(self):
        prep, steps, _, _ = self.run_fw([])
        self.assertIn("cc e1106d00", prep)
        st = nfc.parse_status(bytes.fromhex(prep.split()[2]))
        self.assertEqual((st["state"], st["error"]), ("ready", "ok"))

    def test_single_part(self):
        p = self.parts(SIMPLE, 0x1111)
        self.assertEqual(len(p), 1)
        steps, planes, counts = self.check_same([nfc.part_area(p[0])])
        self.assertEqual(steps[0][0], nfclabel.IMAGE)
        st = nfc.status_from_area(steps[0][2])
        self.assertEqual((st["state"], st["next"], st["image_id"]), ("complete", 1, 0x1111))
        self.assertEqual(planes, SIMPLE.planes())
        self.assertEqual(counts["state page"], "1")        # one flash write per picture

    def test_multi_part_with_errors(self):
        p = self.parts(BIG, 0x2222)
        bad = bytearray(p[1])
        bad[40] ^= 0xFF
        seq = [nfc.part_area(p[0]), nfc.part_area(bytes(bad)), nfc.part_area(p[2]),
               nfc.part_area(p[1]), nfc.part_area(p[1]), nfc.t2t_area(b"")]
        seq += [nfc.part_area(x) for x in p[2:]]
        steps, planes, counts = self.check_same(seq)
        res = [s[0] for s in steps]
        errs = [nfc.parse_status(s[1])["error"] for s in steps]
        nexts = [nfc.parse_status(s[1])["next"] for s in steps]
        self.assertEqual(res[:6], [1, 3, 3, 1, 0, 0])
        self.assertEqual(errs[:4], ["ok", "part_crc", "order", "ok"])
        self.assertEqual(nexts[:5], [1, 1, 1, 2, 2])
        self.assertEqual(res[-1], nfclabel.IMAGE)
        self.assertEqual(planes, BIG.planes())
        self.assertEqual(counts["state page"], "1")

    def test_new_picture_and_foreign_part(self):
        p1, p2 = self.parts(SIMPLE, 0x1111), self.parts(BIG, 0x2222)
        p3 = self.parts(SIMPLE, 0x3333, chunk=200)
        seq = [nfc.part_area(x) for x in p1] + [nfc.part_area(p3[0]), nfc.part_area(p2[1])]
        seq += [nfc.part_area(x) for x in p3[1:]]
        steps, planes, _ = self.check_same(seq)
        res = [s[0] for s in steps]
        self.assertEqual(res[:3], [2, 1, 3])
        self.assertEqual(nfc.parse_status(steps[2][1])["error"], "order")
        self.assertEqual(res[-1], nfclabel.IMAGE)
        self.assertEqual(planes, SIMPLE.planes())

    def test_duplicate_first_part_keeps_progress(self):
        p = self.parts(BIG, 0x4444)
        seq = [nfc.part_area(p[0]), nfc.part_area(p[1]), nfc.part_area(p[0])]
        steps, _, _ = self.check_same(seq)
        self.assertEqual(steps[2][0], nfclabel.NOTHING)
        self.assertEqual(nfc.parse_status(steps[2][1])["next"], 2)

    def test_damaged_first_part_after_complete_picture(self):
        """Must not announce "complete" for the new picture id."""
        p1 = self.parts(SIMPLE, 0x1111)
        p2 = self.parts(BIG, 0x5555)
        bad = bytearray(p2[0])
        bad[100] ^= 0x01
        steps, _, _ = self.check_same([nfc.part_area(p1[0]), nfc.part_area(bytes(bad)), nfc.part_area(p2[0])])
        st = nfc.parse_status(steps[1][1])
        self.assertEqual((st["state"], st["error"], st["image_id"], st["next"]),
                         ("receiving", "part_crc", 0x5555, 0))
        self.assertEqual(nfc.parse_status(steps[2][1])["next"], 1)

    def test_resending_the_displayed_picture(self):
        p = self.parts(SIMPLE, 0x1111)
        steps, _, _ = self.check_same([nfc.part_area(p[0]), nfc.part_area(p[0])])
        self.assertEqual(steps[1][0], nfclabel.NOTHING)
        self.assertEqual(nfc.parse_status(steps[1][1])["state"], "complete")

    def test_power_loss_mid_transfer(self):
        """RAM state lost: the label falls back to its flash copy (the last
        complete picture) and the phone starts over."""
        p1, p2 = self.parts(SIMPLE, 0x1111), self.parts(BIG, 0x6666)
        seq = [nfc.part_area(p1[0]), nfc.part_area(p2[0]), nfc.part_area(p2[1]), "reboot",
               nfc.part_area(p2[2])]
        seq += [nfc.part_area(x) for x in p2]
        steps, planes, counts = self.check_same(seq)
        after = nfc.parse_status(steps[4][1])
        self.assertEqual((after["state"], after["image_id"]), ("complete", 0x1111))
        self.assertEqual(steps[4][0], nfclabel.FAILED)          # part 2 of an unknown transfer
        self.assertEqual(steps[-1][0], nfclabel.IMAGE)
        self.assertEqual(planes, BIG.planes())
        self.assertEqual(counts["state page"], "2")              # one per picture

    def test_polling_mode_detects_new_data(self):
        p = self.parts(SIMPLE, 0x7777)
        _, steps, _, _ = self.run_fw(["poll", ("write", nfc.part_area(p[0])), "poll",
                                      nfc.part_area(p[0]), "poll",
                                      ("write", nfc.t2t_area(b"")), "poll"])
        polls = [s[1] for s in steps if s[0] == "poll"]
        # untouched status -> 0; part written by a phone -> 1; after processing -> 0;
        # tag wiped by another app -> 1 (the label rewrites its status)
        self.assertEqual(polls, [0, 1, 0, 1])

    def test_c_decoder_matches_python(self):
        for conv in (SIMPLE, BIG):
            stream = codec.encode(conv.panel_pixels())
            path = os.path.join(self.tmp, "stream.bin")
            with open(path, "wb") as f:
                f.write(stream)
            out = subprocess.run([self.codec_bin, path], capture_output=True, text=True).stdout.strip()
            self.assertEqual([int(c) for c in out], list(conv.panel_pixels()))


# ====================================================================== phone page (JS)
@unittest.skipUnless(NODE, "node not installed")
class TestPhonePageCodec(unittest.TestCase):
    def run_node(self, script, stdin):
        r = subprocess.run([NODE, "-e", script], input=stdin, capture_output=True, text=True,
                           cwd=os.path.join(ROOT, "docs", "nfc"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_js_encoder_and_parts_match_python(self):
        script = r"""
const K = require('./codec.js');
let s = ''; process.stdin.on('data', d => s += d).on('end', () => {
  const px = Uint8Array.from(s.trim(), c => c.charCodeAt(0) - 48);
  const stream = K.encode(px);
  const parts = K.splitStream(stream, 832, 0xBEEF);
  process.stdout.write(JSON.stringify({stream: Buffer.from(stream).toString('hex'),
    parts: parts.map(p => Buffer.from(p).toString('hex'))}));
});"""
        for conv in (SIMPLE, BIG):
            px = conv.panel_pixels()
            out = self.run_node(script, "".join(map(str, px)))
            stream = codec.encode(px)
            self.assertEqual(bytes.fromhex(out["stream"]), stream)
            self.assertEqual([bytes.fromhex(p) for p in out["parts"]],
                             nfc.split_stream(stream, 832, 0xBEEF))

    def test_js_status_parser(self):
        m = nfclabel.LabelModel()
        m.prepare()
        script = r"""
const K = require('./codec.js');
let s = ''; process.stdin.on('data', d => s += d).on('end', () => {
  process.stdout.write(JSON.stringify(K.parseStatus(Uint8Array.from(Buffer.from(s.trim(), 'hex')))));
});"""
        out = self.run_node(script, m.status().hex())
        py = nfc.parse_status(m.status())
        self.assertEqual((out["state"], out["error"], out["firmware"], out["maxPart"], out["maxStream"]),
                         (py["state"], py["error"], py["firmware"], py["max_part"], py["max_stream"]))

    def test_page_files_are_consistent(self):
        """Every data-i18n key used by index.html exists in both languages."""
        import re
        base = os.path.join(ROOT, "docs", "nfc")
        html = open(os.path.join(base, "index.html"), encoding="utf-8").read()
        js = open(os.path.join(base, "nfc.js"), encoding="utf-8").read()
        keys = set(re.findall(r'data-i18n(?:-html)?="([^"]+)"', html))
        en = js[js.index("en: {"):js.index("fr: {")]
        fr = js[js.index("fr: {"):]
        for k in keys:
            self.assertIn(f'"{k}"', en.replace("tagline:", '"tagline":'), k)
            self.assertIn(f'"{k}"', fr.replace("tagline:", '"tagline":'), k)
        used = set(re.findall(r'T\("([a-z0-9_.]+)"[,)]', js))
        used |= {"s.err." + e for e in nfc.ERRORS.values() if e != "ok"}   # T("s.err." + st.error)
        for k in used:
            self.assertIn(f'"{k}"', en, k)
            self.assertIn(f'"{k}"', fr, k)
        r = subprocess.run([NODE, "--check", os.path.join(base, "nfc.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


# ====================================================================== simulator + host commands
class QuietReporter(ops.Reporter):
    def __init__(self):
        super().__init__("en")
        self.events = []

    def msg(self, level, key, **kw):
        self.events.append((level, key))

    def emit(self, level, text):
        pass


class TestSimNfc(unittest.TestCase):
    def setUp(self):
        sim.world().reset()
        self.env = SimEnv()
        self.cfg = C.load()
        self.rep = QuietReporter()
        ops.install_probe(self.env, self.cfg, self.rep, wait_bootsel=5)

    def test_needs_firmware_13(self):
        with self.assertRaises(ops.OpError) as cm:
            ops.nfc_info(self.env, self.cfg, self.rep)
        self.assertEqual(cm.exception.key, "nfc.need_fw13")

    def test_info_and_send(self):
        ops.tag_install(self.env, self.cfg, self.rep, erase=True, run=False)
        d = ops.nfc_info(self.env, self.cfg, self.rep)
        self.assertEqual((d["variant"], d["cc"], d["auth0"]), ("1k", "e1106d00", 0xFF))
        self.assertEqual(d["wake"], "fd")
        conv = convert(photo(seed=3), ImageParams(mode="threshold"))
        res = ops.nfc_send(self.env, self.cfg, self.rep, conv.panel_pixels())
        self.assertGreaterEqual(res["parts"], 1)
        self.assertEqual(sim.world().chip.displayed, conv.planes())
        st = nfc.parse_status(sim.world().chip.nfc.status())
        self.assertEqual(st["state"], "complete")

    def test_info_reports_polling_mode(self):
        ops.tag_install(self.env, self.cfg, self.rep, erase=True, run=False)
        sim.world().chip.nfc_fd_pullup = False
        d = ops.nfc_info(self.env, self.cfg, self.rep)
        self.assertEqual(d["wake"], "poll")
        self.assertIn(("warn", "nfc.fd_polling"), self.rep.events)


if __name__ == "__main__":
    unittest.main()
