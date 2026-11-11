/**
 * Internationalisation.
 *
 * UI strings live in ``locales/<lang>.json`` as a flat key → string map.
 * Strings may contain ``{name}`` placeholders, filled from ``params``.
 * Static markup is translated through attributes:
 *
 *   data-i18n="key"        → textContent
 *   data-i18n-html="key"   → innerHTML (trusted strings from our own locale files only)
 *   data-i18n-title="key"  → title
 *   data-i18n-alt="key"    → alt
 *   data-i18n-aria="key"   → aria-label
 *   data-i18n-placeholder="key" → placeholder
 *
 * The long explanation at the bottom of the page is a separate partial,
 * ``locales/how.<lang>.html``, because it is prose rather than labels.
 *
 * To add a language: copy ``en.json`` and ``how.en.html``, translate them and
 * add an entry to ``LANGUAGES`` below. The test suite checks the keys match.
 */

import { $, $$ } from "./dom.js";
import { store } from "./state.js";

export const LANGUAGES = {
  en: { label: "EN", name: "English", intl: "en-GB" },
  es: { label: "ES", name: "Español", intl: "es-ES" },
};
export const FALLBACK = "en";

let lang = FALLBACK;
let strings = {};
let fallback = {};
const listeners = new Set();

export const currentLang = () => lang;

/** Translate ``key``, substituting ``{placeholders}`` from ``params``. */
export function t(key, params = {}) {
  let s = strings[key] ?? fallback[key];
  if (s === undefined) {
    console.warn(`[i18n] missing key: ${key}`);
    return key;
  }
  return s.replace(/\{(\w+)\}/g, (m, name) => (name in params ? String(params[name]) : m));
}

/** True if a translation exists (used for optional, code-driven keys). */
export const has = (key) => key in strings || key in fallback;

/** Locale-aware number formatting. */
export function num(n, opts = {}) {
  return Number(n).toLocaleString(LANGUAGES[lang].intl, opts);
}
export const int = (n) => num(Math.round(n));
export const fixed = (n, digits) => num(n, { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Pick the initial language: the user's explicit choice, otherwise English.
 * (Stored under a new key: the old ``lang`` key also held auto-detected values.) */
export function detectLanguage() {
  const saved = store.get("language", null);
  return saved && saved in LANGUAGES ? saved : FALLBACK;
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

/** Translate every annotated element under ``root``. */
export function applyTranslations(root = document) {
  for (const el of $$("[data-i18n]", root)) el.textContent = t(el.dataset.i18n);
  for (const el of $$("[data-i18n-html]", root)) el.innerHTML = t(el.dataset.i18nHtml);
  for (const el of $$("[data-i18n-title]", root)) el.title = t(el.dataset.i18nTitle);
  for (const el of $$("[data-i18n-alt]", root)) el.alt = t(el.dataset.i18nAlt);
  for (const el of $$("[data-i18n-aria]", root)) el.setAttribute("aria-label", t(el.dataset.i18nAria));
  for (const el of $$("[data-i18n-placeholder]", root)) el.placeholder = t(el.dataset.i18nPlaceholder);
}

async function loadExplanation(code) {
  const host = $("#how-content");
  if (!host) return;
  try {
    const res = await fetch(`locales/how.${code}.html`);
    if (!res.ok) throw new Error(res.status);
    host.innerHTML = await res.text();
  } catch (_) {
    if (code !== FALLBACK) return loadExplanation(FALLBACK);
  }
}

/** Switch language, re-translate the page and notify listeners. */
export async function setLanguage(code) {
  if (!(code in LANGUAGES)) code = FALLBACK;
  const [dict, base] = await Promise.all([
    fetchJSON(`locales/${code}.json`),
    code === FALLBACK ? null : fetchJSON(`locales/${FALLBACK}.json`).catch(() => ({})),
  ]);
  strings = dict;
  fallback = base || dict;
  lang = code;
  document.documentElement.lang = code;
  document.title = t("app.title");
  $('meta[name="description"]')?.setAttribute("content", t("app.description"));
  applyTranslations();
  await loadExplanation(code);
  renderSwitcher();
  for (const fn of listeners) fn(code);
}

/** Register a callback run after every language change (to redraw dynamic text). */
export const onLanguageChange = (fn) => listeners.add(fn);

function renderSwitcher() {
  const host = $("#lang");
  if (!host) return;
  host.setAttribute("aria-label", t("header.language"));
  host.innerHTML = "";
  for (const [code, info] of Object.entries(LANGUAGES)) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = info.label;
    b.title = info.name;
    b.lang = code;
    b.className = code === lang ? "on" : "";
    b.setAttribute("aria-pressed", String(code === lang));
    b.onclick = () => {
      if (code === lang) return;
      store.set("language", code);
      setLanguage(code);
    };
    host.appendChild(b);
  }
}
