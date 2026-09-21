"""Picture -> 3-colour e-paper conversion (152 x 296, black / white / red).

Panel buffer conventions (IL0373 in KWR mode, as set by the firmware):
  * black/white plane (cmd 0x10): bit 1 = white, 0 = black
  * red plane         (cmd 0x13): bit 0 = red,   1 = no red (red wins)
  * 19 bytes per row, MSB = leftmost pixel, 296 rows.
"""
import io
from dataclasses import dataclass, asdict, fields

from . import layout as L

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps
except ImportError:      # reported nicely by the CLI / web server
    Image = None

WHITE, BLACK, RED = 0, 1, 2

# colours used for the on-screen preview (what the panel roughly looks like)
PREVIEW_RGB = {WHITE: (233, 230, 219), BLACK: (32, 32, 36), RED: (190, 38, 44)}
# colours used when matching the picture to the palette
MATCH_RGB = {WHITE: (255, 255, 255), BLACK: (0, 0, 0), RED: (215, 25, 32)}


@dataclass
class ImageParams:
    orientation: str = "portrait"   # portrait (152x296) | landscape (296x152)
    fit: str = "cover"              # cover | contain | stretch
    mode: str = "dither"            # dither | threshold | levels
    use_red: bool = True
    brightness: int = 0             # -100..100
    contrast: int = 0               # -100..100
    red_sensitivity: int = 50       # 0..100: how reddish a pixel must be to print red
    black_level: int = 85           # levels mode: below -> black
    white_level: int = 170          # levels mode: above -> white (between -> red)
    invert: bool = False
    fill_enclosed: bool = False     # white areas enclosed in black -> red
    sharp: bool = False             # nearest-neighbour resize (logos, pixel art)
    background: str = "white"       # contain padding: white | black | red

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        kw = {}
        for f in fields(cls):
            if f.name in d and d[f.name] is not None:
                v = d[f.name]
                if f.type in ("int", int):
                    v = int(v)
                elif f.type in ("bool", bool):
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
                else:
                    v = str(v)
                kw[f.name] = v
        p = cls(**kw)
        p.clamp()
        return p

    def clamp(self):
        for name in ("brightness", "contrast"):
            setattr(self, name, max(-100, min(100, getattr(self, name))))
        self.red_sensitivity = max(0, min(100, self.red_sensitivity))
        self.black_level = max(0, min(255, self.black_level))
        self.white_level = max(self.black_level, min(255, self.white_level))
        if self.orientation not in ("portrait", "landscape"):
            self.orientation = "portrait"
        if self.fit not in ("cover", "contain", "stretch"):
            self.fit = "cover"
        if self.mode not in ("dither", "threshold", "levels"):
            self.mode = "dither"
        if self.background not in ("white", "black", "red"):
            self.background = "white"

    def to_dict(self):
        return asdict(self)


def _data(img):
    """Pixel values (Pillow >= 12 renamed getdata to get_flattened_data)."""
    if hasattr(img, "get_flattened_data"):
        return img.get_flattened_data()
    return img.getdata()


def require_pillow():
    if Image is None:
        raise RuntimeError("Pillow is not installed (pip install Pillow)")


def open_image(data: bytes):
    require_pillow()
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        img = bg
    return img.convert("RGB")


def design_size(p: ImageParams):
    if p.orientation == "landscape":
        return L.EPD_HEIGHT, L.EPD_WIDTH
    return L.EPD_WIDTH, L.EPD_HEIGHT


def _fit(img, p: ImageParams):
    w, h = design_size(p)
    rs = Image.NEAREST if p.sharp else Image.LANCZOS
    if p.fit == "stretch":
        return img.resize((w, h), rs)
    if p.fit == "cover":
        return ImageOps.fit(img, (w, h), method=rs, centering=(0.5, 0.5))
    # contain
    scaled = ImageOps.contain(img, (w, h), method=rs)
    bg = Image.new("RGB", (w, h), MATCH_RGB[{"white": WHITE, "black": BLACK, "red": RED}[p.background]])
    bg.paste(scaled, ((w - scaled.width) // 2, (h - scaled.height) // 2))
    return bg


def _adjust(img, p: ImageParams):
    if p.invert:
        img = ImageOps.invert(img)
    if p.brightness:
        img = ImageEnhance.Brightness(img).enhance(1 + p.brightness / 100)
    if p.contrast:
        img = ImageEnhance.Contrast(img).enhance(1 + p.contrast / 100)
    return img


def _red_mask(img, p: ImageParams):
    """1 where the pixel is reddish enough to be printed red."""
    if not p.use_red:
        return [0] * (img.width * img.height)
    # "redness" = how much R dominates G and B; sensitivity 50 -> 60
    thr = 140 - int(1.6 * p.red_sensitivity)
    return [1 if (r > 90 and r - max(g, b) > thr) else 0 for r, g, b in _data(img)]


def _quantize(img, p: ImageParams):
    """Return a list of palette indices (row-major, design orientation).

    Red is decided on hue first (reddish pixels), everything else is rendered
    in pure black and white, so greys never turn into red speckles.
    """
    red = _red_mask(img, p)
    lum = img.convert("L")
    if p.mode == "levels":
        out = []
        for v, r in zip(_data(lum), red):
            if r:
                out.append(RED)
            elif v < p.black_level:
                out.append(BLACK)
            elif v <= p.white_level:
                out.append(RED if p.use_red else (BLACK if v < (p.black_level + p.white_level) / 2 else WHITE))
            else:
                out.append(WHITE)
        return out
    if p.mode == "dither":
        # dither the non-red part only (red areas painted white first so they
        # do not leak dark error into their neighbours)
        if any(red):
            lum = lum.copy()
            lum.putdata([255 if r else v for v, r in zip(_data(lum), red)])
        bw = lum.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    else:
        bw = lum.point(lambda v: 255 if v >= 128 else 0).convert("1", dither=Image.Dither.NONE)
    return [RED if r else (WHITE if v else BLACK) for v, r in zip(_data(bw), red)]


def _fill_enclosed(pix, w, h):
    """White regions that do not touch the border become red."""
    outside = bytearray(w * h)
    stack = []
    for x in range(w):
        stack += [(x, 0), (x, h - 1)]
    for y in range(h):
        stack += [(0, y), (w - 1, y)]
    while stack:
        x, y = stack.pop()
        i = y * w + x
        if outside[i] or pix[i] != WHITE:
            continue
        outside[i] = 1
        if x > 0:
            stack.append((x - 1, y))
        if x < w - 1:
            stack.append((x + 1, y))
        if y > 0:
            stack.append((x, y - 1))
        if y < h - 1:
            stack.append((x, y + 1))
    return [RED if (v == WHITE and not outside[i]) else v for i, v in enumerate(pix)]


class Converted:
    """Result of a conversion: indices in design orientation + panel planes."""

    def __init__(self, pixels, size, params):
        self.pixels = pixels          # design orientation, row-major
        self.size = size              # (w, h) design orientation
        self.params = params

    def stats(self):
        n = len(self.pixels)
        return {c: round(100 * self.pixels.count(i) / n, 1)
                for c, i in (("white", WHITE), ("black", BLACK), ("red", RED))}

    def panel_pixels(self, rotate180=False, mirror=False):
        """Indices in panel orientation (152 wide, 296 high)."""
        w, h = self.size
        px = self.pixels
        if (w, h) != (L.EPD_WIDTH, L.EPD_HEIGHT):
            # landscape design: rotate 90 degrees clockwise onto the panel
            out = [0] * (w * h)
            for y in range(h):
                for x in range(w):
                    out[x * h + (h - 1 - y)] = px[y * w + x]
            px, (w, h) = out, (h, w)
        if rotate180:
            px = px[::-1]
        if mirror:
            px = [px[y * w + (w - 1 - x)] for y in range(h) for x in range(w)]
        return px

    def planes(self, rotate180=False, mirror=False):
        px = self.panel_pixels(rotate180, mirror)
        bw = bytearray(L.PLANE_SIZE)
        red = bytearray(L.PLANE_SIZE)
        i = 0
        for y in range(L.EPD_HEIGHT):
            for xb in range(L.ROW_BYTES):
                b_bw = 0
                b_r = 0
                for bit in range(8):
                    v = px[y * L.EPD_WIDTH + xb * 8 + bit]
                    b_bw = (b_bw << 1) | (0 if v == BLACK else 1)
                    b_r = (b_r << 1) | (0 if v == RED else 1)
                bw[i] = b_bw
                red[i] = b_r
                i += 1
        return bytes(bw), bytes(red)

    def preview(self, scale=3, frame=False):
        """PNG bytes of the design as it will look on the panel."""
        w, h = self.size
        img = Image.new("RGB", (w, h))
        img.putdata([PREVIEW_RGB[v] for v in self.pixels])
        if scale > 1:
            img = img.resize((w * scale, h * scale), Image.NEAREST)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()


def convert(img, params: ImageParams) -> Converted:
    require_pillow()
    img = _adjust(_fit(img.convert("RGB"), params), params)
    pix = _quantize(img, params)
    if params.fill_enclosed and params.use_red:
        pix = _fill_enclosed(pix, img.width, img.height)
    return Converted(pix, img.size, params)


def planes_to_pixels(bw, red):
    """Decode panel planes back to indices (panel orientation)."""
    out = []
    for i in range(L.PLANE_SIZE):
        for bit in range(7, -1, -1):
            if not (red[i] >> bit) & 1:
                out.append(RED)
            elif not (bw[i] >> bit) & 1:
                out.append(BLACK)
            else:
                out.append(WHITE)
    return out


def test_pattern(orientation="portrait"):
    """Orientation / colour test card."""
    require_pillow()
    w, h = (L.EPD_HEIGHT, L.EPD_WIDTH) if orientation == "landscape" else (L.EPD_WIDTH, L.EPD_HEIGHT)
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    try:
        big = ImageFont.load_default(size=28)
        small = ImageFont.load_default(size=16)
    except TypeError:                     # Pillow < 10.1
        big = small = ImageFont.load_default()
    red, black = MATCH_RGB[RED], (0, 0, 0)
    d.rectangle([0, 0, w - 1, h - 1], outline=black, width=3)
    d.rectangle([6, 6, w - 7, h - 7], outline=red, width=2)
    cx = w // 2
    d.polygon([(cx, 14), (cx - 18, 40), (cx + 18, 40)], fill=red)
    d.text((cx, 46), "TOP", font=big, fill=black, anchor="mt")
    d.text((14, h // 2), "L", font=big, fill=black, anchor="lm")
    d.text((w - 14, h // 2), "R", font=big, fill=red, anchor="rm")
    d.text((cx, h // 2), "MonopInk", font=small, fill=black, anchor="mm")
    # colour swatches
    sw = (w - 40) // 3
    y0 = h - 60
    for i, col in enumerate(((255, 255, 255), black, red)):
        x0 = 20 + i * sw
        d.rectangle([x0, y0, x0 + sw - 6, y0 + 30], fill=col, outline=black)
    # grey ramp (shows dithering)
    for x in range(20, w - 20):
        g = int(255 * (x - 20) / (w - 40))
        d.line([(x, y0 - 30), (x, y0 - 12)], fill=(g, g, g))
    return img
