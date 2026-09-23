/* MonopInk - picture -> 3-colour e-paper pixels, in the browser.
 * Same pipeline and parameters as monopink/image.py (desktop app):
 * fit -> invert/brightness/contrast -> red mask by hue -> dither/threshold/levels
 * -> optional "enclosed white -> red" -> panel orientation. */
(function (root) {
  "use strict";
  const EPD_W = 152, EPD_H = 296;
  const WHITE = 0, BLACK = 1, RED = 2;
  const PREVIEW = [[233, 230, 219], [32, 32, 36], [190, 38, 44]];
  const MATCH = { white: [255, 255, 255], black: [0, 0, 0], red: [215, 25, 32] };

  const DEFAULTS = {
    orientation: "portrait", fit: "cover", mode: "dither", use_red: true,
    brightness: 0, contrast: 0, red_sensitivity: 50, black_level: 85, white_level: 170,
    invert: false, fill_enclosed: false, sharp: false, background: "white",
  };

  function designSize(p) {
    return p.orientation === "landscape" ? [EPD_H, EPD_W] : [EPD_W, EPD_H];
  }

  function draw(img, p) {
    const [w, h] = designSize(p);
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.imageSmoothingEnabled = !p.sharp;
    g.imageSmoothingQuality = "high";
    const iw = img.naturalWidth || img.width, ih = img.naturalHeight || img.height;
    if (p.fit === "stretch") {
      g.drawImage(img, 0, 0, w, h);
    } else if (p.fit === "cover") {
      const s = Math.max(w / iw, h / ih);
      const sw = w / s, sh = h / s;
      g.drawImage(img, (iw - sw) / 2, (ih - sh) / 2, sw, sh, 0, 0, w, h);
    } else {
      const bg = MATCH[p.background] || MATCH.white;
      g.fillStyle = `rgb(${bg[0]},${bg[1]},${bg[2]})`;
      g.fillRect(0, 0, w, h);
      const s = Math.min(w / iw, h / ih);
      const dw = Math.round(iw * s), dh = Math.round(ih * s);
      g.drawImage(img, 0, 0, iw, ih, Math.floor((w - dw) / 2), Math.floor((h - dh) / 2), dw, dh);
    }
    return g.getImageData(0, 0, w, h);
  }

  function convert(img, params) {
    const p = Object.assign({}, DEFAULTS, params || {});
    const data = draw(img, p);
    const [w, h] = [data.width, data.height];
    const n = w * h, d = data.data;
    const R = new Float32Array(n), G = new Float32Array(n), B = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      let r = d[i * 4], g = d[i * 4 + 1], b = d[i * 4 + 2];
      const a = d[i * 4 + 3] / 255;                     // transparency -> white
      r = r * a + 255 * (1 - a); g = g * a + 255 * (1 - a); b = b * a + 255 * (1 - a);
      if (p.invert) { r = 255 - r; g = 255 - g; b = 255 - b; }
      R[i] = r; G[i] = g; B[i] = b;
    }
    const clamp = (v) => (v < 0 ? 0 : v > 255 ? 255 : v);
    if (p.brightness) {
      const f = 1 + p.brightness / 100;
      for (let i = 0; i < n; i++) { R[i] = clamp(R[i] * f); G[i] = clamp(G[i] * f); B[i] = clamp(B[i] * f); }
    }
    if (p.contrast) {
      let mean = 0;
      for (let i = 0; i < n; i++) mean += (299 * R[i] + 587 * G[i] + 114 * B[i]) / 1000;
      mean = Math.round(mean / n);
      const f = 1 + p.contrast / 100;
      for (let i = 0; i < n; i++) {
        R[i] = clamp(mean + (R[i] - mean) * f); G[i] = clamp(mean + (G[i] - mean) * f); B[i] = clamp(mean + (B[i] - mean) * f);
      }
    }
    // red mask by hue
    const red = new Uint8Array(n);
    if (p.use_red) {
      const thr = 140 - Math.floor(1.6 * p.red_sensitivity);
      for (let i = 0; i < n; i++) {
        const r = Math.round(R[i]), mx = Math.max(Math.round(G[i]), Math.round(B[i]));
        red[i] = r > 90 && r - mx > thr ? 1 : 0;
      }
    }
    const lum = new Float32Array(n);
    for (let i = 0; i < n; i++) lum[i] = Math.floor((299 * R[i] + 587 * G[i] + 114 * B[i]) / 1000);

    const px = new Uint8Array(n);
    if (p.mode === "levels") {
      for (let i = 0; i < n; i++) {
        const v = lum[i];
        if (red[i]) px[i] = RED;
        else if (v < p.black_level) px[i] = BLACK;
        else if (v <= p.white_level) px[i] = p.use_red ? RED : (v < (p.black_level + p.white_level) / 2 ? BLACK : WHITE);
        else px[i] = WHITE;
      }
    } else if (p.mode === "dither") {
      const e = Float32Array.from(lum);
      for (let i = 0; i < n; i++) if (red[i]) e[i] = 255;
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          const i = y * w + x;
          const old = e[i];
          const nv = old >= 128 ? 255 : 0;
          const err = old - nv;
          px[i] = red[i] ? RED : (nv ? WHITE : BLACK);
          if (x + 1 < w) e[i + 1] += err * 7 / 16;
          if (y + 1 < h) {
            if (x > 0) e[i + w - 1] += err * 3 / 16;
            e[i + w] += err * 5 / 16;
            if (x + 1 < w) e[i + w + 1] += err * 1 / 16;
          }
        }
      }
    } else {
      for (let i = 0; i < n; i++) px[i] = red[i] ? RED : (lum[i] >= 128 ? WHITE : BLACK);
    }
    if (p.fill_enclosed && p.use_red) fillEnclosed(px, w, h);
    return { pixels: px, width: w, height: h, params: p };
  }

  function fillEnclosed(px, w, h) {
    const outside = new Uint8Array(w * h);
    const stack = [];
    for (let x = 0; x < w; x++) stack.push(x, 0, x, h - 1);
    for (let y = 0; y < h; y++) stack.push(0, y, w - 1, y);
    while (stack.length) {
      const y = stack.pop(), x = stack.pop();
      const i = y * w + x;
      if (outside[i] || px[i] !== WHITE) continue;
      outside[i] = 1;
      if (x > 0) stack.push(x - 1, y);
      if (x < w - 1) stack.push(x + 1, y);
      if (y > 0) stack.push(x, y - 1);
      if (y < h - 1) stack.push(x, y + 1);
    }
    for (let i = 0; i < w * h; i++) if (px[i] === WHITE && !outside[i]) px[i] = RED;
  }

  /* design orientation -> panel (152 x 296), same rotation as the desktop app */
  function panelPixels(conv, rotate180, mirror) {
    const { width: w, height: h } = conv;
    let px = conv.pixels, pw = w, ph = h;
    if (w !== EPD_W) {                           // landscape: 90 degrees clockwise
      const out = new Uint8Array(w * h);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) out[x * h + (h - 1 - y)] = px[y * w + x];
      px = out; pw = h; ph = w;
    }
    if (rotate180) px = Uint8Array.from(px).reverse();
    if (mirror) {
      const out = new Uint8Array(pw * ph);
      for (let y = 0; y < ph; y++) for (let x = 0; x < pw; x++) out[y * pw + x] = px[y * pw + (pw - 1 - x)];
      px = out;
    }
    return px;
  }

  function stats(conv) {
    const c = [0, 0, 0];
    for (const v of conv.pixels) c[v]++;
    const n = conv.pixels.length;
    return { white: +(100 * c[0] / n).toFixed(1), black: +(100 * c[1] / n).toFixed(1), red: +(100 * c[2] / n).toFixed(1) };
  }

  function renderPreview(conv, canvas, scale) {
    canvas.width = conv.width * scale;
    canvas.height = conv.height * scale;
    const g = canvas.getContext("2d");
    const small = g.createImageData(conv.width, conv.height);
    for (let i = 0; i < conv.pixels.length; i++) {
      const c = PREVIEW[conv.pixels[i]];
      small.data[i * 4] = c[0]; small.data[i * 4 + 1] = c[1]; small.data[i * 4 + 2] = c[2]; small.data[i * 4 + 3] = 255;
    }
    const tmp = document.createElement("canvas");
    tmp.width = conv.width; tmp.height = conv.height;
    tmp.getContext("2d").putImageData(small, 0, 0);
    g.imageSmoothingEnabled = false;
    g.drawImage(tmp, 0, 0, canvas.width, canvas.height);
  }

  root.MonopInkConvert = { DEFAULTS, convert, panelPixels, stats, renderPreview, EPD_W, EPD_H };
})(typeof self !== "undefined" ? self : this);
