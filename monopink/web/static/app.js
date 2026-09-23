/* MonopInk web UI - no framework, no build step, works offline. */
(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  const DEFAULT_PARAMS = {
    orientation: "portrait", fit: "cover", mode: "dither", use_red: true,
    brightness: 0, contrast: 0, red_sensitivity: 50, black_level: 85, white_level: 170,
    invert: false, fill_enclosed: false, sharp: false, background: "white",
  };
  const DEFAULT_PINS = { rst: 3, dc: 4, dd_i: 6, dd_o: 7 };
  const ROLES = {
    rst: { key: "wi.role.rst", color: "#d97706" },
    dc: { key: "wi.role.dc", color: "#2563eb" },
    dd_i: { key: "wi.role.ddi", color: "#7c3aed" },
    dd_o: { key: "wi.role.ddo", color: "#db2777" },
  };
  const PICO_PINS = {
    1: "GP0", 2: "GP1", 3: "GND", 4: "GP2", 5: "GP3", 6: "GP4", 7: "GP5", 8: "GND", 9: "GP6", 10: "GP7",
    11: "GP8", 12: "GP9", 13: "GND", 14: "GP10", 15: "GP11", 16: "GP12", 17: "GP13", 18: "GND", 19: "GP14", 20: "GP15",
    21: "GP16", 22: "GP17", 23: "GND", 24: "GP18", 25: "GP19", 26: "GP20", 27: "GP21", 28: "GND", 29: "GP22", 30: "RUN",
    31: "GP26", 32: "GP27", 33: "AGND", 34: "GP28", 35: "ADC_VREF", 36: "3V3(OUT)", 37: "3V3_EN", 38: "GND", 39: "VSYS", 40: "VBUS",
  };
  const GP_TO_PIN = {};
  for (const [pin, name] of Object.entries(PICO_PINS)) {
    if (name.startsWith("GP")) GP_TO_PIN[+name.slice(2)] = +pin;
  }
  const RUN_STATES = [16, 48, 64, 80, 96, 112, 128];
  const VIEWS = ["overview", "wiring", "pico", "label", "picture", "nfc", "tools"];

  const S = {
    lang: "en",
    state: null,
    view: "overview",
    pins: { ...DEFAULT_PINS },
    singleDD: false,
    armed: "rst",
    pico: null,
    label: null,
    params: { ...DEFAULT_PARAMS },
    busy: false,
    job: null,
    nfc: null,
    previewSeq: 0,
  };

  // ================================================================ i18n
  function T(key, vars) {
    const dict = window.I18N[S.lang] || window.I18N.en;
    let s = dict[key] ?? window.I18N.en[key] ?? key;
    if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] ?? m));
    return s;
  }

  function applyI18n() {
    document.documentElement.lang = S.lang;
    $$("[data-i18n]").forEach((el) => { el.textContent = T(el.dataset.i18n); });
    $$("[data-i18n-html]").forEach((el) => { el.innerHTML = T(el.dataset.i18nHtml); });
    $$("[data-i18n-title]").forEach((el) => { el.title = T(el.dataset.i18nTitle); });
    $$(".lang-switch button").forEach((b) => b.classList.toggle("on", b.dataset.lang === S.lang));
    renderAll();
  }

  function setLang(lang) {
    S.lang = lang;
    store.set("mp.lang", lang);
    api("/api/config", { lang }).catch(() => {});
    applyI18n();
  }

  // ================================================================ api
  async function api(path, body) {
    const opts = body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-MonopInk": "1" },
      body: JSON.stringify(body),
    };
    let r;
    try {
      r = await fetch(path, opts);
    } catch (e) {
      toast(T("err.network"), true);
      throw e;
    }
    const data = await r.json().catch(() => ({ ok: false, error: r.statusText }));
    if (!r.ok && data.ok === undefined) data.ok = false;
    return data;
  }

  let toastTimer = null;
  function toast(msg, isError) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.toggle("error", !!isError);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 3500);
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } },
  };

  // ================================================================ navigation
  function show(view) {
    if (!VIEWS.includes(view)) view = "overview";
    S.view = view;
    VIEWS.forEach((v) => { $("#view-" + v).hidden = v !== view; });
    $$("#steps button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    if (location.hash !== "#" + view) history.replaceState(null, "", "#" + view);
    if (view === "wiring") store.set("mp.wiringSeen", true);
    if (view === "pico") refreshPico();
    if (view === "picture") { refreshCurrent(); schedulePreview(0); }
    if (view === "tools") refreshPorts();
    renderSteps();
    window.scrollTo({ top: 0 });
  }

  function renderSteps() {
    const btn = (v) => $(`#steps button[data-view="${v}"]`);
    const set = (v, cls) => { const b = btn(v); b.classList.remove("done", "attn"); if (cls) b.classList.add(cls); };
    set("overview", store.get("mp.wiringSeen", false) ? "done" : null);
    set("wiring", store.get("mp.wiringSeen", false) ? "done" : null);
    const p = S.pico;
    set("pico", p && (p.state === "monopink" ? (p.pins_match ? "done" : "attn") : p.state === "cclib" ? "attn" : null));
    const l = S.label;
    set("label", l && (l.locked ? "attn" : (l.firmware && l.firmware.installed ? "done" : null)));
    set("picture", S.state && S.state.has_label_image ? "done" : null);
    set("tools", null);
  }

  // ================================================================ header chips
  function renderChips() {
    const cp = $("#chipPico"), cl = $("#chipLabel");
    const setChip = (el, val, cls) => {
      el.classList.remove("ok", "warn", "bad", "busy");
      if (cls) el.classList.add(cls);
      el.querySelector(".chip-val").textContent = val;
    };
    const p = S.pico;
    if (S.busy) setChip(cp, T("chip.busy"), "busy");
    else if (!p) setChip(cp, T("chip.unknown"));
    else if (p.state === "monopink") setChip(cp, T("chip.monopink", { v: p.version }), p.pins_match ? "ok" : "warn");
    else if (p.state === "cclib") setChip(cp, T("chip.cclib"), "warn");
    else if (p.state === "bootsel") setChip(cp, T("chip.bootsel"), "warn");
    else if (p.state === "busy") setChip(cp, T("chip.busy"), "busy");
    else setChip(cp, T("chip.absent"), "bad");

    const l = S.label;
    if (!l) setChip(cl, T("chip.unknown"));
    else if (l.error) setChip(cl, T("chip.error"), "bad");
    else if (l.locked) setChip(cl, T("chip.locked"), "warn");
    else if (l.firmware && l.firmware.installed) setChip(cl, T("chip.ready", { v: l.firmware.version }), "ok");
    else setChip(cl, T("chip.nofw"), "warn");
  }

  // ================================================================ overview
  function renderEnv() {
    const st = S.state;
    if (!st) return;
    const items = [];
    const deps = st.deps || {};
    items.push([deps.pyserial, "pyserial"], [deps.pillow, "Pillow"]);
    for (const [f, ok] of Object.entries(st.files || {})) items.push([ok, f]);
    $("#envCheck").innerHTML = items.map(([ok, name]) =>
      `<span class="${ok ? "good" : "bad"}">${esc(name)}</span>`).join("");
  }

  // ================================================================ wiring
  function pinsForRole() {
    // role -> gpio, respecting single-wire DD
    const p = { ...S.pins };
    if (S.singleDD) p.dd_o = p.dd_i;
    return p;
  }

  function roleOfGpio(gp) {
    const p = pinsForRole();
    const roles = [];
    for (const r of Object.keys(ROLES)) if (p[r] === gp) roles.push(r);
    if (S.singleDD) return roles.filter((r) => r !== "dd_o");
    return roles;
  }

  function roleLabel(r) {
    if (S.singleDD && r === "dd_i") return T("wi.role.dd");
    return T(ROLES[r].key);
  }

  function renderRoles() {
    const roles = S.singleDD ? ["rst", "dc", "dd_i"] : ["rst", "dc", "dd_i", "dd_o"];
    if (!roles.includes(S.armed)) S.armed = "rst";
    $("#roles").innerHTML = roles.map((r) =>
      `<button class="role ${S.armed === r ? "armed" : ""}" data-role="${r}" style="--role:${ROLES[r].color}">${esc(roleLabel(r))}</button>`).join("");
  }

  function renderPicoSvg() {
    const W = 400, top = 58, step = 24.5;
    const bx = 148, bw = 104;
    let s = `<svg viewBox="0 0 ${W} ${top + step * 20 + 26}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Raspberry Pi Pico pinout">`;
    s += `<rect class="usb" x="${bx + bw / 2 - 16}" y="14" width="32" height="22" rx="3"/>`;
    s += `<rect class="board" x="${bx}" y="28" width="${bw}" height="${step * 20 + 30}" rx="8"/>`;
    s += `<rect class="chip" x="${bx + bw / 2 - 20}" y="${top + step * 8}" width="40" height="40" rx="3"/>`;
    s += `<rect class="btnsel" x="${bx + bw / 2 - 8}" y="${top + step * 2.2}" width="16" height="12" rx="2"/>`;
    s += `<text class="num" x="${bx + bw / 2}" y="${top + step * 2.2 + 22}" text-anchor="middle">BOOTSEL</text>`;
    const p = pinsForRole();
    const fixedTag = { 36: ["BAT +", "#c3272e"], 38: ["BAT −", "#3c3c3c"] };
    for (let pin = 1; pin <= 40; pin++) {
      const left = pin <= 20;
      const idx = left ? pin - 1 : 40 - pin;
      const y = top + idx * step;
      const x = left ? bx + 12 : bx + bw - 12;
      const name = PICO_PINS[pin];
      const isGp = name.startsWith("GP");
      const gp = isGp ? +name.slice(2) : null;
      const isGnd = name.includes("GND");
      const isPwr = pin === 36;
      const cls = isGp ? "pad gpio" : isGnd ? "pad gnd" : isPwr ? "pad pwr" : "pad";
      s += `<circle class="${cls}" cx="${x}" cy="${y}" r="7" ${isGp ? `data-gp="${gp}"` : ""}><title>${name} (pin ${pin})</title></circle>`;
      s += `<text class="num" x="${left ? x + 12 : x - 12}" y="${y + 3}" text-anchor="${left ? "start" : "end"}">${pin}</text>`;
      const lx = left ? bx - 6 : bx + bw + 6;
      const roles = isGp ? roleOfGpio(gp) : [];
      const dim = !isGp && !isGnd && !isPwr;
      s += `<text class="lbl ${dim ? "dim" : ""}" x="${lx}" y="${y + 3}" text-anchor="${left ? "end" : "start"}">${name}</text>`;
      const tags = roles.map((r) => [roleLabel(r), ROLES[r].color]);
      if (fixedTag[pin]) tags.push(fixedTag[pin]);
      const lw = name.length * 5.3 + 8;
      let tx = left ? lx - lw : lx + lw;
      for (const [text, color] of tags) {
        const tw = text.length * 5.6 + 12;
        const rx = left ? tx - tw : tx;
        s += `<g class="tag"><rect x="${rx}" y="${y - 8}" width="${tw}" height="16" fill="${color}" rx="4"/><text x="${rx + tw / 2}" y="${y + 3}" text-anchor="middle">${esc(text)}</text></g>`;
        tx = left ? rx - 4 : rx + tw + 4;
      }
      if (roles.length) {
        s += `<circle cx="${x}" cy="${y}" r="9.5" fill="none" stroke="${ROLES[roles[0]].color}" stroke-width="2.5"/>`;
      }
    }
    s += `</svg>`;
    $("#picoSvg").innerHTML = s;
  }

  function gpOptions(selected) {
    return (S.state ? S.state.header_gpios : Object.keys(GP_TO_PIN).map(Number)).map((g) =>
      `<option value="${g}" ${g === selected ? "selected" : ""}>GP${g} · pin ${GP_TO_PIN[g]}</option>`).join("");
  }

  function renderPinForm() {
    const roles = S.singleDD ? ["rst", "dc", "dd_i"] : ["rst", "dc", "dd_i", "dd_o"];
    $("#pinForm").innerHTML = roles.map((r) =>
      `<div class="pf"><label style="--role:${ROLES[r].color}"><i></i>${esc(roleLabel(r))}</label>
       <select data-pin="${r}">${gpOptions(S.pins[r])}</select></div>`).join("");
    $("#singleDD").checked = S.singleDD;
  }

  function renderConnTable() {
    const p = pinsForRole();
    const sw = (c) => `<span class="sw" style="background:${c}"></span>`;
    const gp = (g) => `GP${g}`;
    const rows = [
      [sw("#c3272e") + "3V3(OUT)", "36", "<code>BAT +</code> 3.3 V", T("wi.where.vdd")],
      [sw("#3c3c3c") + "GND", "38", "<code>BAT −</code>", T("wi.where.gnd")],
      [sw(ROLES.rst.color) + gp(p.rst), GP_TO_PIN[p.rst], "<code>RESET_N</code>", T("wi.where.rst")],
      [sw(ROLES.dc.color) + gp(p.dc), GP_TO_PIN[p.dc], "<code>DC</code> · <code>P2_2</code>", T("wi.where.dc")],
    ];
    if (S.singleDD || p.dd_i === p.dd_o) {
      rows.push([sw(ROLES.dd_i.color) + gp(p.dd_i), GP_TO_PIN[p.dd_i], "<code>DD</code> · <code>P2_1</code>", T("wi.where.dd")]);
    } else {
      rows.push([sw(ROLES.dd_i.color) + gp(p.dd_i) + " + " + sw(ROLES.dd_o.color) + gp(p.dd_o),
        GP_TO_PIN[p.dd_i] + " + " + GP_TO_PIN[p.dd_o], "<code>DD</code> · <code>P2_1</code>",
        T("wi.where.dd") + " " + T("wi.where.dd2")]);
    }
    $("#connTable").innerHTML =
      `<thead><tr><th>${T("wi.col.pico")}</th><th>${T("wi.col.pin")}</th><th>${T("wi.col.label")}</th><th>${T("wi.col.where")}</th></tr></thead><tbody>` +
      rows.map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td class="muted">${esc(r[3])}</td></tr>`).join("") + "</tbody>";
  }

  function renderWiring() {
    renderRoles();
    renderPicoSvg();
    renderPinForm();
    renderConnTable();
    const p = pinsForRole();
    $("#picoPinsLine").textContent = T("pi.withpins", {
      rst: p.rst, dc: p.dc, dd: p.dd_i === p.dd_o ? "GP" + p.dd_i : `GP${p.dd_i} + GP${p.dd_o}`,
    });
  }

  function validatePins(p) {
    const vals = [p.rst, p.dc, p.dd_i];
    if (new Set(vals).size < 3 || p.dd_o === p.rst || p.dd_o === p.dc) return T("pins.duplicate");
    return null;
  }

  let saveTimer = null;
  function pinsChanged() {
    const p = pinsForRole();
    const err = validatePins(p);
    $("#pinError").hidden = !err;
    $("#pinError").textContent = err || "";
    renderWiring();
    renderChipsSoon();
    if (err) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      const r = await api("/api/config", { pins: p });
      if (r.ok) {
        S.state.config = r.config;
        if (S.pico && S.pico.pins) {
          S.pico.pins_match = ["rst", "dc", "dd_i", "dd_o"].every((k) => S.pico.pins[k] === p[k]);
        }
        const note = $("#pinSaved");
        note.hidden = false;
        setTimeout(() => { note.hidden = true; }, 1500);
        renderPicoStatus();
        renderChips();
        renderSteps();
      } else {
        $("#pinError").hidden = false;
        $("#pinError").textContent = r.error;
      }
    }, 250);
  }

  function assignPin(role, gp) {
    // swap if another role already uses this GPIO
    const p = S.pins;
    for (const r of Object.keys(ROLES)) {
      if (r !== role && p[r] === gp && !(S.singleDD && r === "dd_o")) {
        if (!(role === "dd_i" && r === "dd_o") && !(role === "dd_o" && r === "dd_i")) p[r] = p[role];
      }
    }
    p[role] = gp;
    if (S.singleDD) p.dd_o = p.dd_i;
    pinsChanged();
  }

  // pins.duplicate lives in the server catalog; mirror it here
  window.I18N.en["pins.duplicate"] = "RST, DC and DD must be on different GPIOs.";
  window.I18N.fr["pins.duplicate"] = "RST, DC et DD doivent être sur des GPIO différents.";

  // ================================================================ pico
  let picoTimer = null;
  async function refreshPico() {
    clearTimeout(picoTimer);
    if (!S.busy) {
      try {
        const st = await api("/api/pico/status");
        if (st.state !== "busy") S.pico = st;
      } catch (e) { /* toast already shown */ }
      renderPicoStatus();
      renderChips();
      renderSteps();
    }
    if (S.view === "pico") picoTimer = setTimeout(refreshPico, 3000);
  }

  function renderPicoStatus() {
    const p = S.pico;
    const box = $("#picoStatus");
    const line = (icon, cls, title, help) =>
      `<div class="status-line"><div class="status-icon ${cls}">${icon}</div><div class="status-text"><b>${title}</b>${help ? `<span class="muted small">${help}</span>` : ""}</div></div>`;
    let html = "";
    let installLabel = T("pi.install");
    let showApply = false;
    if (S.busy && (!p || p.state === "busy")) html = line("…", "idle", esc(T("pi.st.busy")));
    else if (!p || p.state === "absent") html = line("?", "bad", esc(T("pi.st.absent")), esc(T("pi.st.absent.help")));
    else if (p.state === "bootsel") html = line("↓", "warn", esc(T("pi.st.bootsel", { board: p.board_id })));
    else if (p.state === "cclib") html = line("!", "warn", esc(T("pi.st.cclib", { port: p.port })), esc(T("pi.st.cclib.help")));
    else if (p.state === "unknown") html = line("?", "warn", esc(T("pi.st.unknown", { port: p.port })), esc(T("pi.st.unknown.help")));
    else if (p.state === "monopink") {
      installLabel = T("pi.reinstall");
      showApply = true;
      html = line("✓", p.pins_match ? "ok" : "warn", esc(T("pi.st.monopink", { v: p.version, board: p.board || "?", port: p.port })));
      if (p.pins) {
        const pp = p.pins;
        html += `<div class="pins-badges"><span class="muted small">${esc(T("pi.pins.stored"))}${S.lang === "fr" ? " :" : ":"}</span>
          <span class="pb">RST GP${pp.rst}</span><span class="pb">DC GP${pp.dc}</span>
          <span class="pb">DD GP${pp.dd_i}${pp.dd_o !== pp.dd_i ? "+GP" + pp.dd_o : ""}</span>
          <span class="pill ${p.pins_match ? "ok" : "warn"}">${esc(T(p.pins_match ? "pi.pins.match" : "pi.pins.mismatch"))}</span></div>`;
      }
    }
    box.innerHTML = html;
    $("#picoInstall").textContent = installLabel;
    $("#picoApply").hidden = !showApply;
    $("#picoApply").classList.toggle("primary", showApply && !p.pins_match);
  }

  // ================================================================ label
  function renderLabel() {
    const l = S.label;
    const res = $("#labelResult");
    if (!l || l.error) {
      res.hidden = true;
      $("#eraseBox").hidden = true;
      $("#installBox").hidden = true;
      return;
    }
    const fw = l.firmware;
    let fwText;
    if (l.locked) fwText = T("la.fw.hidden");
    else if (fw && fw.installed) fwText = T("la.fw.monopink", { v: fw.version });
    else if (fw && fw.blank) fwText = T("la.fw.blank");
    else fwText = T("la.fw.other");
    const probe = l.probe || {};
    res.innerHTML = `
      <span class="k">${esc(T("la.chip"))}</span><span>${esc(l.chip)} · ID ${esc(l.chip_id)} · rev ${esc(l.revision)}</span>
      <span class="k">${esc(T("la.lock"))}</span><span><span class="pill ${l.locked ? "bad" : "ok"}">${esc(T(l.locked ? "la.lock.on" : "la.lock.off"))}</span></span>
      <span class="k">${esc(T("la.fw"))}</span><span><span class="pill ${fw && fw.installed ? "ok" : "warn"}">${esc(fwText)}</span></span>
      <span class="k">${esc(T("la.probe"))}</span><span class="muted">${esc(probe.kind || "?")}${probe.version ? " v" + esc(probe.version) : ""} · ${esc(probe.port || "")}</span>`;
    res.hidden = false;
    $("#eraseBox").hidden = !l.locked;
    $("#installBox").hidden = l.locked;
    $("#labelInstall").textContent = T(fw && fw.installed ? "la.reinstall" : "la.install");
  }

  function renderTimeline(states, running, target = "#timeline") {
    const seen = {};
    for (const s of states || []) seen[s.state] = s.t;
    const codes = Object.keys(seen).map(Number);
    const last = codes.length ? Math.max(...codes) : 0;
    const list = RUN_STATES.filter((c) => c !== 112 || seen[112] !== undefined);
    $(target).innerHTML = list.map((c) => {
      let cls = "";
      if (c < last || (c === last && (!running || c >= 112))) cls = "done";
      else if (c === last && running) cls = "now";
      else if (running && c > last && c === list.find((x) => x > last) && last === 0) cls = "now";
      const t = seen[c] !== undefined ? `+${seen[c]} s` : "";
      return `<li class="${cls}"><span class="tl-dot"></span><span>${esc(T("state." + c))}</span><span class="tl-t">${t}</span></li>`;
    }).join("");
  }

  function labelFromResult(snap) {
    // tag_info result -> S.label
    if (snap.status === "done" && snap.result) {
      S.label = snap.result;
    } else if (snap.status === "error") {
      S.label = { error: snap.error };
    }
  }

  // ================================================================ picture
  function paramControls() {
    const p = S.params;
    $$("#view-picture .seg[data-param]").forEach((seg) => {
      $$("button", seg).forEach((b) => b.classList.toggle("on", String(p[seg.dataset.param]) === b.dataset.value));
    });
    $$('#view-picture input[type=checkbox][data-param]').forEach((c) => { c.checked = !!p[c.dataset.param]; });
    $$('#view-picture input[type=range][data-param]').forEach((r) => {
      r.value = p[r.dataset.param];
      const out = r.parentElement.querySelector("output");
      if (out) out.textContent = r.value;
    });
    $$("#view-picture [data-show]").forEach((el) => {
      const k = el.dataset.show;
      el.hidden = k === "use_red" ? !p.use_red : k === "levels" ? p.mode !== "levels" : k === "contain" ? p.fit !== "contain" : false;
    });
    const mock = $("#labelMock");
    mock.classList.toggle("landscape", p.orientation === "landscape");
    mock.classList.toggle("portrait", p.orientation !== "landscape");
    mock.classList.toggle("zoom", $("#zoom").checked);
  }

  let previewTimer = null;
  function schedulePreview(delay = 120) {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(runPreview, delay);
  }

  async function runPreview() {
    const has = S.state && S.state.has_source;
    $("#noImage").hidden = !!has;
    $("#labelMock").hidden = !has;
    $("#sendImage").disabled = !has;
    $("#dlBtn").disabled = !has;
    if (!has) { $("#stats").innerHTML = ""; return; }
    const seq = ++S.previewSeq;
    $("#previewSpin").hidden = false;
    const r = await api("/api/image/preview", { params: S.params });
    if (seq !== S.previewSeq) return;
    $("#previewSpin").hidden = true;
    if (!r.ok) { toast(r.error, true); return; }
    $("#preview").src = r.preview;
    const st = r.stats;
    $("#stats").innerHTML = `<span class="bar3"><span style="width:${st.white}%"></span><span style="width:${st.black}%"></span><span style="width:${st.red}%"></span></span>
      <span>${esc(T("pc.stats", { w: st.white, b: st.black, r: st.red }))}</span>`;
  }

  function renderSource() {
    const st = S.state;
    const img = $("#sourceThumb");
    if (st && st.has_source) {
      img.src = "/api/image/source?t=" + Date.now();
      img.hidden = false;
      $("#sourceName").textContent = st.source_name || "";
    } else {
      img.hidden = true;
      $("#sourceName").textContent = "";
    }
  }

  async function uploadFile(file) {
    if (!file) return;
    let r;
    try {
      const resp = await fetch("/api/image/upload", {
        method: "POST",
        headers: { "X-MonopInk": "1", "X-Filename": encodeURIComponent(file.name).slice(0, 200), "X-Lang": S.lang,
          "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
      r = await resp.json();
    } catch (e) {
      toast(T("err.network"), true);
      return;
    }
    if (!r.ok) { toast(r.error, true); return; }
    S.state.has_source = true;
    S.state.source_name = decodeURIComponent(r.name);
    // pick a sensible orientation for the new picture
    S.params.orientation = r.width > r.height * 1.15 ? "landscape" : "portrait";
    paramControls();
    renderSource();
    schedulePreview(0);
  }

  function refreshCurrent() {
    const img = $("#currentImg");
    if (S.state && S.state.has_label_image) {
      img.src = "/api/label/preview?t=" + Date.now();
      img.hidden = false;
      $("#currentNone").hidden = true;
    } else {
      img.hidden = true;
      $("#currentNone").hidden = false;
    }
  }

  // ================================================================ tools
  async function refreshPorts() {
    const r = await api("/api/ports");
    const cur = (S.state && S.state.config.port) || "auto";
    const opts = [`<option value="auto">${esc(T("to.port.auto"))}</option>`];
    for (const p of r.ports || []) {
      opts.push(`<option value="${esc(p.device)}">${esc(p.device)}${p.is_pico ? " · Raspberry Pi" : ""}</option>`);
    }
    if (cur !== "auto" && !(r.ports || []).some((p) => p.device === cur)) {
      opts.push(`<option value="${esc(cur)}">${esc(cur)}</option>`);
    }
    $("#portSelect").innerHTML = opts.join("");
    $("#portSelect").value = cur;
  }

  function renderTools() {
    const st = S.state;
    if (!st) return;
    const d = st.config.display || {};
    $("#calRot").checked = !!d.rotate180;
    $("#calMirror").checked = !!d.mirror;
    $("#aboutText").textContent = T("to.about.text", { v: st.version });
    $("#simCard").hidden = !st.simulate;
    if (st.sim) {
      $("#simConnected").checked = st.sim.connected;
      $("#simWrong").checked = st.sim.wired.dc !== 4;
    }
  }

  // ================================================================ jobs / console
  function setBusy(b) {
    S.busy = b;
    document.body.classList.toggle("busy", b);
    $("#cancelJob").hidden = !b;
    renderChips();
  }

  function consoleOpen(open) {
    $("#console").classList.toggle("open", open);
  }

  async function startJob(op, args, opts = {}) {
    if (S.busy) { toast(T("err.busy"), true); return; }
    const r = await api("/api/jobs", { op, args: args || {}, lang: S.lang });
    if (!r.ok) { toast(r.error, true); return; }
    trackJob(r.id, op, opts);
  }

  function trackJob(id, op, opts = {}) {
    S.job = { id, op, next: 0, opts };
    setBusy(true);
    $("#consoleBody").innerHTML = "";
    $("#consoleJob").textContent = T("job." + op) + " — " + T("con.running");
    $("#consoleJob").className = "console-job running";
    $("#progress").hidden = true;
    consoleOpen(true);
    if (opts.onStart) opts.onStart();
    pollJob();
  }

  async function pollJob() {
    const job = S.job;
    if (!job) return;
    let snap;
    try {
      const r = await fetch(`/api/jobs/${job.id}?since=${job.next}`);
      snap = await r.json();
    } catch (e) {
      setTimeout(pollJob, 1000);
      return;
    }
    if (snap.ok === false) { setBusy(false); return; }
    const body = $("#consoleBody");
    for (const l of snap.log) {
      const div = document.createElement("div");
      div.className = "log-line " + l.level;
      div.innerHTML = `<span class="t">${l.t.toFixed(1).padStart(5)}s</span>${esc(l.text)}`;
      body.appendChild(div);
      if (l.level === "action") job.action = true;
      else if (l.level === "ok" || l.level === "error") job.action = false;
    }
    job.next = snap.next;
    body.scrollTop = body.scrollHeight;
    if (snap.progress && snap.progress.total) {
      $("#progress").hidden = false;
      $("#progressBar").style.width = Math.round(100 * snap.progress.done / snap.progress.total) + "%";
    }
    if (job.op === "pico_flash") {
      const need = !!(job.action && snap.status === "running");
      if (need && $("#bootselHelp").hidden) {
        // make room: the user now has to act on the hardware
        consoleOpen(false);
        $("#bootselHelp").hidden = false;
        $("#bootselHelp").scrollIntoView({ behavior: "smooth", block: "center" });
      } else if (!need) {
        $("#bootselHelp").hidden = true;
      }
    }
    if (job.opts.onUpdate) job.opts.onUpdate(snap);

    if (snap.status === "running") {
      setTimeout(pollJob, 350);
      return;
    }
    $("#consoleJob").textContent = T("job." + job.op) + " — " + T("con." + (snap.status === "done" ? "done" : snap.status)) + ` (${snap.elapsed} s)`;
    $("#consoleJob").className = "console-job " + snap.status;
    $("#bootselHelp").hidden = true;
    S.job = null;
    setBusy(false);
    if (snap.status === "done") $("#progressBar").style.width = "100%";
    if (job.opts.onDone) job.opts.onDone(snap);
    await refreshState();
    renderAll();
  }

  // ================================================================ state / render
  async function refreshState() {
    try {
      S.state = await api("/api/state");
    } catch (e) {
      return;
    }
  }

  let chipsTimer = null;
  function renderChipsSoon() { clearTimeout(chipsTimer); chipsTimer = setTimeout(renderChips, 50); }

  function renderAll() {
    if (!S.state) return;
    $("#simBadge").hidden = !S.state.simulate;
    renderEnv();
    renderWiring();
    renderPicoStatus();
    renderLabel();
    paramControls();
    renderSource();
    renderTools();
    renderNfc();
    renderChips();
    renderSteps();
  }

  // ================================================================ NFC
  function nfcLink() {
    const url = (S.state.config.nfc_url || "").trim();
    if (!url) return "";
    const d = S.state.config.display || {};
    const q = new URLSearchParams({ lang: S.lang, rot: d.rotate180 ? 1 : 0, mirror: d.mirror ? 1 : 0 });
    return url + (url.includes("?") ? "&" : "?") + q;
  }

  function renderNfc() {
    const inp = $("#nfcUrl");
    if (document.activeElement !== inp) inp.value = S.state.config.nfc_url || "";
    const link = nfcLink();
    $("#nfcOpen").hidden = !link;
    if (link) $("#nfcOpen").href = link;
    const d = S.nfc;
    const box = $("#nfcResult");
    box.hidden = !d;
    if (!d) return;
    const row = (k, v) => `<dt>${T(k)}</dt><dd>${esc(String(v))}</dd>`;
    box.innerHTML = row("nf.r.chip", `NTAG I2C plus ${d.variant}`) + row("nf.r.uid", d.uid) +
      row("nf.r.cc", d.cc) +
      row("nf.r.prot", d.auth0 >= 0xEB ? T("nf.r.prot.none") : T("nf.r.prot.pwd", { p: d.auth0.toString(16) + "h" })) +
      row("nf.r.wake", T(d.wake === "fd" ? "nf.r.wake.fd" : "nf.r.wake.poll"));
  }

  // ================================================================ events
  function bind() {
    document.addEventListener("click", (e) => {
      const go = e.target.closest("[data-goto]");
      if (go) { show(go.dataset.goto); return; }
      const nav = e.target.closest("#steps button");
      if (nav) { show(nav.dataset.view); return; }
      const lang = e.target.closest(".lang-switch button");
      if (lang) { setLang(lang.dataset.lang); return; }
      if (!e.target.closest(".menu")) $("#dlMenu").hidden = true;
    });

    // wiring
    $("#roles").addEventListener("click", (e) => {
      const b = e.target.closest("[data-role]");
      if (b) { S.armed = b.dataset.role; renderRoles(); }
    });
    $("#picoSvg").addEventListener("click", (e) => {
      const c = e.target.closest("[data-gp]");
      if (!c) return;
      assignPin(S.armed, +c.dataset.gp);
      // move on to the next role for quick assignment
      const order = S.singleDD ? ["rst", "dc", "dd_i"] : ["rst", "dc", "dd_i", "dd_o"];
      S.armed = order[(order.indexOf(S.armed) + 1) % order.length];
      renderRoles();
    });
    $("#pinForm").addEventListener("change", (e) => {
      const sel = e.target.closest("select[data-pin]");
      if (sel) assignPin(sel.dataset.pin, +sel.value);
    });
    $("#singleDD").addEventListener("change", (e) => {
      S.singleDD = e.target.checked;
      if (S.singleDD) S.pins.dd_o = S.pins.dd_i;
      else if (S.pins.dd_o === S.pins.dd_i) {
        const used = new Set([S.pins.rst, S.pins.dc, S.pins.dd_i]);
        S.pins.dd_o = S.state.header_gpios.find((g) => g > S.pins.dd_i && !used.has(g)) ?? S.state.header_gpios.find((g) => !used.has(g));
      }
      pinsChanged();
    });
    $("#pinDefaults").addEventListener("click", () => {
      S.pins = { ...DEFAULT_PINS };
      S.singleDD = false;
      pinsChanged();
    });

    // pico
    $("#picoRefresh").addEventListener("click", refreshPico);
    $("#picoInstall").addEventListener("click", () => startJob("pico_flash", { pins: pinsForRole() }, {
      onDone: (snap) => {
        if (snap.status === "done") {
          S.pico = snap.result;
          toast(T("pi.done"));
        }
        refreshPico();
      },
    }));
    $("#picoApply").addEventListener("click", () => startJob("pico_pins", { pins: pinsForRole() }, {
      onDone: () => refreshPico(),
    }));

    // label
    $("#labelTest").addEventListener("click", () => startJob("tag_info", {}, {
      onDone: (snap) => { labelFromResult(snap); renderLabel(); renderChips(); renderSteps(); },
    }));
    $("#eraseConfirm").addEventListener("change", (e) => { $("#eraseGo").disabled = !e.target.checked; });
    const installOpts = {
      onStart: () => { $("#timelineBox").hidden = false; $("#labelOk").hidden = true; $("#labelSuspicious").hidden = true; renderTimeline([], true); },
      onUpdate: (snap) => renderTimeline(snap.run_states, snap.status === "running"),
      onDone: (snap) => {
        renderTimeline(snap.run_states, false);
        if (snap.status === "done") {
          const run = snap.result && snap.result.run;
          S.label = { ...(S.label || {}), locked: false, error: null,
            firmware: { installed: true, version: snap.result.firmware_version } };
          $("#labelOk").hidden = !!(run && run.suspicious);
          $("#labelSuspicious").hidden = !(run && run.suspicious);
          $("#eraseConfirm").checked = false;
          $("#eraseGo").disabled = true;
        }
        renderLabel(); renderChips(); renderSteps();
      },
    };
    $("#eraseGo").addEventListener("click", () => startJob("tag_install", { erase: true }, installOpts));
    $("#labelInstall").addEventListener("click", () => startJob("tag_install", { erase: false }, installOpts));

    // picture
    const drop = $("#drop");
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => uploadFile(e.dataTransfer.files[0]));
    $("#fileInput").addEventListener("change", (e) => { uploadFile(e.target.files[0]); e.target.value = ""; });
    document.addEventListener("paste", (e) => {
      if (S.view !== "picture") return;
      const item = [...(e.clipboardData || {}).items || []].find((i) => i.type.startsWith("image/"));
      if (item) uploadFile(item.getAsFile());
    });
    $("#useTestCard").addEventListener("click", async () => {
      await api("/api/image/test-pattern", { orientation: S.params.orientation });
      S.state.has_source = true;
      S.state.source_name = "test-pattern.png";
      S.params = { ...DEFAULT_PARAMS, orientation: S.params.orientation, mode: "threshold", fit: "stretch" };
      paramControls();
      renderSource();
      schedulePreview(0);
    });
    $("#view-picture").addEventListener("click", (e) => {
      const b = e.target.closest(".seg[data-param] button");
      if (!b) return;
      S.params[b.parentElement.dataset.param] = b.dataset.value;
      paramControls();
      schedulePreview(0);
    });
    $$('#view-picture input[data-param]').forEach((inp) => {
      inp.addEventListener(inp.type === "range" ? "input" : "change", () => {
        S.params[inp.dataset.param] = inp.type === "checkbox" ? inp.checked : +inp.value;
        if (inp.dataset.param === "black_level" && S.params.white_level < S.params.black_level) S.params.white_level = S.params.black_level;
        if (inp.dataset.param === "white_level" && S.params.black_level > S.params.white_level) S.params.black_level = S.params.white_level;
        paramControls();
        schedulePreview(inp.type === "range" ? 140 : 0);
      });
    });
    $("#zoom").addEventListener("change", paramControls);
    $("#resetAdjust").addEventListener("click", () => {
      S.params = { ...DEFAULT_PARAMS, orientation: S.params.orientation };
      paramControls();
      schedulePreview(0);
    });
    $("#sendImage").addEventListener("click", () => startJob("tag_image", { params: S.params }, {
      onDone: (snap) => {
        if (snap.status === "done") {
          toast(T("pc.sent"));
          S.state.has_label_image = true;
          refreshCurrent();
        }
      },
    }));
    $("#dlBtn").addEventListener("click", () => { $("#dlMenu").hidden = !$("#dlMenu").hidden; });
    $("#dlMenu").addEventListener("click", (e) => {
      const b = e.target.closest("[data-fmt]");
      if (!b) return;
      $("#dlMenu").hidden = true;
      const a = document.createElement("a");
      a.href = `/api/image/export?fmt=${b.dataset.fmt}&params=${encodeURIComponent(JSON.stringify(S.params))}`;
      a.download = "";
      document.body.appendChild(a);
      a.click();
      a.remove();
    });

    // NFC
    $("#nfcUrlSave").addEventListener("click", async () => {
      const r = await api("/api/config", { nfc_url: $("#nfcUrl").value.trim() });
      if (!r.ok) { toast(r.error, true); return; }
      S.state.config = r.config;
      renderNfc();
      toast(T("nf.url.saved"));
    });
    $("#nfcInfo").addEventListener("click", () => startJob("nfc_info", {}, {
      onDone: (snap) => { S.nfc = snap.status === "done" ? snap.result : null; renderNfc(); },
    }));
    $("#nfcSend").addEventListener("click", () => startJob("nfc_send", { params: S.params }, {
      onDone: (snap) => {
        if (snap.status === "done") {
          toast(T("nf.sent"));
          S.state.has_label_image = true;
          refreshCurrent();
        }
      },
    }));
    $("#nfcArm").addEventListener("click", () => startJob("tag_reset"));

    // tools
    $("#toolRun").addEventListener("click", () => startJob("tag_run"));
    $("#toolReset").addEventListener("click", () => startJob("tag_reset"));
    $("#toolBoot").addEventListener("click", () => startJob("tag_boottest"));
    $("#toolDump").addEventListener("click", () => startJob("tag_dump", {}, {
      onDone: (snap) => {
        if (snap.status === "done") {
          const a = document.createElement("a");
          a.href = "/api/label/dump";
          a.download = "monopink-flash.bin";
          document.body.appendChild(a); a.click(); a.remove();
        }
      },
    }));
    const saveDisplay = async () => {
      const r = await api("/api/config", { display: { rotate180: $("#calRot").checked, mirror: $("#calMirror").checked } });
      if (r.ok) S.state.config = r.config;
    };
    $("#calRot").addEventListener("change", saveDisplay);
    $("#calMirror").addEventListener("change", saveDisplay);
    $("#calTest").addEventListener("click", async () => {
      await api("/api/image/test-pattern", { orientation: "portrait" });
      S.params = { ...DEFAULT_PARAMS, mode: "threshold", fit: "stretch" };
      S.state.has_source = true;
      S.state.source_name = "test-pattern.png";
      renderSource();
      startJob("tag_image", { params: S.params }, {
        onDone: (snap) => { if (snap.status === "done") { S.state.has_label_image = true; toast(T("pc.sent")); } },
      });
    });
    $("#portSelect").addEventListener("change", async (e) => {
      const r = await api("/api/config", { port: e.target.value });
      if (r.ok) S.state.config = r.config;
    });
    $("#portRefresh").addEventListener("click", refreshPorts);
    let hexText = null;
    $("#hexFile").addEventListener("change", async (e) => {
      const f = e.target.files[0];
      hexText = f ? await f.text() : null;
      $("#hexName").textContent = f ? f.name : "";
      $("#hexGo").disabled = !hexText;
    });
    $("#hexGo").addEventListener("click", () => {
      if (!hexText) return;
      startJob("tag_hex", { hex: hexText, erase: $("#hexErase").checked }, {
        onDone: (snap) => {
          if (snap.status === "done") { S.label = null; renderChips(); }
        },
      });
    });
    $("#simConnected").addEventListener("change", (e) => api("/api/sim", { connected: e.target.checked }));
    $("#simWrong").addEventListener("change", (e) => api("/api/sim", { wired: { dc: e.target.checked ? 5 : 4 } }));
    $("#simReset").addEventListener("click", async () => {
      await api("/api/sim", { reset: true });
      S.label = null; S.pico = null;
      await refreshState();
      renderAll();
      toast("OK");
    });

    // console
    $("#consoleHead").addEventListener("click", (e) => {
      if (e.target.closest("#cancelJob")) return;
      consoleOpen(!$("#console").classList.contains("open"));
    });
    $("#cancelJob").addEventListener("click", () => {
      if (S.job) api(`/api/jobs/${S.job.id}/cancel`, {});
    });

    window.addEventListener("hashchange", () => show(location.hash.slice(1)));
  }

  // ================================================================ boot
  async function boot() {
    await refreshState();
    if (!S.state) return;
    const cfg = S.state.config;
    const saved = store.get("mp.lang", null);
    S.lang = cfg.lang || (saved === "en" || saved === "fr" ? saved : null) ||
      ((navigator.language || "en").toLowerCase().startsWith("fr") ? "fr" : "en");
    S.pins = { ...DEFAULT_PINS, ...cfg.pins };
    S.singleDD = S.pins.dd_i === S.pins.dd_o;
    S.params = { ...DEFAULT_PARAMS, ...(cfg.image || {}) };
    bind();
    applyI18n();
    show(location.hash.slice(1) || "overview");
    if (S.state.busy && S.state.current_job) trackJob(S.state.current_job, S.state.current_op || "tag_info");
    refreshPico();
  }

  boot();
})();
