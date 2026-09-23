"""MonopInk NFC image codec ("MPK", version 1).

A context-adaptive binary range coder (LZMA-style bit coder) over the
3-colour pixels of the panel (152 x 296, panel orientation, raster order).
Per pixel: bit "ink" (non-white), then if ink: bit "red".
Context = colours of 5 causal neighbours (3 values each -> 243 contexts):
    left, left-left, up-left, up, up-right      (outside = white)
The "red" decision uses the first 4 of them only (81 contexts), which keeps
the decoder's tables small enough for the CC2510 RAM.

Stream = 1 format byte (0x01) + range coder bytes.
Must stay bit-exact with firmware/src/codec.c and web/static/nfc/codec.js.
"""
from . import layout as L
from .image import WHITE, BLACK, RED

FORMAT = 0x01
W, H = L.EPD_WIDTH, L.EPD_HEIGHT
PROB_INIT = 1024
N_INK = 243
N_RED = 81


def _ctx(prev, cur, x):
    """(ink context, red context) for pixel x of the current row."""
    a = cur[x - 1] if x >= 1 else 0
    b = cur[x - 2] if x >= 2 else 0
    c = prev[x - 1] if x >= 1 else 0
    d = prev[x]
    e = prev[x + 1] if x + 1 < W else 0
    r = ((a * 3 + b) * 3 + c) * 3 + d
    return r * 3 + e, r


class _Enc:
    def __init__(self):
        self.low = 0
        self.rng = 0xFFFFFFFF
        self.cache = 0
        self.csize = 1
        self.out = bytearray()

    def _shift(self):
        if self.low < 0xFF000000 or self.low >= (1 << 32):
            carry = self.low >> 32
            t = self.cache
            while True:
                self.out.append((t + carry) & 0xFF)
                t = 0xFF
                self.csize -= 1
                if self.csize == 0:
                    break
            self.cache = (self.low >> 24) & 0xFF
        self.csize += 1
        self.low = (self.low << 8) & 0xFFFFFFFF

    def bit(self, probs, i, b):
        p = probs[i]
        bound = (self.rng >> 11) * p
        if b == 0:
            self.rng = bound
            probs[i] = p + ((2048 - p) >> 5)
        else:
            self.low += bound
            self.rng -= bound
            probs[i] = p - (p >> 5)
        while self.rng < (1 << 24):
            self.rng = (self.rng << 8) & 0xFFFFFFFF
            self._shift()

    def finish(self):
        for _ in range(5):
            self._shift()
        return bytes(self.out)


class _Dec:
    def __init__(self, data, pos):
        self.data = data
        self.pos = pos
        self.rng = 0xFFFFFFFF
        self.code = 0
        for _ in range(5):
            self.code = ((self.code << 8) | self._next()) & 0xFFFFFFFF

    def _next(self):
        b = self.data[self.pos] if self.pos < len(self.data) else 0
        self.pos += 1
        return b

    def bit(self, probs, i):
        p = probs[i]
        bound = (self.rng >> 11) * p
        if self.code < bound:
            self.rng = bound
            probs[i] = p + ((2048 - p) >> 5)
            b = 0
        else:
            self.code -= bound
            self.rng -= bound
            probs[i] = p - (p >> 5)
            b = 1
        while self.rng < (1 << 24):
            self.rng = (self.rng << 8) & 0xFFFFFFFF
            self.code = ((self.code << 8) | self._next()) & 0xFFFFFFFF
        return b


def encode(pixels):
    """pixels: panel orientation, row-major, values WHITE/BLACK/RED."""
    assert len(pixels) == W * H
    e = _Enc()
    p_ink = [PROB_INIT] * N_INK
    p_red = [PROB_INIT] * N_RED
    prev = [0] * W
    for y in range(H):
        cur = pixels[y * W:(y + 1) * W]
        for x in range(W):
            ci, cr = _ctx(prev, cur, x)
            v = cur[x]
            e.bit(p_ink, ci, 0 if v == WHITE else 1)
            if v != WHITE:
                e.bit(p_red, cr, 1 if v == RED else 0)
        prev = cur
    return bytes([FORMAT]) + e.finish()


def decode(stream):
    if not stream or stream[0] != FORMAT:
        raise ValueError("unknown stream format")
    d = _Dec(stream, 1)
    p_ink = [PROB_INIT] * N_INK
    p_red = [PROB_INIT] * N_RED
    prev = [0] * W
    out = []
    for y in range(H):
        cur = [0] * W
        for x in range(W):
            ci, cr = _ctx(prev, cur, x)
            if d.bit(p_ink, ci):
                cur[x] = RED if d.bit(p_red, cr) else BLACK
        out += cur
        prev = cur
    return out


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc
