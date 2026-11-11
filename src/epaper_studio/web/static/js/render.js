/**
 * Rendering the preview: debounced requests, layout of the tag window,
 * dragging/zooming the framing, and the source thumbnail.
 */

import { api } from "./api.js";
import { $, clamp } from "./dom.js";
import { t } from "./i18n.js";
import { S } from "./state.js";
import { dumpHint, setDump, sizeDump } from "./dump.js";
import { samplePixels, updateStats } from "./stats.js";
import { inputs, syncControls } from "./controls.js";
import { flash, flashError } from "./status.js";
import { renderDesigns } from "./designs.js";

let timer = null;
let controller = null;
let seq = 0;

/** Re-render after ``delay`` ms; rapid calls collapse into one request. */
export function schedule(delay = 70) {
  if (!S.id) return;
  clearTimeout(timer);
  timer = setTimeout(render, delay);
}

function lost(err) {
  if (err.status === 404) {
    S.id = null;
    $("#send").disabled = true;
  }
}

export async function render() {
  if (!S.id) return;
  controller?.abort();
  controller = new AbortController();
  const mine = ++seq;
  const sent = { ...S.p };
  const win = $("#window");
  win.classList.add("busy");
  try {
    if (sent.view === "data") {
      const packed = await api.packed(S.id, { ...sent, view: "pure" }, controller.signal);
      if (mine !== seq) return;
      S.rendered = sent;
      S.stats = packed.stats;
      setDump(packed);
      applyView();
      layoutPreview();
      updateStats();
      drawThumb();
      win.classList.remove("busy");
      $("#send").disabled = false;
      return;
    }
    const { blob, stats } = await api.render(S.id, sent, controller.signal);
    if (mine !== seq) return;
    const url = URL.createObjectURL(blob);
    const img = $("#preview");
    img.onload = () => {
      URL.revokeObjectURL(url);
      S.rendered = sent;
      S.stats = stats;
      applyView();
      layoutPreview();
      applyDragOffset();
      updateStats();
      drawThumb();
      samplePixels();
      win.classList.remove("busy");
    };
    img.src = url;
    $("#send").disabled = false;
  } catch (err) {
    if (err.name === "AbortError") return;
    win.classList.remove("busy");
    lost(err);
    flashError(err);
  }
}

/** Upload a file (from the picker, drag and drop or the clipboard). */
export async function loadFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    flash("status.not_image", "err");
    return;
  }
  flash("status.uploading", "busy");
  try {
    const data = await api.upload(file);
    if (S.design) S.design = { ...S.design, image: null }; // "Update" would now replace its image
    showSource(data, file.name || t("image.pasted"), URL.createObjectURL(file));
    Object.assign(S.p, { pan_x: 0, pan_y: 0, zoom: 1, rotate: 0, flip: false });
    syncControls();
    flash("");
    schedule(0);
  } catch (err) {
    flashError(err);
  }
}

/** Make ``image`` ({id, width, height}) the one being edited. ``url`` feeds the thumbnail. */
export function showSource(image, name, url) {
  S.id = image.id;
  S.srcW = image.width;
  S.srcH = image.height;
  S.srcName = name;
  const img = new Image();
  img.onload = () => { S.srcImg = img; drawThumb(); };
  img.src = url;
  $("#source").classList.remove("hidden");
  $("#srcname").textContent = name.length > 26 ? name.slice(0, 24) + "…" : name;
  $("#srcname").title = name;
  $("#srcsize").textContent = `${image.width}×${image.height}`;
  $("#empty").classList.add("hidden");
  $("#window").classList.add("loaded");
  renderDesigns();
}

/** Same media query as the pinned-preview rules in app.css. */
const PINNED = window.matchMedia("(max-width: 920px) and (min-height: 501px)");
PINNED.addEventListener?.("change", () => layoutPreview());

/** The centre block sticks while scrolling only if it fits in the window. */
export function updateStick() {
  const st = $(".stick");
  st.classList.remove("fits");
  st.classList.toggle("fits", st.offsetHeight + 90 < window.innerHeight);
}

export function layoutPreview() {
  const { width: W, height: H } = S.p;
  // The chosen zoom shrinks if the tag does not fit the centre column.
  const avail = ($("#stage").clientWidth || 900) - 68;
  // On phones the preview stays pinned at the top while the controls scroll, so it
  // must leave room for them: at most ~40 % of the screen height.
  const availH = PINNED.matches ? window.innerHeight * 0.4 : Infinity;
  const z = (S.ez = Math.max(0.25, Math.min(S.zoom, avail / W, availH / H)));
  for (const el of [$("#preview"), $("#window")]) {
    el.style.width = W * z + "px";
    el.style.height = H * z + "px";
  }
  updateStick();
  if (S.p.view === "data") sizeDump();
}

/** While dragging, shift the last image with CSS until the next one arrives. */
export function applyDragOffset() {
  const g = S.stats?.geometry;
  const r = S.rendered;
  const img = $("#preview");
  if (!g || !r) { img.style.transform = ""; return; }
  const dx = ((S.p.pan_x - r.pan_x) * (S.p.width - g.nw)) / 2 * S.ez;
  const dy = ((S.p.pan_y - r.pan_y) * (S.p.height - g.nh)) / 2 * S.ez;
  img.style.transform = dx || dy ? `translate(${dx}px, ${dy}px)` : "";
}

/** Show the image or the data view, and the matching hint. */
export function applyView() {
  const data = S.p.view === "data";
  $("#preview").classList.toggle("hidden", data);
  $("#dump").classList.toggle("hidden", !data);
  if (!data) $("#dumptip").classList.add("hidden");
  $("#hint").textContent = (data && dumpHint()) || t("hint.image");
}

/**
 * Drag to move the framing, wheel or pinch to zoom. Works with mouse, pen and
 * touch (pointer events); ``touch-action: none`` on the loaded window keeps
 * the browser from scrolling while you drag.
 */
export function wirePan() {
  const win = $("#window");
  const pointers = new Map();
  let drag = null;
  let pinch = null;

  const spread = () => {
    const [a, b] = [...pointers.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  };
  const startDrag = (p) => { drag = { x: p.x, y: p.y, px: S.p.pan_x, py: S.p.pan_y }; };

  win.addEventListener("pointerdown", (ev) => {
    if (!S.id) { $("#file").click(); return; }      // empty tag: open the picker
    if (!S.stats || S.p.view === "data") return;   // the data view scrolls instead
    pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    win.setPointerCapture(ev.pointerId);
    win.classList.add("drag");
    if (pointers.size === 1) startDrag(pointers.get(ev.pointerId));
    if (pointers.size === 2) { drag = null; pinch = { d: spread(), zoom: S.p.zoom }; }
  });
  win.addEventListener("pointermove", (ev) => {
    if (!pointers.has(ev.pointerId)) return;
    pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pinch && pointers.size === 2) {
      S.p.zoom = clamp(pinch.zoom * (spread() / pinch.d), 0.2, 4);
      inputs.zoom();
      schedule(60);
      return;
    }
    if (!drag) return;
    const g = S.stats.geometry;
    const spanX = (S.p.width - g.nw) / 2;
    const spanY = (S.p.height - g.nh) / 2;
    const dx = (ev.clientX - drag.x) / S.ez;
    const dy = (ev.clientY - drag.y) / S.ez;
    if (Math.abs(spanX) > 0.5) S.p.pan_x = clamp(drag.px + dx / spanX, -1, 1);
    if (Math.abs(spanY) > 0.5) S.p.pan_y = clamp(drag.py + dy / spanY, -1, 1);
    inputs.pan_x();
    inputs.pan_y();
    applyDragOffset();
    schedule(40);
  });
  const end = (ev) => {
    pointers.delete(ev.pointerId);
    if (pointers.size < 2) pinch = null;
    if (pointers.size === 1) startDrag([...pointers.values()][0]); // keep dragging with the other finger
    if (!pointers.size) { drag = null; win.classList.remove("drag"); }
  };
  win.addEventListener("pointerup", end);
  win.addEventListener("pointercancel", end);
  win.addEventListener("wheel", (ev) => {
    if (!S.id || S.p.view === "data") return;
    ev.preventDefault();
    S.p.zoom = clamp(S.p.zoom * Math.pow(1.0015, -ev.deltaY), 0.2, 4);
    inputs.zoom();
    schedule(60);
  }, { passive: false });
}

/** Source thumbnail with the visible area outlined. */
export function drawThumb() {
  const cv = $("#thumb");
  const img = S.srcImg;
  if (!img) return;
  const rot = (S.p.rotate * Math.PI) / 180;
  const w = img.naturalWidth, h = img.naturalHeight;
  const rw = Math.abs(w * Math.cos(rot)) + Math.abs(h * Math.sin(rot));
  const rh = Math.abs(w * Math.sin(rot)) + Math.abs(h * Math.cos(rot));
  const scale = (cv.parentElement.clientWidth || 236) / rw;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(rw * scale * dpr);
  cv.height = Math.round(rh * scale * dpr);
  cv.style.height = rh * scale + "px";
  const c = cv.getContext("2d");
  c.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);
  c.fillStyle = S.p.background === "black" ? "#000" : "#fff";
  c.fillRect(0, 0, rw, rh);
  c.save();
  c.translate(rw / 2, rh / 2);
  c.rotate(rot);
  if (S.p.flip) c.scale(-1, 1);
  c.drawImage(img, -w / 2, -h / 2);
  c.restore();

  const g = S.stats?.geometry;
  if (!g) return;
  const [x0, y0, x1, y1] = g.visible;
  const R = [x0 * rw, y0 * rh, (x1 - x0) * rw, (y1 - y0) * rh];
  c.fillStyle = "rgba(10,12,14,.62)";           // darken what falls outside the frame
  c.beginPath();
  c.rect(0, 0, rw, rh);
  c.rect(R[0], R[1] + R[3], R[2], -R[3]);
  c.fill("evenodd");
  c.strokeStyle = "#D24242";
  c.lineWidth = 2 / scale;
  c.strokeRect(R[0], R[1], R[2], R[3]);
}
