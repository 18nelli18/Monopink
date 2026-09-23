"""Local web interface: a small JSON API + a static single-page app.

Only listens on 127.0.0.1.  Hardware actions run as background "jobs" whose
log and progress the page polls.  POST requests must carry the header
X-MonopInk: 1, which a foreign web page cannot add without a CORS preflight
(that this server never grants) - so other sites cannot drive the hardware.
"""
import base64
import io
import json
import mimetypes
import os
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .. import __version__
from .. import config as C
from .. import ops
from .. import sim
from ..i18n import t, norm_lang
from ..pico import make_env, HEADER_GPIOS

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
# phone page for NFC uploads (also published over HTTPS, e.g. GitHub Pages)
NFC_PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs", "nfc")
SOURCE_PATH = os.path.join(C.DATA_DIR, "source.png")
MAX_UPLOAD = 30 * 1024 * 1024


# ====================================================================== jobs
class Job:
    def __init__(self, op, lang):
        self.id = uuid.uuid4().hex[:12]
        self.op = op
        self.lang = lang
        self.status = "running"
        self.log = []
        self.progress = None
        self.run_states = []
        self.result = None
        self.error = None
        self.started = time.time()
        self.finished = None
        self.reporter = JobReporter(self)

    def snapshot(self, since=0):
        return {
            "id": self.id, "op": self.op, "status": self.status,
            "log": self.log[since:], "next": len(self.log),
            "progress": self.progress, "run_states": self.run_states, "result": self.result, "error": self.error,
            "elapsed": round((self.finished or time.time()) - self.started, 1),
        }


class JobReporter(ops.Reporter):
    def __init__(self, job):
        super().__init__(job.lang)
        self.job = job

    def emit(self, level, text):
        self.job.log.append({"level": level, "text": text, "t": round(time.time() - self.job.started, 1)})

    def progress(self, done, total):
        self.job.progress = {"done": done, "total": total}

    def run_state(self, state, elapsed):
        self.job.run_states.append({"state": state, "t": elapsed})


class App:
    def __init__(self, simulate=False):
        self.simulate = simulate
        self.env = make_env(simulate)
        self.jobs = {}
        self.current = None
        self.lock = threading.Lock()
        self.source = None
        self.source_name = None
        self._load_source()

    # ----------------------------------------------------------------- state
    def cfg(self):
        return C.load()

    def lang(self, requested=None):
        return norm_lang(requested or self.cfg().get("lang") or "")

    def busy(self):
        return self.current is not None and self.current.status == "running"

    def start_job(self, op, func, lang):
        with self.lock:
            if self.busy():
                return None
            job = Job(op, lang)
            self.jobs[job.id] = job
            self.current = job
            if len(self.jobs) > 30:
                for k in sorted(self.jobs, key=lambda k: self.jobs[k].started)[:-30]:
                    del self.jobs[k]

        def run():
            rep = job.reporter
            try:
                job.result = func(rep)
                job.status = "done"
            except ops.OpError as e:
                job.error = t(e.key, lang, **e.kw)
                rep.emit("error", job.error)
                job.status = "error"
            except ops.Cancelled:
                job.error = t("op.cancelled", lang)
                rep.emit("error", job.error)
                job.status = "cancelled"
            except Exception as e:
                traceback.print_exc()
                job.error = t("op.failed", lang, err=e)
                rep.emit("error", job.error)
                job.status = "error"
            finally:
                job.finished = time.time()

        threading.Thread(target=run, daemon=True).start()
        return job

    # ----------------------------------------------------------------- image
    def _load_source(self):
        try:
            from ..image import open_image
            with open(SOURCE_PATH, "rb") as f:
                self.source = open_image(f.read())
            self.source_name = self.cfg().get("image_name") or "source.png"
        except Exception:
            self.source = None

    def set_source(self, img, name):
        self.source = img
        self.source_name = name
        os.makedirs(C.DATA_DIR, exist_ok=True)
        copy = img.copy()
        copy.thumbnail((1600, 1600))
        copy.save(SOURCE_PATH, "PNG")
        C.update({"image_name": name})

    def convert(self, params_dict):
        from ..image import convert, ImageParams
        if self.source is None:
            raise ops.OpError("image.none")
        params = ImageParams.from_dict(params_dict)
        return convert(self.source, params)

    def planes(self, conv):
        d = self.cfg().get("display", {})
        return conv.planes(d.get("rotate180", False), d.get("mirror", False))

    def panel_pixels(self, conv):
        d = self.cfg().get("display", {})
        return conv.panel_pixels(d.get("rotate180", False), d.get("mirror", False))


APP = None


# ====================================================================== HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "MonopInk/" + __version__

    def log_message(self, fmt, *args):     # keep the terminal quiet
        pass

    # ----------------------------------------------------------------- helpers
    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]", "::1")

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    def _error(self, code, message):
        self._send(code, {"ok": False, "error": message})

    # ----------------------------------------------------------------- GET
    def do_GET(self):
        if not self._host_ok():
            return self._error(403, "forbidden host")
        url = urlparse(self.path)
        path = url.path
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if path == "/" or path == "/index.html":
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/nfc":
                return self._send(301, b"", "text/plain", {"Location": "/nfc/"})
            if path.startswith("/nfc/"):
                return self._static(path[len("/nfc/"):] or "index.html", NFC_PAGE)
            if path == "/api/state":
                return self._send(200, self._state())
            if path == "/api/pico/status":
                if APP.busy():
                    return self._send(200, {"state": "busy"})
                with APP.lock:
                    return self._send(200, ops.pico_status(APP.env, APP.cfg()))
            if path == "/api/ports":
                return self._send(200, {"ports": APP.env.serial_ports(), "drives": APP.env.drives()})
            if path.startswith("/api/jobs/"):
                job = APP.jobs.get(path.split("/")[3])
                if not job:
                    return self._error(404, "no such job")
                return self._send(200, job.snapshot(int(q.get("since", 0))))
            if path == "/api/image/source":
                if APP.source is None:
                    return self._error(404, "no image")
                buf = io.BytesIO()
                thumb = APP.source.copy()
                thumb.thumbnail((600, 600))
                thumb.save(buf, "PNG")
                return self._send(200, buf.getvalue(), "image/png")
            if path == "/api/image/export":
                return self._export(q)
            if path == "/api/label/preview":
                return self._label_preview()
            if path == "/api/label/dump":
                dump = os.path.join(C.DATA_DIR, "flash-dump.bin")
                if not os.path.exists(dump):
                    return self._error(404, "no dump")
                with open(dump, "rb") as f:
                    return self._send(200, f.read(), "application/octet-stream",
                                      {"Content-Disposition": 'attachment; filename="monopink-flash.bin"'})
            return self._error(404, "not found")
        except ops.OpError as e:
            return self._error(400, t(e.key, APP.lang(q.get("lang")), **e.kw))
        except Exception as e:
            traceback.print_exc()
            return self._error(500, str(e))

    def _static(self, rel, root=STATIC):
        full = os.path.normpath(os.path.join(root, rel))
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            return self._error(404, "not found")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def _state(self):
        cfg = APP.cfg()
        deps = {}
        try:
            import serial  # noqa: F401
            deps["pyserial"] = True
        except ImportError:
            deps["pyserial"] = False
        try:
            import PIL  # noqa: F401
            deps["pillow"] = True
        except ImportError:
            deps["pillow"] = False
        from ..pico import UF2
        files = {os.path.basename(p): os.path.exists(p) for p in list(UF2.values()) + [ops.FIRMWARE_HEX]}
        state = {
            "version": __version__,
            "simulate": APP.simulate,
            "lang": APP.lang(),
            "config": cfg,
            "header_gpios": HEADER_GPIOS,
            "deps": deps,
            "files": files,
            "busy": APP.busy(),
            "current_job": APP.current.id if APP.busy() else None,
            "current_op": APP.current.op if APP.busy() else None,
            "has_source": APP.source is not None,
            "source_name": APP.source_name,
            "has_label_image": ops.saved_planes() is not None,
        }
        if APP.simulate:
            w = sim.world()
            state["sim"] = {"connected": w.chip.connected, "wired": w.wired,
                            "locked": w.chip.locked, "pico_fw": w.pico_fw}
        return state

    def _export(self, q):
        fmt = q.get("fmt", "png")
        params = json.loads(q.get("params") or "{}")
        conv = APP.convert(params)
        base = os.path.splitext(APP.source_name or "image")[0] or "image"
        if fmt == "png":
            return self._send(200, conv.preview(3), "image/png",
                              {"Content-Disposition": f'attachment; filename="{base}-epaper.png"'})
        bw, red = APP.planes(conv)
        if fmt == "hex":
            data, name, ctype = ops.full_hex(bw, red), f"{base}-monopink.hex", "text/plain"
        elif fmt == "bin":
            data, name, ctype = bw + red, f"{base}-planes.bin", "application/octet-stream"
        elif fmt == "c":
            data, name, ctype = ops.images_c(bw, red), "images.c", "text/plain"
        else:
            return self._error(400, "unknown format")
        return self._send(200, data, ctype, {"Content-Disposition": f'attachment; filename="{name}"'})

    def _label_preview(self):
        from ..image import planes_to_pixels, Converted, ImageParams
        from .. import layout as L
        planes = ops.saved_planes()
        if planes is None:
            return self._error(404, "nothing flashed yet")
        px = planes_to_pixels(*planes)
        d = APP.cfg().get("display", {})
        # undo the calibration so the preview matches what the user sees
        conv = Converted(px, (L.EPD_WIDTH, L.EPD_HEIGHT), ImageParams())
        w = L.EPD_WIDTH
        if d.get("mirror"):
            px = [px[y * w + (w - 1 - x)] for y in range(L.EPD_HEIGHT) for x in range(w)]
        if d.get("rotate180"):
            px = px[::-1]
        conv.pixels = px
        png = conv.preview(2)
        if APP.cfg().get("label_orientation") == "landscape":
            from PIL import Image
            img = Image.open(io.BytesIO(png)).rotate(90, expand=True)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            png = buf.getvalue()
        return self._send(200, png, "image/png")

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-MonopInk") != "1":
            return self._error(403, "forbidden")
        path = urlparse(self.path).path
        try:
            if path == "/api/image/upload":
                return self._upload()
            body = self._json_body()
            lang = APP.lang(body.get("lang"))
            if path == "/api/config":
                return self._config(body, lang)
            if path == "/api/jobs":
                return self._new_job(body, lang)
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job = APP.jobs.get(path.split("/")[3])
                if job:
                    job.reporter.cancelled = True
                return self._send(200, {"ok": True})
            if path == "/api/image/preview":
                conv = APP.convert(body.get("params") or {})
                C.update({"image": conv.params.to_dict()})
                png = conv.preview(3)
                return self._send(200, {
                    "ok": True, "stats": conv.stats(),
                    "width": conv.size[0], "height": conv.size[1],
                    "preview": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
                })
            if path == "/api/image/test-pattern":
                from ..image import test_pattern
                APP.set_source(test_pattern(body.get("orientation") or "portrait"), "test-pattern.png")
                return self._send(200, {"ok": True})
            if path == "/api/sim" and APP.simulate:
                w = sim.world()
                if body.get("reset"):
                    w.reset()
                if "connected" in body:
                    w.chip.connected = bool(body["connected"])
                if "wired" in body:
                    w.wired.update({k: int(v) for k, v in body["wired"].items()})
                if body.get("pico_fw") in ("blank", "cclib", "monopink"):
                    w.pico_fw = body["pico_fw"]
                if "bootsel" in body:
                    w.bootsel = bool(body["bootsel"])
                return self._send(200, {"ok": True})
            return self._error(404, "not found")
        except ops.OpError as e:
            return self._error(400, t(e.key, APP.lang(), **e.kw))
        except Exception as e:
            traceback.print_exc()
            return self._error(500, str(e))

    def _config(self, body, lang):
        changes = {}
        if "pins" in body:
            pins = {k: int(body["pins"][k]) for k in ("rst", "dc", "dd_i", "dd_o")}
            err = C.validate_pins(pins, HEADER_GPIOS)
            if err:
                return self._error(400, t(err, lang))
            changes["pins"] = pins
        if "port" in body:
            changes["port"] = str(body["port"] or "auto")
        if "lang" in body:
            changes["lang"] = body["lang"] if body["lang"] in ("en", "fr") else ""
        if "display" in body:
            changes["display"] = {k: bool(body["display"][k]) for k in ("rotate180", "mirror")
                                  if k in body["display"]}
        if "nfc_url" in body:
            url = str(body["nfc_url"] or "").strip()
            if url and (not url.startswith("https://") or len(url) > 300 or any(c in url for c in " <>\"'")):
                return self._error(400, t("nfc.url_invalid", lang))
            changes["nfc_url"] = url
        cfg = C.update(changes)
        return self._send(200, {"ok": True, "config": cfg})

    def _upload(self):
        from ..image import open_image
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_UPLOAD:
            return self._error(413, "file too large (max 30 MB)")
        data = self.rfile.read(n)
        name = os.path.basename(self.headers.get("X-Filename") or "image")
        try:
            img = open_image(data)
        except Exception:
            lang = APP.lang(self.headers.get("X-Lang"))
            msg = "Unsupported image format." if lang == "en" else "Format d'image non supporté."
            return self._error(400, msg)
        APP.set_source(img, name)
        return self._send(200, {"ok": True, "width": img.width, "height": img.height, "name": name})

    def _new_job(self, body, lang):
        op = body.get("op")
        args = body.get("args") or {}
        cfg = APP.cfg()
        env = APP.env

        if op == "pico_flash":
            pins = args.get("pins") or cfg["pins"]
            func = lambda rep: ops.install_probe(env, cfg, rep, pins, wait_bootsel=int(args.get("wait", 120)))
        elif op == "pico_pins":
            pins = args.get("pins") or cfg["pins"]
            func = lambda rep: ops.configure_probe(env, cfg, rep, pins)
        elif op == "tag_info":
            func = lambda rep: ops.tag_info(env, cfg, rep)
        elif op == "tag_install":
            erase = bool(args.get("erase"))

            def func(rep):
                had_image = ops.saved_planes() is not None
                res = ops.tag_install(env, cfg, rep, erase=erase)
                if not had_image:
                    C.update({"label_orientation": "portrait"})
                return res
        elif op == "tag_image":
            conv = APP.convert(args.get("params") or cfg.get("image") or {})
            bw, red = APP.planes(conv)

            def func(rep):
                res = ops.tag_write_image(env, cfg, rep, bw, red)
                C.update({"label_orientation": conv.params.orientation})
                return res
        elif op == "tag_hex":
            text = str(args.get("hex") or "")
            erase = bool(args.get("erase"))
            if len(text) > 400_000:
                return self._error(413, "file too large")
            func = lambda rep: ops.tag_flash_hex(env, cfg, rep, text, erase=erase)
        elif op == "nfc_info":
            func = lambda rep: ops.nfc_info(env, cfg, rep)
        elif op == "nfc_send":
            conv = APP.convert(args.get("params") or cfg.get("image") or {})
            px = APP.panel_pixels(conv)

            def func(rep):
                res = ops.nfc_send(env, cfg, rep, px)
                C.update({"label_orientation": conv.params.orientation})
                return res
        elif op == "tag_run":
            func = lambda rep: ops.tag_run(env, cfg, rep)
        elif op == "tag_boottest":
            func = lambda rep: ops.tag_boot_test(env, cfg, rep)
        elif op == "tag_reset":
            func = lambda rep: ops.tag_reset(env, cfg, rep)
        elif op == "tag_dump":
            path = os.path.join(C.DATA_DIR, "flash-dump.bin")
            os.makedirs(C.DATA_DIR, exist_ok=True)
            func = lambda rep: {"path": path, "size": ops.tag_dump(env, cfg, rep, path)}
        else:
            return self._error(400, "unknown operation")

        job = APP.start_job(op, func, lang)
        if job is None:
            return self._error(409, t("op.busy", lang))
        return self._send(200, {"ok": True, "id": job.id})


def serve(host="127.0.0.1", port=8420, simulate=False, open_browser=True):
    global APP
    APP = App(simulate=simulate)
    httpd = None
    for p in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print(f"Cannot listen on ports {port}-{port + 9}")
        return 1
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    lang = APP.lang()
    print("MonopInk", __version__, "-", "simulation" if simulate else "hardware mode")
    print(("Web interface: " if lang == "en" else "Interface web : ") + url)
    print("Ctrl+C " + ("to stop." if lang == "en" else "pour arrêter."))
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
