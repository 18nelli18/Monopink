/* MonopInk NFC image codec - encoder + protocol helpers (browser & Node).
 * Bit-exact with monopink/codec.py and firmware/src/codec.c.
 * Context-adaptive binary range coder over the 3-colour panel pixels
 * (152 x 296, panel orientation, 0 white / 1 black / 2 red). */
(function (root) {
  "use strict";
  const W = 152, H = 296, FORMAT = 0x01;

  function encode(pixels) {
    if (pixels.length !== W * H) throw new Error("bad pixel count");
    const out = [];
    let low = 0;            // < 2^33, kept as a JS number
    let rng = 0xFFFFFFFF;
    let cache = 0, csize = 1;
    const pInk = new Uint16Array(243).fill(1024);
    const pRed = new Uint16Array(81).fill(1024);

    function shift() {
      if (low < 0xFF000000 || low >= 0x100000000) {
        const carry = low >= 0x100000000 ? 1 : 0;
        let t = cache;
        do {
          out.push((t + carry) & 0xFF);
          t = 0xFF;
        } while (--csize !== 0);
        cache = Math.floor(low / 0x1000000) & 0xFF;
      }
      csize++;
      low = (low % 0x1000000) * 256;   // (low << 8) & 0xFFFFFFFF
    }
    function bit(probs, i, b) {
      const p = probs[i];
      const bound = (rng >>> 11) * p;
      if (b === 0) {
        rng = bound;
        probs[i] = p + ((2048 - p) >> 5);
      } else {
        low += bound;
        rng -= bound;
        probs[i] = p - (p >> 5);
      }
      while (rng < 0x1000000) {
        rng = (rng * 256) >>> 0;
        shift();
      }
    }

    let prev = new Uint8Array(W);
    for (let y = 0; y < H; y++) {
      const cur = pixels.subarray ? pixels.subarray(y * W, (y + 1) * W) : pixels.slice(y * W, (y + 1) * W);
      for (let x = 0; x < W; x++) {
        const a = x >= 1 ? cur[x - 1] : 0;
        const b = x >= 2 ? cur[x - 2] : 0;
        const c = x >= 1 ? prev[x - 1] : 0;
        const d = prev[x];
        const e = x + 1 < W ? prev[x + 1] : 0;
        const r = ((a * 3 + b) * 3 + c) * 3 + d;
        const v = cur[x];
        bit(pInk, r * 3 + e, v === 0 ? 0 : 1);
        if (v !== 0) bit(pRed, r, v === 2 ? 1 : 0);
      }
      prev = cur;
    }
    for (let i = 0; i < 5; i++) shift();
    return Uint8Array.from([FORMAT, ...out]);
  }

  function crc16(data) {
    let crc = 0xFFFF;
    for (const b of data) {
      crc ^= b << 8;
      for (let i = 0; i < 8; i++) crc = (crc & 0x8000) ? ((crc << 1) ^ 0x1021) & 0xFFFF : (crc << 1) & 0xFFFF;
    }
    return crc;
  }

  /* split a stream into part payloads (15-byte header + data) */
  function splitStream(stream, chunk, imageId) {
    const count = Math.max(1, Math.ceil(stream.length / chunk));
    if (count > 255) throw new Error("too many parts");
    const scrc = crc16(stream);
    const parts = [];
    for (let i = 0; i < count; i++) {
      const data = stream.subarray(i * chunk, (i + 1) * chunk);
      const p = new Uint8Array(15 + data.length);
      const dv = new DataView(p.buffer);
      p[0] = 0x4D; p[1] = 0x4B; p[2] = 1;              // "MK", protocol 1
      dv.setUint16(3, imageId, true);
      p[5] = i; p[6] = count;
      dv.setUint16(7, stream.length, true);
      dv.setUint16(9, scrc, true);
      dv.setUint16(11, crc16(data), true);
      dv.setUint16(13, chunk, true);
      p.set(data, 15);
      parts.push(p);
    }
    return parts;
  }

  const STATES = ["ready", "receiving", "complete", "error"];
  const ERRORS = ["ok", "chip", "header", "part_crc", "order", "too_big", "stream_crc", "decode"];
  function parseStatus(bytes) {
    if (!bytes || bytes.length < 16 || bytes[0] !== 0x4D || bytes[1] !== 0x53) return null;
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    return {
      proto: bytes[2],
      firmware: (bytes[3] >> 4) + "." + (bytes[3] & 15),
      state: STATES[bytes[4]] || String(bytes[4]),
      error: ERRORS[bytes[5]] || String(bytes[5]),
      imageId: dv.getUint16(6, true),
      next: bytes[8],
      count: bytes[9],
      maxPart: dv.getUint16(10, true),
      maxStream: dv.getUint16(12, true),
    };
  }

  const api = { W, H, encode, crc16, splitStream, parseStatus, PART_TYPE: "x/mpk", STATUS_TYPE: "x/mps" };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MonopInkCodec = api;
})(typeof self !== "undefined" ? self : this);
