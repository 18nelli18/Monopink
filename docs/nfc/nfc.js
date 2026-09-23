/* MonopInk NFC - phone page: pick a picture, convert it, send it to the label
 * with Web NFC (Chrome on Android).  One NDEF message per tap: the page
 * first reads the label's status record ("x/mps"), then writes the part the
 * label asks for ("x/mpk").  The label processes it when the phone leaves. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const C = window.MonopInkConvert, K = window.MonopInkCodec;
  const DEFAULT_CHUNK = 832;

  const I18N = {
    en: {
      tagline: "Send a picture to your label over NFC",
      "nonfc.title": "Web NFC is not available here",
      "nonfc.text": "Open this page in <b>Chrome on Android</b>, over <b>https://</b>, with NFC turned on in the phone settings. (iPhone and desktop browsers do not support Web NFC.)",
      "pick.title": "Picture", "pick.choose": "Choose a picture", "pick.sub": "photo, logo, drawing…", "pick.testcard": "Use the orientation test card", "pick.testcard.name": "orientation test card",
      "adj.title": "Adjust", "adj.orientation": "Orientation", "adj.portrait": "Portrait", "adj.landscape": "Landscape",
      "adj.fit": "Framing", "adj.cover": "Fill", "adj.contain": "Fit", "adj.stretch": "Stretch",
      "adj.mode": "Rendering", "adj.threshold": "Threshold", "adj.threshold.sub": "fewest taps", "adj.levels": "Levels", "adj.levels.sub": "greys → red",
      "adj.dither": "Dithering", "adj.dither.sub": "photos, more taps", "adj.more": "More settings",
      "adj.red": "Use red", "adj.redsens": "Red sensitivity", "adj.brightness": "Brightness", "adj.contrast": "Contrast",
      "adj.black": "Black below", "adj.white": "White above", "adj.invert": "Invert", "adj.sharp": "Sharp resize (logos, pixel art)",
      "adj.fill": "Enclosed white areas → red",
      "meter": "{size} bytes → <b>{taps} tap{s}</b>", "meter.big": "Too complex ({size} bytes, max {max}): use Threshold or simplify the picture",
      "send.title": "Send", "send.lead": "Tap the phone on the label (its centre), keep it still until it vibrates, move it away, wait a second, repeat for each part.",
      "send.go": "Send to the label", "send.stop": "Stop",
      "s.hold": "Hold the phone against the label", "s.hold2": "Part {i} of {n}",
      "s.written": "Part {i}/{n} sent — move the phone away", "s.written2": "Wait one second, then tap again for part {j}.",
      "s.last": "Last part sent — move the phone away", "s.last2": "The label rebuilds the picture and refreshes its screen (about 20 s). Tap again afterwards to confirm.",
      "s.done": "Picture displayed ✓", "s.done2": "The label confirmed the new picture.",
      "s.retry": "Keep the phone still and tap again", "s.retry2": "The write was interrupted ({err}).",
      "s.err.part_crc": "The previous part arrived damaged: it has just been sent again.", "s.err.order": "The label asked for another part: part {j} has just been sent.",
      "s.err.too_big": "The label cannot store this picture: choose Threshold or a simpler picture.",
      "s.err.stream_crc": "The label received a damaged picture: sending it again from the start.", "s.err.decode": "The label could not decode the picture.",
      "s.err.chip": "The label could not access its NFC chip.", "s.err.header": "The label rejected the data.",
      "s.pending": "The label has not taken the last part yet", "s.pending2": "Move the phone away, wait 2 seconds, then tap again. No progress? Check the batteries.",
      "s.notours": "This tag is not a MonopInk label (no status record). Install the MonopInk firmware 1.3+ first.",
      "status.read": "Read the label's status", "status.hold": "Tap the label…",
      "st.firmware": "Firmware", "st.state": "State", "st.image": "Transfer", "st.error": "Last error", "st.capacity": "Capacity", "st.capacity.val": "{p} bytes per tap · {s} bytes max",
      "st.ready": "ready", "st.receiving": "receiving", "st.complete": "picture complete", "st.error.state": "error",
      "foot.tips": "Tips: NFC must be on (Settings → Connected devices). The label's antenna is small: try the middle of the label, then slide slowly. The picture stays on the label without batteries; with batteries, the label wakes up when a phone comes close.",
      "foot.calib": "Display calibration:", "foot.rot": "rotate 180°", "foot.mirror": "mirror",
      "err.image": "Cannot open this picture.", "err.perm": "NFC permission refused.",
    },
    fr: {
      tagline: "Envoie une image sur ton étiquette en NFC",
      "nonfc.title": "Web NFC n'est pas disponible ici",
      "nonfc.text": "Ouvre cette page dans <b>Chrome sur Android</b>, en <b>https://</b>, avec le NFC activé dans les réglages du téléphone. (L'iPhone et les navigateurs d'ordinateur ne gèrent pas Web NFC.)",
      "pick.title": "Image", "pick.choose": "Choisir une image", "pick.sub": "photo, logo, dessin…", "pick.testcard": "Utiliser la mire d'orientation", "pick.testcard.name": "mire d'orientation",
      "adj.title": "Réglages", "adj.orientation": "Orientation", "adj.portrait": "Portrait", "adj.landscape": "Paysage",
      "adj.fit": "Cadrage", "adj.cover": "Remplir", "adj.contain": "Ajuster", "adj.stretch": "Étirer",
      "adj.mode": "Rendu", "adj.threshold": "Seuil", "adj.threshold.sub": "le moins de tapes", "adj.levels": "Niveaux", "adj.levels.sub": "gris → rouge",
      "adj.dither": "Tramage", "adj.dither.sub": "photos, plus de tapes", "adj.more": "Plus de réglages",
      "adj.red": "Utiliser le rouge", "adj.redsens": "Sensibilité au rouge", "adj.brightness": "Luminosité", "adj.contrast": "Contraste",
      "adj.black": "Noir en dessous de", "adj.white": "Blanc au-dessus de", "adj.invert": "Inverser", "adj.sharp": "Redimensionnement net (logos, pixel art)",
      "adj.fill": "Zones blanches enclavées → rouge",
      "meter": "{size} octets → <b>{taps} tape{s}</b>", "meter.big": "Trop complexe ({size} octets, max {max}) : utilise Seuil ou simplifie l'image",
      "send.title": "Envoyer", "send.lead": "Pose le téléphone sur l'étiquette (au centre), garde-le immobile jusqu'à la vibration, éloigne-le, attends une seconde, recommence pour chaque morceau.",
      "send.go": "Envoyer sur l'étiquette", "send.stop": "Arrêter",
      "s.hold": "Pose le téléphone sur l'étiquette", "s.hold2": "Morceau {i} sur {n}",
      "s.written": "Morceau {i}/{n} envoyé — éloigne le téléphone", "s.written2": "Attends une seconde, puis tape de nouveau pour le morceau {j}.",
      "s.last": "Dernier morceau envoyé — éloigne le téléphone", "s.last2": "L'étiquette reconstruit l'image et rafraîchit son écran (environ 20 s). Tape de nouveau ensuite pour confirmer.",
      "s.done": "Image affichée ✓", "s.done2": "L'étiquette a confirmé la nouvelle image.",
      "s.retry": "Garde le téléphone immobile et tape de nouveau", "s.retry2": "L'écriture a été interrompue ({err}).",
      "s.err.part_crc": "Le morceau précédent est arrivé abîmé : il vient d'être renvoyé.", "s.err.order": "L'étiquette a demandé un autre morceau : le morceau {j} vient d'être envoyé.",
      "s.err.too_big": "L'étiquette ne peut pas stocker cette image : choisis Seuil ou une image plus simple.",
      "s.err.stream_crc": "L'étiquette a reçu une image abîmée : on la renvoie depuis le début.", "s.err.decode": "L'étiquette n'a pas pu décoder l'image.",
      "s.err.chip": "L'étiquette n'a pas pu accéder à sa puce NFC.", "s.err.header": "L'étiquette a refusé les données.",
      "s.pending": "L'étiquette n'a pas encore pris le dernier morceau", "s.pending2": "Éloigne le téléphone, attends 2 secondes, puis tape de nouveau. Rien ne bouge ? Vérifie les piles.",
      "s.notours": "Ce tag n'est pas une étiquette MonopInk (pas d'enregistrement d'état). Installe d'abord le firmware MonopInk 1.3+.",
      "status.read": "Lire l'état de l'étiquette", "status.hold": "Pose le téléphone sur l'étiquette…",
      "st.firmware": "Firmware", "st.state": "État", "st.image": "Transfert", "st.error": "Dernière erreur", "st.capacity": "Capacité", "st.capacity.val": "{p} octets par tape · {s} octets max",
      "st.ready": "prête", "st.receiving": "réception en cours", "st.complete": "image complète", "st.error.state": "erreur",
      "foot.tips": "Astuces : le NFC doit être activé (Réglages → Appareils connectés). L'antenne de l'étiquette est petite : essaie le milieu de l'étiquette puis glisse doucement. L'image reste sans piles ; avec des piles, l'étiquette se réveille quand un téléphone approche.",
      "foot.calib": "Calibration de l'affichage :", "foot.rot": "rotation 180°", "foot.mirror": "miroir",
      "err.image": "Impossible d'ouvrir cette image.", "err.perm": "Autorisation NFC refusée.",
    },
  };

  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } },
  };
  const S = {
    lang: store.get("mpn.lang", (navigator.language || "en").toLowerCase().startsWith("fr") ? "fr" : "en"),
    img: null, params: Object.assign({}, C.DEFAULTS, { mode: "threshold" }, store.get("mpn.params", {})),
    conv: null, stream: null, parts: null, imageId: 0, chunk: DEFAULT_CHUNK, maxStream: 6144,
    reader: null, abort: null, busy: false, phase: "idle", lastWrite: 0,
  };

  function T(k, v) {
    let s = (I18N[S.lang] || I18N.en)[k] ?? I18N.en[k] ?? k;
    if (v) s = s.replace(/\{(\w+)\}/g, (m, x) => (v[x] ?? m));
    return s;
  }
  function applyI18n() {
    document.documentElement.lang = S.lang;
    $$("[data-i18n]").forEach((el) => { el.textContent = T(el.dataset.i18n); });
    $$("[data-i18n-html]").forEach((el) => { el.innerHTML = T(el.dataset.i18nHtml); });
    $$(".lang button").forEach((b) => b.classList.toggle("on", b.dataset.lang === S.lang));
    if (S.img) $("#fileName").textContent = S.name || T("pick.testcard.name");
    updateMeter();
  }
  let toastTimer;
  function toast(msg, bad) {
    const t = $("#toast");
    t.textContent = msg; t.classList.toggle("error", !!bad); t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 4000);
  }

  // ------------------------------------------------------------ picture
  function loadFile(file) {
    if (!file) return;
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { S.name = file.name; setImage(img, url); };
    img.onerror = () => toast(T("err.image"), true);
    img.src = url;
  }
  function setImage(img, url) {
    S.img = img;
    const th = $("#thumb"); th.src = url; th.hidden = false;
    $("#fileName").textContent = S.name;
    if ((img.naturalWidth || img.width) > (img.naturalHeight || img.height) * 1.15) S.params.orientation = "landscape";
    else S.params.orientation = "portrait";
    $("#adjustCard").hidden = false;
    $("#sendCard").hidden = false;
    controls();
    reconvert();
  }
  function testCard() {
    const land = S.params.orientation === "landscape";
    const w = land ? 296 : 152, h = land ? 152 : 296;
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const g = c.getContext("2d");
    g.fillStyle = "#fff"; g.fillRect(0, 0, w, h);
    g.strokeStyle = "#000"; g.lineWidth = 3; g.strokeRect(1.5, 1.5, w - 3, h - 3);
    g.strokeStyle = "#d7191f"; g.lineWidth = 2; g.strokeRect(7, 7, w - 14, h - 14);
    g.fillStyle = "#d7191f"; g.beginPath(); g.moveTo(w / 2, 14); g.lineTo(w / 2 - 18, 40); g.lineTo(w / 2 + 18, 40); g.fill();
    g.fillStyle = "#000"; g.font = "bold 28px sans-serif"; g.textAlign = "center"; g.textBaseline = "top"; g.fillText("TOP", w / 2, 46);
    g.textBaseline = "middle"; g.textAlign = "left"; g.fillText("L", 14, h / 2);
    g.fillStyle = "#d7191f"; g.textAlign = "right"; g.fillText("R", w - 14, h / 2);
    g.fillStyle = "#000"; g.font = "16px sans-serif"; g.textAlign = "center"; g.fillText("MonopInk", w / 2, h / 2);
    const sw = (w - 40) / 3, y0 = h - 60;
    ["#fff", "#000", "#d7191f"].forEach((col, i) => { g.fillStyle = col; g.fillRect(20 + i * sw, y0, sw - 6, 30); g.strokeStyle = "#000"; g.lineWidth = 1; g.strokeRect(20 + i * sw + .5, y0 + .5, sw - 7, 29); });
    const img = new Image();
    img.onload = () => {
      S.name = null;
      S.params = Object.assign({}, C.DEFAULTS, { mode: "threshold", fit: "stretch", orientation: land ? "landscape" : "portrait" });
      S.img = img; $("#thumb").src = img.src; $("#thumb").hidden = false; $("#fileName").textContent = T("pick.testcard.name");
      $("#adjustCard").hidden = false; $("#sendCard").hidden = false;
      controls(); reconvert();
    };
    img.src = c.toDataURL();
  }

  let convTimer;
  function reconvert(delay) {
    clearTimeout(convTimer);
    convTimer = setTimeout(() => {
      if (!S.img) return;
      S.conv = C.convert(S.img, S.params);
      $("#mock").className = "mock " + S.params.orientation;
      C.renderPreview(S.conv, $("#preview"), 2);
      encode();
      store.set("mpn.params", S.params);
    }, delay || 0);
  }
  function encode() {
    const px = C.panelPixels(S.conv, $("#calRot").checked, $("#calMirror").checked);
    S.stream = K.encode(px);
    S.imageId = (Math.random() * 65536) | 0;
    S.parts = S.stream.length <= S.maxStream ? K.splitStream(S.stream, S.chunk, S.imageId) : null;
    updateMeter();
  }
  function updateMeter() {
    const m = $("#meter");
    if (!S.stream) { m.innerHTML = ""; return; }
    if (!S.parts) {
      m.innerHTML = `<span class="bad">${T("meter.big", { size: S.stream.length, max: S.maxStream })}</span>`;
      $("#send").disabled = true;
      return;
    }
    const n = S.parts.length;
    m.innerHTML = T("meter", { size: S.stream.length, taps: n, s: n > 1 ? "s" : "" });
    $("#send").disabled = false;
  }
  function controls() {
    const p = S.params;
    $$(".seg[data-param]").forEach((seg) => $$(`.seg[data-param="${seg.dataset.param}"] button`).forEach((b) => b.classList.toggle("on", String(p[seg.dataset.param]) === b.dataset.value)));
    $$("input[type=checkbox][data-param]").forEach((c) => { c.checked = !!p[c.dataset.param]; });
    $$("input[type=range][data-param]").forEach((r) => { r.value = p[r.dataset.param]; r.parentElement.querySelector("output").textContent = r.value; });
    $$("[data-show]").forEach((el) => {
      const k = el.dataset.show;
      el.hidden = k === "use_red" ? !p.use_red : k === "levels" ? p.mode !== "levels" : false;
    });
  }

  // ------------------------------------------------------------ NFC
  function hasPart(message) {
    return message.records.some((r) => r.recordType === "mime" && r.mediaType === K.PART_TYPE);
  }
  function statusOf(message) {
    for (const r of message.records) {
      if (r.recordType === "mime" && r.mediaType === K.STATUS_TYPE && r.data) {
        return K.parseStatus(new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength));
      }
    }
    return null;
  }
  function say(main, sub, cls) {
    const s = $("#say");
    s.textContent = main; s.className = "say" + (cls ? " " + cls : "");
    $("#say2").textContent = sub || "";
  }
  function dots(next, total) {
    $("#dots").innerHTML = Array.from({ length: total }, (_, i) => `<span class="${i < next ? "done" : i === next ? "now" : ""}"></span>`).join("");
  }
  function stopSession() {
    if (S.abort) S.abort.abort();
    S.abort = null; S.reader = null; S.phase = "idle"; S.busy = false;
    $("#session").hidden = true; $("#send").hidden = false;
  }
  async function startScan(onReading) {
    if (!("NDEFReader" in window)) { $("#noNfc").hidden = false; $("#noNfc").scrollIntoView({ behavior: "smooth" }); return false; }
    S.abort = new AbortController();
    S.reader = new NDEFReader();
    try {
      await S.reader.scan({ signal: S.abort.signal });
    } catch (e) {
      toast(e.name === "NotAllowedError" ? T("err.perm") : String(e.message || e), true);
      S.abort = null;
      return false;
    }
    S.reader.onreading = onReading;
    S.reader.onreadingerror = () => { if (S.phase === "send") say(T("s.retry"), T("s.retry2", { err: "read" }), "bad"); };
    return true;
  }

  async function send() {
    if (!S.parts) return;
    S.phase = "send";
    $("#session").hidden = false; $("#send").hidden = true;
    dots(0, S.parts.length);
    say(T("s.hold"), T("s.hold2", { i: 1, n: S.parts.length }));
    const ok = await startScan(onSendReading);
    if (!ok) stopSession();
  }

  async function onSendReading(ev) {
    if (S.busy || S.phase !== "send") return;
    S.busy = true;
    const n = S.parts.length;
    try {
      const st = statusOf(ev.message);
      if (!st) {
        // our part is still on the tag: the label only reads it once the phone has left
        if (hasPart(ev.message)) {
          if (Date.now() - S.lastWrite > 2500) say(T("s.pending"), T("s.pending2"));   // else: re-read of our own write
        }
        else say(T("s.notours"), "", "bad");
        return;
      }
      if (st.maxStream && st.maxStream !== S.maxStream) { S.maxStream = st.maxStream; updateMeter(); }
      if (S.stream.length > S.maxStream || st.error === "too_big") {
        say(T("s.err.too_big"), T("meter.big", { size: S.stream.length, max: S.maxStream }).replace(/<[^>]+>/g, ""), "bad");
        return;
      }
      if (st.maxPart && st.maxPart < S.chunk) {          // older/smaller label: re-split
        S.chunk = st.maxPart;
        S.parts = K.splitStream(S.stream, S.chunk, S.imageId);
      }
      let next = 0;
      const ours = st.imageId === S.imageId && st.count === S.parts.length;
      if (ours && st.state === "complete") {
        dots(n, n); say(T("s.done"), T("s.done2"), "ok");
        if (navigator.vibrate) navigator.vibrate([60, 60, 60]);
        if (S.abort) S.abort.abort();
        S.phase = "idle";
        setTimeout(() => { $("#send").hidden = false; }, 1500);
        return;
      }
      if (ours && st.state === "receiving") next = st.next;
      let note = "";
      if (ours && st.error !== "ok") note = T("s.err." + st.error, { j: next + 1 });
      if (next >= n) next = 0;
      dots(next, n);
      await S.reader.write({ records: [{ recordType: "mime", mediaType: K.PART_TYPE, data: S.parts[next] }] },
                           { overwrite: true, signal: S.abort.signal });
      S.lastWrite = Date.now();
      if (navigator.vibrate) navigator.vibrate(80);
      dots(next + 1, n);
      if (next + 1 >= n) say(T("s.last"), T("s.last2"), "ok");
      else say(T("s.written", { i: next + 1, n }), (note ? note + " " : "") + T("s.written2", { j: next + 2 }));
    } catch (e) {
      if (e.name !== "AbortError") say(T("s.retry"), T("s.retry2", { err: e.name || e.message }), "bad");
    } finally {
      S.busy = false;
    }
  }

  async function readStatus() {
    const box = $("#statusBox");
    box.hidden = false;
    box.innerHTML = `<span></span><span>${T("status.hold")}</span>`;
    const ok = await startScan((ev) => {
      const st = statusOf(ev.message);
      if (!st) box.innerHTML = `<span></span><span>${T(hasPart(ev.message) ? "s.pending" : "s.notours")}</span>`;
      else {
        const stateTxt = { ready: T("st.ready"), receiving: T("st.receiving"), complete: T("st.complete"), error: T("st.error.state") }[st.state] || st.state;
        box.innerHTML = `<span>${T("st.firmware")}</span><span>${st.firmware}</span>
          <span>${T("st.state")}</span><span>${stateTxt}</span>
          <span>${T("st.image")}</span><span>#${st.imageId.toString(16)} · ${st.next}/${st.count}</span>
          <span>${T("st.error")}</span><span>${st.error === "ok" ? "—" : st.error}</span>
          <span>${T("st.capacity")}</span><span>${T("st.capacity.val", { p: st.maxPart, s: st.maxStream })}</span>`;
      }
      if (S.abort) S.abort.abort();
      S.abort = null;
    });
    if (!ok) box.hidden = true;
  }

  // ------------------------------------------------------------ events
  $("#file").addEventListener("change", (e) => { loadFile(e.target.files[0]); e.target.value = ""; });
  $("#testCard").addEventListener("click", testCard);
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".seg[data-param] button");
    if (b) { S.params[b.parentElement.dataset.param] = b.dataset.value; controls(); reconvert(); return; }
    const l = e.target.closest(".lang button");
    if (l) { S.lang = l.dataset.lang; store.set("mpn.lang", S.lang); applyI18n(); }
  });
  $$("input[data-param]").forEach((inp) => inp.addEventListener(inp.type === "range" ? "input" : "change", () => {
    S.params[inp.dataset.param] = inp.type === "checkbox" ? inp.checked : +inp.value;
    controls(); reconvert(inp.type === "range" ? 120 : 0);
  }));
  // the desktop app's link carries its language and display calibration
  const qs = new URLSearchParams(location.search);
  if (I18N[qs.get("lang")]) { S.lang = qs.get("lang"); store.set("mpn.lang", S.lang); }
  if (qs.has("rot")) store.set("mpn.calRot", qs.get("rot") === "1");
  if (qs.has("mirror")) store.set("mpn.calMirror", qs.get("mirror") === "1");
  ["calRot", "calMirror"].forEach((id) => {
    $("#" + id).checked = store.get("mpn." + id, false);
    $("#" + id).addEventListener("change", (e) => { store.set("mpn." + id, e.target.checked); if (S.conv) encode(); });
  });
  $("#send").addEventListener("click", send);
  $("#stop").addEventListener("click", stopSession);
  $("#readStatus").addEventListener("click", readStatus);

  if (!("NDEFReader" in window)) $("#noNfc").hidden = false;
  applyI18n();
})();
