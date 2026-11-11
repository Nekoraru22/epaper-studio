/**
 * The adjustment panel (right column) and the presets (left column).
 *
 * Controls are declared as data. Each item names a parameter ``k`` of
 * ``Params``; its label is ``control.<k>`` and its optional help text
 * ``control.<k>.help``. Option labels are ``option.<k>.<value>``.
 */

import { $, normAngle } from "./dom.js";
import { fixed, has, int, num, t } from "./i18n.js";
import { DEFAULTS, FRAMING, S } from "./state.js";
import { schedule } from "./render.js";
import { flash } from "./status.js";

const pct = (v) => int(v * 100) + " %";
const signed = (v, d = 2) => (v > 0 ? "+" : "") + fixed(v, d);

export const SECTIONS = [
  { id: "framing", items: [
    { k: "fit", type: "seg", opts: ["cover", "contain", "stretch"], bare: true },
    { k: "zoom", min: 0.2, max: 4, step: 0.01, fmt: (v) => fixed(v, 2) + "×" },
    { k: "pan_x", min: -1, max: 1, step: 0.01, fmt: (v) => signed(v) },
    { k: "pan_y", min: -1, max: 1, step: 0.01, fmt: (v) => signed(v) },
    { k: "rotate", min: -180, max: 180, step: 0.5, fmt: (v) => fixed(v, 1) + "°", quick: true },
    { k: "flip", type: "check" },
    { k: "background", type: "seg", opts: ["white", "black"] },
  ] },
  { id: "tone", items: [
    { k: "auto_levels", type: "check" },
    { k: "brightness", min: -0.5, max: 0.5, step: 0.01, fmt: (v) => signed(v) },
    { k: "contrast", min: 0.2, max: 3, step: 0.01, fmt: (v) => fixed(v, 2) },
    { k: "gamma", min: 0.3, max: 3, step: 0.01, fmt: (v) => fixed(v, 2) },
    { k: "sharpen", min: 0, max: 2, step: 0.05, fmt: (v) => fixed(v, 2) },
  ] },
  { id: "color", items: [
    { k: "saturation", min: 0, max: 3, step: 0.01, fmt: pct },
    { k: "hue", min: -180, max: 180, step: 1, fmt: (v) => (v > 0 ? "+" : "") + num(v) + "°" },
    { k: "color_bias", min: 0, max: 0.9, step: 0.01, fmt: pct },
    { k: "color_weight", min: 0.5, max: 8, step: 0.1, fmt: (v) => fixed(v, 1) },
  ] },
  { id: "dither", items: [
    { k: "palette", type: "seg", opts: ["bw", "bwr", "bwy", "bwry"] },
    { k: "dither", type: "select",
      opts: ["floyd", "atkinson", "jjn", "stucki", "burkes", "sierra", "sierra_lite", "bayer", "none"] },
    { k: "strength", min: 0, max: 1, step: 0.01, fmt: pct },
    { k: "serpentine", type: "check" },
    { k: "compress_range", type: "check" },
  ] },
];

/** Presets only change look-related parameters; ``FRAMING`` is kept. */
export const PRESETS = [
  { id: "photo", set: { dither: "jjn", contrast: 1.12, gamma: 1.08, sharpen: 0.55, saturation: 1.15, color_weight: 3.2 } },
  { id: "illustration", set: { dither: "atkinson", contrast: 1.1, saturation: 1.45, hue: 12, color_bias: 0.25, sharpen: 0.3, color_weight: 3 } },
  { id: "text", set: { dither: "none", auto_levels: true, contrast: 1.35, sharpen: 0.9, color_weight: 2 } },
  { id: "poster", set: { dither: "bayer", contrast: 1.25, saturation: 1.35, strength: 0.85 } },
];

/** Parameter key → function that refreshes its widget from ``S.p``. */
export const inputs = {};
const openState = {};

export function syncControls() {
  for (const k in inputs) inputs[k]();
}

const optionLabel = (k, v) => t(`option.${k}.${v}`);

function buildControl(it) {
  const wrap = document.createElement("div");
  wrap.className = "ctl";
  const type = it.type || "range";
  const label = t(`control.${it.k}`);

  if (type === "range") {
    wrap.innerHTML = `<label class="row"><span></span><span class="mono"></span></label>
      <input type="range" min="${it.min}" max="${it.max}" step="${it.step}">`;
    wrap.querySelector("span").textContent = label;
    const input = wrap.querySelector("input");
    const out = wrap.querySelector(".mono");
    input.setAttribute("aria-label", label);
    input.title = t("control.reset_hint");
    input.oninput = () => {
      S.p[it.k] = parseFloat(input.value);
      out.textContent = it.fmt(S.p[it.k]);
      schedule();
    };
    const reset = () => { S.p[it.k] = DEFAULTS[it.k]; syncControls(); schedule(); };
    input.ondblclick = reset;
    wrap.querySelector("label").ondblclick = reset;
    inputs[it.k] = () => { input.value = S.p[it.k]; out.textContent = it.fmt(S.p[it.k]); };
    if (it.quick) {
      const q = document.createElement("div");
      q.className = "rotq";
      for (const [text, v] of [["−90°", -90], ["0°", 0], ["+90°", 90], ["180°", 180]]) {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = text;
        b.onclick = () => {
          S.p.rotate = v === 0 ? 0 : v === 180 ? 180 : normAngle(S.p.rotate + v);
          syncControls();
          schedule();
        };
        q.appendChild(b);
      }
      wrap.appendChild(q);
    }
  } else if (type === "seg") {
    if (!it.bare) wrap.innerHTML = `<label class="row"><span></span></label>`;
    if (!it.bare) wrap.querySelector("span").textContent = label;
    const seg = document.createElement("div");
    seg.className = "seg";
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", label);
    for (const v of it.opts) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = optionLabel(it.k, v);
      b.dataset.v = v;
      b.onclick = () => { S.p[it.k] = v; syncControls(); schedule(); };
      seg.appendChild(b);
    }
    wrap.appendChild(seg);
    inputs[it.k] = () => seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === S.p[it.k]));
  } else if (type === "select") {
    wrap.innerHTML = `<label class="row"><span></span></label><select></select>`;
    wrap.querySelector("span").textContent = label;
    const sel = wrap.querySelector("select");
    sel.setAttribute("aria-label", label);
    for (const v of it.opts) {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = optionLabel(it.k, v);
      sel.appendChild(o);
    }
    sel.onchange = () => { S.p[it.k] = sel.value; schedule(); };
    inputs[it.k] = () => { sel.value = S.p[it.k]; };
  } else if (type === "check") {
    wrap.innerHTML = `<label class="check" style="color:var(--text)"><input type="checkbox"> <span></span></label>`;
    wrap.querySelector("span").textContent = label;
    const cb = wrap.querySelector("input");
    cb.onchange = () => { S.p[it.k] = cb.checked; schedule(); };
    inputs[it.k] = () => { cb.checked = !!S.p[it.k]; };
  }

  const helpKey = `control.${it.k}.help`;
  if (has(helpKey)) {
    const h = document.createElement("div");
    h.className = "help";
    h.textContent = t(helpKey);
    wrap.appendChild(h);
  }
  return wrap;
}

/** (Re)build the panel. Called at start-up and after a language change. */
export function buildControls({ collapsed = false } = {}) {
  const host = $("#controls");
  host.querySelectorAll("details").forEach((d) => { openState[d.dataset.id] = d.open; });
  host.innerHTML = "";
  for (const k in inputs) delete inputs[k];
  for (const sec of SECTIONS) {
    const d = document.createElement("details");
    d.className = "sec";
    d.dataset.id = sec.id;
    // On phones the panel starts collapsed so the page is not endlessly long.
    d.open = openState[sec.id] ?? (!collapsed || sec.id === "framing");
    const summary = document.createElement("summary");
    summary.textContent = t(`section.${sec.id}`);
    const reset = document.createElement("button");
    reset.className = "reset";
    reset.type = "button";
    reset.textContent = t("section.reset");
    reset.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      for (const it of sec.items) if (it.k !== "palette") S.p[it.k] = DEFAULTS[it.k];
      syncControls();
      schedule();
    };
    summary.appendChild(reset);
    d.appendChild(summary);
    const box = document.createElement("div");
    box.className = "ctrls";
    for (const it of sec.items) box.appendChild(buildControl(it));
    d.appendChild(box);
    host.appendChild(d);
  }
  syncControls();
}

export function buildPresets() {
  const host = $("#presets");
  host.innerHTML = "";
  for (const pr of PRESETS) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = t(`preset.${pr.id}`);
    const note = document.createElement("small");
    note.textContent = t(`preset.${pr.id}.note`);
    b.appendChild(note);
    b.onclick = () => {
      const keep = Object.fromEntries(FRAMING.map((k) => [k, S.p[k]]));
      S.p = { ...DEFAULTS, ...keep, ...pr.set };
      syncControls();
      schedule();
      flash("status.preset_applied", "ok", { name: t(`preset.${pr.id}`) });
    };
    host.appendChild(b);
  }
}
