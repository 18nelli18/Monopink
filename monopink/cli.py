"""Command line interface:  ./monopink.sh <command> [options]   (--help for details)"""
import argparse
import os
import sys
import time

from . import __version__
from . import config as C
from . import ops
from .i18n import t, norm_lang
from .pico import make_env, HEADER_GPIOS

COLORS = {"step": "\033[1m", "ok": "\033[32m", "warn": "\033[33m", "error": "\033[31m",
          "action": "\033[1;35m", "info": ""}
PREFIX = {"step": "==", "ok": "✔ ", "warn": "! ", "error": "✘ ", "action": ">>", "info": "  "}


class CliReporter(ops.Reporter):
    def __init__(self, lang):
        super().__init__(lang)
        self.tty = sys.stdout.isatty()
        self._bar = False

    def _clear_bar(self):
        if self._bar:
            sys.stdout.write("\r" + " " * 60 + "\r")
            self._bar = False

    def emit(self, level, text):
        self._clear_bar()
        pre = PREFIX.get(level, "  ")
        if self.tty and COLORS.get(level):
            print(f"{COLORS[level]}{pre} {text}\033[0m")
        else:
            print(f"{pre} {text}")
        sys.stdout.flush()

    def progress(self, done, total):
        if not self.tty or total <= 0:
            return
        frac = min(1.0, done / total)
        n = int(frac * 30)
        sys.stdout.write(f"\r   [{'#' * n}{'.' * (30 - n)}] {int(frac * 100):3d}%")
        sys.stdout.flush()
        self._bar = True
        if done >= total:
            self._clear_bar()


def ask_yes_no(question):
    """Prompt that ignores keystrokes typed before it appeared."""
    if not sys.stdin.isatty():
        return False
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass
    try:
        ans = input(f"{question} [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes", "o", "oui")


# ---------------------------------------------------------------- arguments
def add_pin_args(p):
    g = p.add_argument_group("pins (Pico GPIO numbers)")
    g.add_argument("--rst", type=int, help="GPIO wired to RESET_N (default 3)")
    g.add_argument("--dc", type=int, help="GPIO wired to DC / P2_2 (default 4)")
    g.add_argument("--dd", type=int, help="single GPIO wired to DD / P2_1 (sets DD_IN = DD_OUT)")
    g.add_argument("--dd-in", type=int, help="GPIO reading DD (default 6)")
    g.add_argument("--dd-out", type=int, help="GPIO driving DD (default 7, bridged with DD_IN)")


def pins_from_args(args, cfg):
    pins = dict(cfg["pins"])
    if args.rst is not None:
        pins["rst"] = args.rst
    if args.dc is not None:
        pins["dc"] = args.dc
    if args.dd is not None:
        pins["dd_i"] = pins["dd_o"] = args.dd
    if args.dd_in is not None:
        pins["dd_i"] = args.dd_in
    if args.dd_out is not None:
        pins["dd_o"] = args.dd_out
    return pins


def add_image_args(p):
    g = p.add_argument_group("conversion")
    g.add_argument("--orientation", choices=["portrait", "landscape"])
    g.add_argument("--fit", choices=["cover", "contain", "stretch"])
    g.add_argument("--mode", choices=["dither", "threshold", "levels"])
    g.add_argument("--no-red", action="store_true", help="black and white only")
    g.add_argument("--brightness", type=int, metavar="-100..100")
    g.add_argument("--contrast", type=int, metavar="-100..100")
    g.add_argument("--red-sensitivity", type=int, metavar="0..100",
                   help="how reddish a colour must be to print red (default 50)")
    g.add_argument("--black-level", type=int, metavar="0..255", help="levels mode")
    g.add_argument("--white-level", type=int, metavar="0..255", help="levels mode")
    g.add_argument("--invert", action="store_true")
    g.add_argument("--fill-enclosed", action="store_true",
                   help="white areas enclosed by black become red")
    g.add_argument("--sharp", action="store_true", help="nearest-neighbour resize (logos)")
    g.add_argument("--background", choices=["white", "black", "red"])


def params_from_args(args, cfg):
    from .image import ImageParams
    d = dict(cfg.get("image") or {})
    for name in ("orientation", "fit", "mode", "brightness", "contrast", "red_sensitivity",
                 "black_level", "white_level", "background"):
        v = getattr(args, name, None)
        if v is not None:
            d[name] = v
    for flag in ("invert", "fill_enclosed", "sharp"):
        if getattr(args, flag, False):
            d[flag] = True
    if getattr(args, "no_red", False):
        d["use_red"] = False
    return ImageParams.from_dict(d)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="monopink",
        description="MonopInk - put your own pictures on a VUSION 2.6 BWR (GL420) e-ink label.")
    ap.add_argument("--version", action="version", version=f"MonopInk {__version__}")
    ap.add_argument("--sim", action="store_true", help="simulate the hardware (try without a Pico)")
    ap.add_argument("--lang", choices=["en", "fr"], help="message language")
    ap.add_argument("--port", help="serial port of the Pico (default: auto)")
    sub = ap.add_subparsers(dest="cmd", metavar="command")

    p = sub.add_parser("web", help="start the web interface (default)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--http-port", type=int, default=8420)
    p.add_argument("--no-browser", action="store_true")

    sub.add_parser("doctor", help="check the installation")
    sub.add_parser("ports", help="list serial ports, BOOTSEL drives and probes")

    p = sub.add_parser("pico-flash", help="install the MonopInk probe firmware on the Pico")
    add_pin_args(p)
    p.add_argument("--wait", type=int, default=120, help="seconds to wait for BOOTSEL (default 120)")
    p = sub.add_parser("pico-pins", help="change the pins stored in the Pico (no reflash)")
    add_pin_args(p)

    sub.add_parser("info", help="identify the label (chip, lock, firmware)")

    p = sub.add_parser("install", help="install the MonopInk firmware on the label")
    p.add_argument("--erase", action="store_true", help="allow the mass erase of a locked chip")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--no-run", action="store_true", help="do not start the display afterwards")

    p = sub.add_parser("image", help="convert a picture and send it to the label")
    p.add_argument("file")
    add_image_args(p)
    p.add_argument("--preview", metavar="PNG", help="also save a preview")
    p.add_argument("--dry-run", action="store_true", help="convert only, do not flash")

    sub.add_parser("test-pattern", help="send the orientation test card to the label")
    sub.add_parser("run", help="restart the label firmware and watch the refresh")
    sub.add_parser("reset", help="plain reset of the label (normal boot)")
    sub.add_parser("boot-test", help="autonomous start test: plain reset as on batteries, then check the result")
    p = sub.add_parser("dump", help="save the whole flash of an unlocked label")
    p.add_argument("out")

    p = sub.add_parser("flash-hex", help="write any Intel HEX firmware (blink, angrymew...)")
    p.add_argument("file")
    p.add_argument("--erase", action="store_true", help="mass erase first (needed on a locked chip)")
    p.add_argument("--no-run", action="store_true", help="leave the chip halted")

    p = sub.add_parser("export", help="convert a picture to files (no hardware needed)")
    p.add_argument("file")
    add_image_args(p)
    p.add_argument("--png", help="preview PNG")
    p.add_argument("--hex", help="firmware + picture, Intel HEX (for any CC programmer)")
    p.add_argument("--bin", help="raw planes (5624 bytes black/white + 5624 bytes red)")
    p.add_argument("--c", dest="c_file", help="images.c for angrymew/firmware-cc2510")

    p = sub.add_parser("config", help="show or change saved settings")
    add_pin_args(p)
    p.add_argument("--set-port", help="serial port or 'auto'")
    p.add_argument("--set-lang", choices=["en", "fr", "auto"])
    p.add_argument("--rotate180", choices=["on", "off"], help="display calibration")
    p.add_argument("--mirror", choices=["on", "off"], help="display calibration")
    return ap


# ---------------------------------------------------------------- commands
def cmd_doctor(rep, env, cfg):
    ok = True

    def line(good, text):
        nonlocal ok
        ok &= good
        rep.emit("ok" if good else "error", text)

    line(sys.version_info >= (3, 8), f"Python {sys.version.split()[0]}")
    try:
        import serial
        line(True, f"pyserial {serial.__version__}")
    except ImportError:
        line(False, t("deps.missing", rep.lang, pkg="pyserial"))
    try:
        import PIL
        line(True, f"Pillow {PIL.__version__}")
    except ImportError:
        line(False, t("deps.missing", rep.lang, pkg="Pillow"))
    from .pico import UF2
    for path in list(UF2.values()) + [ops.FIRMWARE_HEX]:
        line(os.path.exists(path), os.path.relpath(path, C.ROOT))
    return 0 if ok else 1


def cmd_ports(rep, env, cfg):
    for d in env.drives():
        rep.emit("ok", f"BOOTSEL: {d['path']}  ({d['board_id']})")
    ports = env.serial_ports()
    if not ports:
        rep.emit("warn", t("probe.not_found", rep.lang))
    for p in ports:
        tag = " [Raspberry Pi]" if p["is_pico"] else ""
        desc = ""
        try:
            pr = env.open_probe(p["device"])
            kind, version = pr.identify()
            desc = " -> " + ops._describe(rep, kind, version, pr.board())
            pins = pr.get_pins()
            if pins:
                desc += "  " + t("probe.pins", rep.lang, **pins)
            pr.close()
        except Exception:
            pass
        rep.emit("info", f"{p['device']}{tag}  {p['description']}{desc}")
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = C.load()
    lang = norm_lang(args.lang or cfg.get("lang") or "")
    if args.port:
        cfg["port"] = args.port
    rep = CliReporter(lang)
    env = make_env(args.sim)
    if args.sim:
        rep.emit("warn", t("sim.banner", lang))
    cmd = args.cmd or "web"

    try:
        if cmd == "web":
            from .web.server import serve
            return serve(host=getattr(args, "host", "127.0.0.1"),
                         port=getattr(args, "http_port", 8420),
                         simulate=args.sim,
                         open_browser=not getattr(args, "no_browser", False))
        if cmd == "doctor":
            return cmd_doctor(rep, env, cfg)
        if cmd == "ports":
            return cmd_ports(rep, env, cfg)

        if cmd in ("pico-flash", "pico-pins", "config"):
            pins = pins_from_args(args, cfg)
            err = C.validate_pins(pins, HEADER_GPIOS)
            if err:
                rep.emit("error", t(err, lang))
                return 2
            if pins != cfg["pins"]:
                cfg = C.update({"pins": pins})
            if cmd == "pico-flash":
                ops.install_probe(env, cfg, rep, pins, wait_bootsel=args.wait)
            elif cmd == "pico-pins":
                ops.configure_probe(env, cfg, rep, pins)
            else:
                changes = {}
                if args.set_port:
                    changes["port"] = args.set_port
                if args.set_lang:
                    changes["lang"] = "" if args.set_lang == "auto" else args.set_lang
                disp = {}
                if args.rotate180:
                    disp["rotate180"] = args.rotate180 == "on"
                if args.mirror:
                    disp["mirror"] = args.mirror == "on"
                if disp:
                    changes["display"] = disp
                if changes:
                    cfg = C.update(changes)
                import json
                print(json.dumps(cfg, indent=2, ensure_ascii=False))
                print(f"({C.CONFIG_PATH})")
            return 0

        if cmd == "info":
            ops.tag_info(env, cfg, rep)
            return 0

        if cmd == "install":
            erase = args.erase
            if not erase:
                info = ops.tag_info(env, cfg, rep)
                if info["locked"]:
                    if args.yes or ask_yes_no(t("tag.locked", lang) + "\n  " +
                                              ("Erase it now?" if lang == "en" else "L'effacer maintenant ?")):
                        erase = True
                    else:
                        rep.emit("error", t("op.cancelled", lang))
                        return 1
            ops.tag_install(env, cfg, rep, erase=erase, run=not args.no_run)
            return 0

        if cmd in ("image", "export", "test-pattern"):
            from .image import open_image, convert, test_pattern, ImageParams
            if cmd == "test-pattern":
                conv = convert(test_pattern(), ImageParams(mode="threshold", fit="stretch"))
            else:
                with open(args.file, "rb") as f:
                    src = open_image(f.read())
                params = params_from_args(args, cfg)
                conv = convert(src, params)
            rep.emit("ok", t("image.converted", lang, **conv.stats()))
            disp = cfg.get("display", {})
            bw, red = conv.planes(disp.get("rotate180", False), disp.get("mirror", False))
            outputs = []
            if cmd != "test-pattern":
                outputs.append((getattr(args, "preview", None) or getattr(args, "png", None), conv.preview(3), "wb"))
            if cmd == "export":
                if args.hex:
                    outputs.append((args.hex, ops.full_hex(bw, red), "w"))
                if args.bin:
                    outputs.append((args.bin, bw + red, "wb"))
                if args.c_file:
                    outputs.append((args.c_file, ops.images_c(bw, red), "w"))
            for path, data, mode in outputs:
                if path:
                    with open(path, mode) as f:
                        f.write(data)
                    rep.emit("ok", t("image.saved", lang, path=path))
            if cmd == "export" or getattr(args, "dry_run", False):
                return 0
            ops.tag_write_image(env, cfg, rep, bw, red)
            return 0

        if cmd == "flash-hex":
            with open(args.file, "r", encoding="ascii", errors="replace") as f:
                ops.tag_flash_hex(env, cfg, rep, f.read(), erase=args.erase, run=not args.no_run)
            return 0
        if cmd == "run":
            ops.tag_run(env, cfg, rep)
            return 0
        if cmd == "reset":
            ops.tag_reset(env, cfg, rep)
            return 0
        if cmd == "boot-test":
            ops.tag_boot_test(env, cfg, rep)
            return 0
        if cmd == "dump":
            ops.tag_dump(env, cfg, rep, args.out)
            return 0
    except ops.OpError as e:
        rep.emit("error", t(e.key, lang, **e.kw))
        return 1
    except ops.Cancelled:
        rep.emit("error", t("op.cancelled", lang))
        return 1
    except KeyboardInterrupt:
        rep.emit("error", t("op.cancelled", lang))
        return 130
    except Exception as e:     # ProbeError, OSError...
        rep.emit("error", t("op.failed", lang, err=e))
        return 1
    return 0
