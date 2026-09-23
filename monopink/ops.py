"""High-level workflows shared by the CLI and the web app.

Every function takes an Env (real or simulated hardware), the settings and a
Reporter, and raises OpError (with an i18n key) when something goes wrong.
"""
import os
import time

from . import config as C
from . import hexfile
from . import layout as L
from .chip import CC2510, TagError
from .i18n import t, state_text
from .pico import uf2_for, HEADER_GPIOS
from .probe import ProbeError

ROOT = C.ROOT
FIRMWARE_HEX = os.path.join(ROOT, "firmware", "prebuilt", "monopink-tag.hex")
LABEL_IMAGE = os.path.join(C.DATA_DIR, "label_image.bin")


def _hex_firmware_version():
    """Version stored in the info block of the prebuilt firmware."""
    try:
        img = hexfile.to_flash_image(hexfile.load_hex(FIRMWARE_HEX), L.FLASH_SIZE)
        if bytes(img[L.FW_INFO_ADDR:L.FW_INFO_ADDR + 8]) == L.FW_MAGIC:
            return f"{img[L.FW_INFO_ADDR + 8]}.{img[L.FW_INFO_ADDR + 9]}"
    except (OSError, hexfile.HexError):
        pass
    return "0.0"


WANTED_FW = _hex_firmware_version()


class Cancelled(Exception):
    pass


class OpError(Exception):
    def __init__(self, key, **kw):
        super().__init__(key)
        self.key = key
        self.kw = kw


class Reporter:
    """Receives progress and messages.  Subclassed by the CLI and the web jobs."""

    def __init__(self, lang="en"):
        self.lang = lang
        self.cancelled = False

    def t(self, key, **kw):
        return t(key, self.lang, **kw)

    def emit(self, level, text):          # override
        print(f"[{level}] {text}")

    def msg(self, level, key, **kw):
        self.emit(level, self.t(key, **kw))

    def step(self, key, **kw):
        self.msg("step", key, **kw)

    def info(self, key, **kw):
        self.msg("info", key, **kw)

    def ok(self, key, **kw):
        self.msg("ok", key, **kw)

    def warn(self, key, **kw):
        self.msg("warn", key, **kw)

    def action(self, key, **kw):
        self.msg("action", key, **kw)

    def progress(self, done, total):
        pass

    def run_state(self, state, elapsed):
        """Firmware progress code seen while watching a refresh."""
        pass

    def check_cancel(self):
        if self.cancelled:
            raise Cancelled()

    def sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.check_cancel()
            time.sleep(min(0.1, max(0, end - time.time())))


# ====================================================================== probe
def _describe(rep, kind, version, board):
    if kind == "monopink":
        return rep.t("probe.kind.monopink", version=version, board=board or "?")
    return rep.t("probe.kind.cclib")


def open_probe(env, cfg, rep, quiet=False):
    """Open the configured (or auto-detected) probe."""
    port = cfg.get("port") or "auto"
    candidates = [port] if port != "auto" else [p["device"] for p in env.serial_ports()]
    if not quiet:
        rep.info("probe.searching")
    last_err = None
    for dev in candidates:
        try:
            pr = env.open_probe(dev)
        except ProbeError as e:
            last_err = e
            continue
        kind, version = pr.identify()
        if not quiet:
            rep.info("probe.found", port=dev, kind=_describe(rep, kind, version, pr.board()))
            if kind != "monopink":
                rep.warn("probe.cclib_hint")
        return pr
    raise OpError("probe.not_found", err=str(last_err or ""))


def pico_status(env, cfg):
    """Snapshot of the Pico side (never raises)."""
    drives = env.drives()
    if drives:
        d = drives[0]
        return {"state": "bootsel", "drive": d["path"], "board_id": d["board_id"]}
    ports = env.serial_ports()
    for p in ports:
        try:
            pr = env.open_probe(p["device"])
        except ProbeError:
            continue
        try:
            kind, version = pr.identify()
            out = {"state": kind, "port": p["device"], "version": version,
                   "board": pr.board(), "pins": pr.get_pins()}
        except ProbeError:
            out = {"state": "unknown", "port": p["device"]}
        finally:
            pr.close()
        if out.get("pins"):
            want = cfg["pins"]
            out["pins_match"] = all(int(want[k]) == out["pins"][k] for k in ("rst", "dc", "dd_i", "dd_o"))
        return out
    picos = [p for p in ports if p["is_pico"]]
    if picos:
        return {"state": "unknown", "port": picos[0]["device"]}
    return {"state": "absent"}


def _wait_for(rep, predicate, seconds, interval=0.5):
    end = time.time() + seconds
    while time.time() < end:
        rep.check_cancel()
        v = predicate()
        if v:
            return v
        time.sleep(interval)
    return None


def install_probe(env, cfg, rep, pins=None, wait_bootsel=120):
    """Flash the MonopInk probe firmware on the Pico, then store the pins."""
    pins = pins or cfg["pins"]
    err = C.validate_pins(pins, HEADER_GPIOS)
    if err:
        raise OpError(err)
    rep.step("pico.flash.start")

    drives = env.drives()
    if not drives:
        touched = False
        for p in env.serial_ports():
            if p["is_pico"]:
                rep.info("pico.touch", port=p["device"])
                env.touch_1200(p["device"])
                touched = True
        if touched:
            drives = _wait_for(rep, env.drives, 8)
    if not drives:
        rep.action("pico.hold_bootsel")
        rep.info("pico.waiting_bootsel", s=wait_bootsel)
        drives = _wait_for(rep, env.drives, wait_bootsel)
    if not drives:
        raise OpError("pico.no_bootsel")

    drive = drives[0]
    rep.ok("pico.bootsel_found", path=drive["path"], board=drive["board_id"])
    uf2 = uf2_for(drive["board_id"])
    if not uf2 or not os.path.exists(uf2):
        raise OpError("pico.no_uf2", board=drive["board_id"])
    rep.info("pico.copying", file=os.path.basename(uf2))
    rep.progress(0, 1)
    env.copy_uf2(drive["path"], uf2)
    rep.progress(1, 1)
    rep.info("pico.rebooting")
    if not env.simulated:
        import sys
        if sys.platform == "darwin":
            rep.info("pico.macos_note")

    def find_probe():
        for p in env.serial_ports():
            try:
                pr = env.open_probe(p["device"])
            except ProbeError:
                continue
            if pr.identify()[0] == "monopink":
                return pr
            pr.close()
        return None

    pr = _wait_for(rep, find_probe, 25, interval=1.0)
    if not pr:
        raise OpError("pico.not_back", s=25)
    try:
        rep.ok("pico.back", version=pr.version, board=pr.board(), port=pr.port)
        _apply_pins(pr, pins, rep)
    finally:
        pr.close()
    return pico_status(env, cfg)


def _apply_pins(pr, pins, rep):
    p = {k: int(pins[k]) for k in ("rst", "dc", "dd_i", "dd_o")}
    pr.set_pins(p["rst"], p["dc"], p["dd_i"], p["dd_o"], save=True)
    back = pr.get_pins()
    if any(back[k] != p[k] for k in p):
        raise OpError("pico.pins_mismatch")
    rep.ok("pico.pins_set", **p)


def configure_probe(env, cfg, rep, pins=None):
    pins = pins or cfg["pins"]
    err = C.validate_pins(pins, HEADER_GPIOS)
    if err:
        raise OpError(err)
    pr = open_probe(env, cfg, rep)
    try:
        if not pr.is_monopink:
            raise OpError("pico.needs_monopink")
        _apply_pins(pr, pins, rep)
    finally:
        pr.close()


# ====================================================================== label
def _connect(pr, cfg, rep):
    if pr.is_monopink:
        have = pr.get_pins()
        want = cfg["pins"]
        if any(have[k] != int(want[k]) for k in ("rst", "dc", "dd_i", "dd_o")):
            rep.warn("probe.pins", **have)
            rep.warn("probe.pins_differ")
    rep.info("tag.connecting")
    chip = CC2510(pr, rep)
    try:
        info = chip.connect()
    except TagError as e:
        raise OpError(e.key, **e.kw)
    rep.ok("tag.found", **info)
    return chip, info


def tag_info(env, cfg, rep):
    pr = open_probe(env, cfg, rep)
    try:
        chip, info = _connect(pr, cfg, rep)
        if info["locked"]:
            rep.warn("tag.locked")
            info["firmware"] = None
        else:
            rep.info("tag.unlocked")
            fw = chip.firmware_info()
            info["firmware"] = fw
            if fw["installed"]:
                rep.ok("tag.fw_installed", version=fw["version"])
                if _version_tuple(fw["version"]) < _version_tuple(WANTED_FW):
                    rep.warn("tag.fw_outdated", have=fw["version"], want=WANTED_FW)
            elif fw["blank"]:
                rep.info("tag.fw_blank")
            else:
                rep.info("tag.fw_other")
        info["probe"] = {"kind": pr.kind, "version": pr.version, "port": pr.port}
        return info
    finally:
        pr.close()


def _version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def firmware_pages():
    mem = hexfile.load_hex(FIRMWARE_HEX)
    img = hexfile.to_flash_image(mem, L.FLASH_SIZE)
    pages = {}
    for pg in hexfile.used_pages(mem, L.PAGE_SIZE):
        a = pg * L.PAGE_SIZE
        if a >= L.IMG_REGION_START:
            continue
        pages[a] = bytes(img[a:a + L.PAGE_SIZE])
    # start with a clean NFC receive state
    pages[L.NFC_DESC_ADDR] = b"\xff" * L.PAGE_SIZE
    return pages


def image_pages(bw, red):
    region = L.image_region(bw, red)
    return {L.IMG_REGION_START + o: region[o:o + L.PAGE_SIZE]
            for o in range(0, len(region), L.PAGE_SIZE)}


def default_planes(cfg):
    from .image import convert, test_pattern, ImageParams
    p = ImageParams(mode="threshold", fit="stretch")
    conv = convert(test_pattern(), p)
    d = cfg.get("display", {})
    return conv.planes(d.get("rotate180", False), d.get("mirror", False))


def saved_planes():
    try:
        with open(LABEL_IMAGE, "rb") as f:
            data = f.read()
        if len(data) == 2 * L.PLANE_SIZE:
            return data[:L.PLANE_SIZE], data[L.PLANE_SIZE:]
    except OSError:
        pass
    return None


def save_planes(bw, red):
    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(LABEL_IMAGE, "wb") as f:
        f.write(bw + red)


def _program(chip, pages, rep):
    rep.info("tag.programming", n=len(pages))
    t0 = time.time()
    try:
        chip.program(pages, verify=True)
    except TagError as e:
        raise OpError(e.key, **e.kw)
    rep.ok("tag.programmed", n=len(pages), s=round(time.time() - t0, 1))


def _run(chip, rep):
    rep.info("tag.running")

    def on_state(state, elapsed):
        rep.run_state(state, round(elapsed, 1))
        rep.info("tag.state", state=state_text(state, rep.lang), t=round(elapsed, 1))

    res = chip.run_monitored(on_state=on_state)
    if not res["finished"]:
        raise OpError("tag.run_timeout", s=int(res["elapsed"]))
    return _check_refresh(res, rep)


def _check_refresh(res, rep, ok_key="tag.refresh_ok"):
    secs = round((res["refresh_ms"] or 0) / 1000, 1)
    res["refresh_s"] = secs
    err = res["error"]
    if err == L.ERR_BUSY_POWER_ON:
        raise OpError("tag.err_busy_on")
    if err == L.ERR_BUSY_REFRESH:
        raise OpError("tag.err_busy_refresh")
    if err == L.ERR_BUSY_POWER_OFF:
        rep.warn("tag.err_busy_off")
    if secs < 3:
        rep.warn("tag.refresh_too_fast", s=secs)
        res["suspicious"] = True
    else:
        rep.ok(ok_key, s=secs)
    return res


def tag_install(env, cfg, rep, erase=False, planes=None, run=True):
    rep.step("tag.install.start")
    pr = open_probe(env, cfg, rep)
    try:
        chip, info = _connect(pr, cfg, rep)
        if info["locked"]:
            rep.warn("tag.locked")
            if not erase:
                raise OpError("tag.locked_need_erase")
            rep.info("tag.erasing")
            try:
                chip.mass_erase()
            except TagError as e:
                raise OpError(e.key, **e.kw)
            rep.ok("tag.erased")
        if planes is None:
            planes = saved_planes()
        if planes is None:
            rep.info("tag.default_image")
            planes = default_planes(cfg)
        pages = firmware_pages()
        pages.update(image_pages(*planes))
        _program(chip, pages, rep)
        save_planes(*planes)
        result = {"programmed": len(pages), "firmware_version": WANTED_FW}
        if run:
            result["run"] = _run(chip, rep)
        return result
    finally:
        pr.close()


def tag_write_image(env, cfg, rep, bw, red, run=True):
    rep.step("tag.image.start")
    pr = open_probe(env, cfg, rep)
    try:
        chip, info = _connect(pr, cfg, rep)
        if info["locked"]:
            raise OpError("tag.no_firmware")
        fw = chip.firmware_info()
        if not fw["installed"]:
            raise OpError("tag.no_firmware")
        _program(chip, image_pages(bw, red), rep)
        save_planes(bw, red)
        result = {"programmed": 11}
        if run:
            result["run"] = _run(chip, rep)
        return result
    finally:
        pr.close()


def tag_run(env, cfg, rep):
    pr = open_probe(env, cfg, rep)
    try:
        chip, info = _connect(pr, cfg, rep)
        if info["locked"] or not chip.firmware_info()["installed"]:
            raise OpError("tag.no_firmware")
        return _run(chip, rep)
    finally:
        pr.close()


def tag_boot_test(env, cfg, rep, wait=None):
    """Autonomous boot test: plain reset (as on batteries), then read back
    what the firmware did.  Catches power problems the debug-mode runs hide."""
    wait = wait if wait is not None else (8 if env.simulated else 30)
    rep.step("boot.start")
    pr = open_probe(env, cfg, rep)
    try:
        if not pr.is_monopink:
            raise OpError("pico.needs_monopink")
        chip, info = _connect(pr, cfg, rep)
        fw = None if info["locked"] else chip.firmware_info()
        if not fw or not fw["installed"]:
            raise OpError("tag.no_firmware")
        if _version_tuple(fw["version"]) < (1, 2):
            raise OpError("tag.fw_outdated", have=fw["version"], want=WANTED_FW)
        chip.start_boot_test()
        rep.info("boot.waiting", s=wait)
        for i in range(int(wait * 10)):
            rep.check_cancel()
            time.sleep(0.1)
            rep.progress(i + 1, int(wait * 10))
        res = chip.read_boot_test()
        if res["state"] is None or res["state"] < L.ST_REFRESH_DONE:
            raise OpError("boot.incomplete", state=f"0x{res['state'] or 0:02x}")
        return _check_refresh(res, rep, ok_key="boot.ok")
    finally:
        pr.close()


# ====================================================================== NFC
def _decode_nfc_diag(d):
    b0, b38, b39, b3a = d[0x10:0x20], d[0x20:0x30], d[0x30:0x40], d[0x40:0x50]
    regs = d[8:16]
    return {
        "answers": bool(d[0] & 1),
        "variant": "2k" if d[0] & 2 else "1k",
        "fd_chip_off": d[1],
        "fd_chip_on": d[2],
        "wake": {1: "fd", 2: "poll"}.get(d[4], "?"),
        "uid": bytes(b0[0:7]).hex(),
        "static_lock": bytes(b0[10:12]).hex(),
        "cc": bytes(b0[12:16]).hex(),
        "dynamic_lock": bytes(b38[8:11]).hex(),
        "auth0": b38[15],
        "access": b39[0],
        "pt_i2c": b39[12],
        "config": bytes(b3a[0:8]).hex(),
        "nc_reg": regs[0],
        "ns_reg": regs[6],
        "ndef_start": bytes(d[0x50:0x90]).hex(),
    }


def nfc_info(env, cfg, rep):
    rep.step("nfc.info.start")
    pr = open_probe(env, cfg, rep)
    try:
        chip, info = _connect(pr, cfg, rep)
        fw = None if info["locked"] else chip.firmware_info()
        if not fw or not fw["installed"] or _version_tuple(fw["version"]) < (1, 3):
            raise OpError("nfc.need_fw13")
        try:
            raw = chip.nfc_diag()
        except TagError as e:
            raise OpError(e.key, **e.kw)
        d = _decode_nfc_diag(raw)
        if not d["answers"]:
            raise OpError("nfc.no_chip")
        rep.ok("nfc.chip", variant=d["variant"], uid=d["uid"])
        rep.info("nfc.details", cc=d["cc"], config=d["config"], auth0=d["auth0"],
                 access=d["access"], lock=d["static_lock"] + "/" + d["dynamic_lock"])
        rep.info("nfc.fd", off=d["fd_chip_off"], on=d["fd_chip_on"])
        if d["auth0"] < 0xEB:
            rep.warn("nfc.password")
        if d["wake"] == "fd":
            rep.ok("nfc.fd_wake")
        else:
            rep.warn("nfc.fd_polling")
        d["raw"] = bytes(raw).hex()
        return d
    finally:
        pr.close()


def nfc_send(env, cfg, rep, pixels):
    """Upload a picture through the NFC protocol, the Pico playing the phone."""
    from . import nfc
    stream, parts = nfc.encode_planes_pixels(pixels)
    rep.step("nfc.send.start", size=len(stream), n=len(parts))
    pr = open_probe(env, cfg, rep)
    try:
        chip, info = _connect(pr, cfg, rep)
        fw = None if info["locked"] else chip.firmware_info()
        if not fw or not fw["installed"] or _version_tuple(fw["version"]) < (1, 3):
            raise OpError("nfc.need_fw13")

        def on_state(state, elapsed):
            rep.run_state(state, round(elapsed, 1))

        last = None
        for i, payload in enumerate(parts):
            rep.check_cancel()
            try:
                res = chip.nfc_test_write(nfc.part_area(payload), on_state=on_state)
            except TagError as e:
                raise OpError(e.key, **e.kw)
            st = nfc.parse_status(res["status"])
            last = res
            rep.progress(i + 1, len(parts))
            if st is None or st["error"] != "ok":
                raise OpError("nfc.part_refused", i=i + 1, err=(st or {}).get("error", "?"))
            rep.info("nfc.part_ok", i=i + 1, n=len(parts), next=st["next"])
        mb = last["mailbox"]
        if last["result"] != 2:
            raise OpError("nfc.not_complete")
        from .image import pixels_to_planes
        save_planes(*pixels_to_planes(pixels))
        rep.ok("nfc.send.done", s=round((mb["refresh_ms"] or 0) / 1000, 1))
        return {"stream": len(stream), "parts": len(parts), "mailbox": mb}
    finally:
        pr.close()


def tag_reset(env, cfg, rep):
    pr = open_probe(env, cfg, rep)
    try:
        pr.reset_run(hold=False)
        rep.ok("tag.reset_done")
    finally:
        pr.close()


def tag_dump(env, cfg, rep, path):
    pr = open_probe(env, cfg, rep)
    try:
        chip, info = _connect(pr, cfg, rep)
        if info["locked"]:
            raise OpError("tag.locked")
        data = chip.read_flash()
        with open(path, "wb") as f:
            f.write(data)
        rep.ok("tag.dumped", path=path)
        return len(data)
    finally:
        pr.close()


def tag_flash_hex(env, cfg, rep, hex_text, erase=False, run=True):
    """Write any Intel HEX (e.g. the blink example or angrymew's firmware)."""
    try:
        mem = hexfile.parse_hex(hex_text)
        img = hexfile.to_flash_image(mem, L.FLASH_SIZE)
    except hexfile.HexError as e:
        raise OpError("hex.invalid", err=str(e))
    if not mem:
        raise OpError("hex.invalid", err="empty")
    pages = {pg * L.PAGE_SIZE: bytes(img[pg * L.PAGE_SIZE:(pg + 1) * L.PAGE_SIZE])
             for pg in hexfile.used_pages(mem, L.PAGE_SIZE)}
    rep.step("hex.start", n=len(mem))
    pr = open_probe(env, cfg, rep)
    try:
        chip, info = _connect(pr, cfg, rep)
        if info["locked"] and not erase:
            rep.warn("tag.locked")
            raise OpError("tag.locked_need_erase")
        if erase:
            rep.info("tag.erasing")
            try:
                chip.mass_erase()
            except TagError as e:
                raise OpError(e.key, **e.kw)
            rep.ok("tag.erased")
        _program(chip, pages, rep)
        if run:
            pr.reset_run(hold=False)
            rep.ok("hex.running")
        return {"programmed": len(pages)}
    finally:
        pr.close()


def full_hex(bw, red):
    """Firmware + picture as one Intel HEX (usable with any CC programmer)."""
    mem = hexfile.load_hex(FIRMWARE_HEX)
    img = hexfile.to_flash_image(mem, L.FLASH_SIZE)
    region = L.image_region(bw, red)
    img[L.IMG_REGION_START:L.IMG_REGION_END] = region
    return hexfile.dump_hex(bytes(img))


def images_c(bw, red):
    """C arrays compatible with angrymew/firmware-cc2510 (src/display/images.c)."""
    def arr(name, data):
        rows = [",".join(f"0x{b:02x}" for b in data[i:i + 19]) for i in range(0, len(data), 19)]
        return f"__code const uint8_t {name}[] = {{\n" + ",\n".join(rows) + "\n};\n"
    return "#include <stdint.h>\n\n" + arr("imageBW", bw) + "\n" + arr("imageR", red)
