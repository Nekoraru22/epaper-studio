/**
 * The "Data" view: the exact buffer that would be uploaded, one panel row per
 * line, drawn on a canvas that only paints the visible lines (there are tens
 * of thousands of bytes). Each byte is tinted by how much ink it represents,
 * so the picture shows through the hex.
 */

import { $, hex2 } from "./dom.js";
import { int, t } from "./i18n.js";
import { errorText } from "./status.js";

const HEX = Array.from({ length: 256 }, (_, v) => hex2(v));
const POP = Array.from({ length: 256 }, (_, v) => { let n = 0; while (v) { n += v & 1; v >>= 1; } return n; });
const D = { bytes: null, layout: null, lines: [], hover: -1, m: null, frame: 0, note: null };

export function setDump(packed) {
  const bin = atob(packed.data || "");
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  D.bytes = bytes;
  D.layout = packed.layout;
  D.note = packed.stats?.unsupported || null;
  D.lines = [];
  packed.layout.planes.forEach((pl, pi) => {
    D.lines.push({ head: true, plane: pi });
    const rows = Math.ceil(pl.length / packed.layout.row_bytes);
    for (let r = 0; r < rows; r++) D.lines.push({ plane: pi, row: r });
  });
}

export const dumpHint = () =>
  D.layout ? t("hint.data", { row_bytes: D.layout.row_bytes, block: D.layout.block }) : "";

function metrics() {
  const w = $("#dump").clientWidth;
  const rb = D.layout.row_bytes;
  // 4.6 characters for the row number, 2.4 per byte (two digits and a gap).
  const cw = w / (4.6 + rb * 2.4);
  const font = cw / 0.6; // IBM Plex Mono: one character is 0.6 em wide
  return { w, cw, font, lh: font * 1.3, gutter: cw * 4.6, step: cw * 2.4, rb };
}

export function sizeDump() {
  if (!D.layout) return;
  D.m = metrics();
  $("#dumpspace").style.height = Math.ceil(D.lines.length * D.m.lh) + "px";
  drawDump();
}

function byteColor(kind, v) {
  if (kind === "bw") return `rgba(34,34,38,${0.1 + (0.9 * (8 - POP[v])) / 8})`;   // 0 = ink
  if (kind === "red") return `rgba(176,36,40,${0.12 + (0.88 * POP[v]) / 8})`;     // 1 = red
  if (kind === "2bpp") {
    const px = [v >> 6, (v >> 4) & 3, (v >> 2) & 3, v & 3];
    const inked = px.filter((p) => p !== 1).length;
    const tone = px.includes(3) ? "176,36,40" : px.includes(2) ? "184,150,15" : "34,34,38";
    return `rgba(${tone},${0.1 + (0.9 * inked) / 4})`;
  }
  return "rgba(34,34,38,.75)";
}

export function drawDump() {
  const box = $("#dump");
  const cv = $("#dumpcv");
  if (!D.layout || box.classList.contains("hidden")) return;
  const m = D.m || (D.m = metrics());
  const H = box.clientHeight, top = box.scrollTop, dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(m.w * dpr);
  cv.height = Math.round(H * dpr);
  cv.style.width = m.w + "px";
  cv.style.height = H + "px";
  cv.style.top = top + "px";
  const c = cv.getContext("2d");
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.fillStyle = "#E8E7DE";
  c.fillRect(0, 0, m.w, H);

  if (!D.bytes.length) {
    c.fillStyle = "#6E6C63";
    c.font = "13px 'IBM Plex Sans', sans-serif";
    c.textAlign = "center";
    c.textBaseline = "middle";
    c.fillText(D.note ? errorText(D.note) : t("data.empty"), m.w / 2, H / 2);
    return;
  }

  const L = D.layout;
  const first = Math.max(0, Math.floor(top / m.lh));
  const last = Math.min(D.lines.length, Math.ceil((top + H) / m.lh) + 1);
  const mono = `${m.font}px 'IBM Plex Mono', ui-monospace, monospace`;
  c.textBaseline = "middle";

  for (let li = first; li < last; li++) {
    const ln = D.lines[li], pl = L.planes[ln.plane];
    const y = li * m.lh - top, cy = y + m.lh / 2;

    if (ln.head) {
      const size = Math.max(8, Math.min(12, m.font * 1.05));
      c.font = `600 ${size}px 'IBM Plex Sans', sans-serif`;
      c.textAlign = "left";
      c.fillStyle = pl.kind === "red" ? "#B02428" : "#4A4943";
      const legend = pl.kind === "raw" ? "" : "  ·  " + t(`plane.${pl.kind}.legend`);
      const range = t("data.bytes_range", { from: int(pl.start), to: int(pl.start + pl.length - 1) });
      c.fillText(`${t(`plane.${pl.kind}`)}  ·  ${range}${legend}`, m.gutter, cy);
      continue;
    }

    c.font = mono;
    c.textAlign = "right";
    c.fillStyle = "rgba(34,34,38,.38)";
    c.fillText(String(ln.row), m.gutter - m.cw * 1.2, cy);
    c.textAlign = "left";
    const rowStart = pl.start + ln.row * m.rb;
    const rowEnd = Math.min(rowStart + m.rb, pl.start + pl.length);
    for (let off = rowStart; off < rowEnd; off++) {
      const x = m.gutter + (off - rowStart) * m.step, v = D.bytes[off];
      if (off === D.hover) {
        c.fillStyle = "rgba(190,50,50,.18)";
        c.fillRect(x - m.cw * 0.2, y, m.cw * 2.4, m.lh);
      }
      if (off % L.block === 0) {                    // start of a 240-byte block
        c.fillStyle = "#BE3232";
        c.fillRect(x - m.cw * 0.25, y + m.lh * 0.08, Math.max(1, m.cw * 0.14), m.lh * 0.84);
      }
      c.fillStyle = byteColor(pl.kind, v);
      c.fillText(HEX[v], x, cy);
    }
  }
}

function hitTest(ev) {
  const box = $("#dump"), m = D.m, L = D.layout;
  if (!m || !L || !D.bytes.length) return null;
  const r = box.getBoundingClientRect();
  const ln = D.lines[Math.floor((ev.clientY - r.top + box.scrollTop) / m.lh)];
  if (!ln || ln.head) return null;
  const col = Math.floor((ev.clientX - r.left - m.gutter + m.cw * 0.2) / m.step);
  if (col < 0 || col >= m.rb) return null;
  const pl = L.planes[ln.plane], off = pl.start + ln.row * m.rb + col;
  if (off >= pl.start + pl.length) return null;
  return { off, pl, row: ln.row, col };
}

function showTip(ev, hit) {
  const tip = $("#dumptip"), L = D.layout, v = D.bytes[hit.off];
  const bits = v.toString(2).padStart(8, "0");
  const k = (key) => `<span class="k">${t(key)}</span>`;
  let pixels = "";
  if (L.aligned && (hit.pl.kind === "bw" || hit.pl.kind === "red")) {
    const x0 = hit.col * 8;
    const shown = hit.pl.kind === "bw"
      ? [...bits].map((b) => (b === "1" ? '<span class="on">1</span>' : '<span class="ink">0</span>')).join("")
      : bits;
    pixels = `<div>${k("data.tip.row")} ${hit.row}${L.transformed ? " " + t("data.tip.internal") : ""} · ${k("data.tip.pixels")} ${x0}–${x0 + 7}</div>
      <div>${k("data.tip.bits")} ${shown}  ${k(`plane.${hit.pl.kind}.legend`)}</div>`;
  } else if (L.aligned && hit.pl.kind === "2bpp") {
    const x0 = hit.col * 4;
    const names = ["black", "white", "yellow", "red"].map((n) => t(`pigment.${n}`).toLowerCase());
    pixels = `<div>${k("data.tip.row")} ${hit.row} · ${k("data.tip.pixels")} ${x0}–${x0 + 3}</div>
      <div>${[v >> 6, (v >> 4) & 3, (v >> 2) & 3, v & 3].map((p) => names[p]).join(" · ")}</div>`;
  }
  tip.innerHTML = `<div><b>0x${HEX[v].toUpperCase()}</b>  ${k("data.tip.byte")} ${int(hit.off)}</div>
    <div>${k("data.tip.block")} ${Math.floor(hit.off / L.block)} ${k("data.tip.position")} ${t("data.tip.of", { n: hit.off % L.block, total: L.block })}</div>${pixels}`;
  tip.classList.remove("hidden");
  const win = $("#window").getBoundingClientRect();
  let x = ev.clientX - win.left + 14, y = ev.clientY - win.top + 16;
  if (x + tip.offsetWidth > win.width - 6) x = ev.clientX - win.left - tip.offsetWidth - 14;
  if (y + tip.offsetHeight > win.height - 6) y = ev.clientY - win.top - tip.offsetHeight - 12;
  tip.style.left = Math.max(4, x) + "px";
  tip.style.top = Math.max(4, y) + "px";
}

export function wireDump() {
  const box = $("#dump");
  const tip = $("#dumptip");
  const redraw = () => { cancelAnimationFrame(D.frame); D.frame = requestAnimationFrame(drawDump); };
  box.addEventListener("scroll", () => { tip.classList.add("hidden"); redraw(); }, { passive: true });
  const hover = (ev) => {
    const hit = hitTest(ev), off = hit ? hit.off : -1;
    if (off !== D.hover) { D.hover = off; redraw(); }
    if (hit) showTip(ev, hit); else tip.classList.add("hidden");
  };
  box.addEventListener("pointermove", hover);
  box.addEventListener("pointerdown", hover); // a tap shows the tooltip on touch screens
  box.addEventListener("pointerleave", (ev) => {
    if (ev.pointerType !== "mouse") return; // touch: keep the tooltip after the finger lifts
    D.hover = -1; tip.classList.add("hidden"); redraw(); });
  document.fonts?.ready.then(drawDump);
}
