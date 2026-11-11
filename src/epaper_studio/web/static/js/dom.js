/** Tiny DOM helpers shared by every module. */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
/** Escape text before interpolating it into innerHTML. */
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESCAPES[c]);

export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** Wrap an angle into (-180, 180]. */
export const normAngle = (a) => {
  a = (((a + 180) % 360) + 360) % 360 - 180;
  return a === -180 ? 180 : a;
};

export const hex2 = (v) => v.toString(16).padStart(2, "0");
export const modelHex = (id) => "0x" + id.toString(16).toUpperCase().padStart(4, "0");
