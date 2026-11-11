/** The status line in the header, and turning errors into readable text. */

import { $ } from "./dom.js";
import { has, t } from "./i18n.js";
import { S } from "./state.js";

/** Readable, translated text for an ``ApiError`` (or any error). */
export function errorText(err) {
  if (!err) return "";
  const key = `error.${err.code}`;
  if (err.code && has(key)) return t(key, err.params || {});
  return t("error.generic", { detail: err.message || String(err) });
}

let timer = null;

/**
 * Show a message. ``msg`` is a translation key, or ``{error}`` for an error.
 * ``kind`` is "ok", "err", "busy" or "" (clears). Messages are re-translated
 * when the language changes.
 */
export function flash(msg, kind = "", params = {}) {
  S.status = msg ? { msg, kind, params } : null;
  paint();
  clearTimeout(timer);
  if (kind === "ok" || kind === "err") timer = setTimeout(() => flash(""), 6000);
}

export const flashError = (error) => flash({ error }, "err");

export function paint() {
  const el = $("#status");
  const st = S.status;
  if (!st) {
    el.textContent = "";
    el.className = "";
    return;
  }
  const text = typeof st.msg === "string" ? t(st.msg, st.params) : errorText(st.msg.error);
  el.textContent = text.length > 110 ? text.slice(0, 108) + "…" : text;
  el.title = text;
  el.className = st.kind;
}
