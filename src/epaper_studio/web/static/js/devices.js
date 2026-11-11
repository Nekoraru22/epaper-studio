/**
 * Tags: choosing whose Bluetooth to use, finding tags, naming and grouping
 * them, and selecting the one to send to.
 *
 * Two sources:
 *   "server" — the adapter of the machine running E-Paper Studio (scan from the server)
 *   "web"    — the Bluetooth of the device showing this page (Web Bluetooth)
 *
 * Saved devices (name, group, model) live on the server, so they show up on
 * every browser. A tag in the list is described by ``describe()``.
 */

import { api } from "./api.js";
import { $, esc, modelHex } from "./dom.js";
import { fixed, t } from "./i18n.js";
import { S, store } from "./state.js";
import { syncControls } from "./controls.js";
import { layoutPreview, schedule } from "./render.js";
import { showAdvert } from "./stats.js";
import { errorText, flash, flashError } from "./status.js";
import { canReadAdverts, chooseDevice, findGranted, readAdvert, webStatus } from "./webble.js";

let scanning = false;
let message = { key: "tags.empty" }; // shown when the list is empty: {key, params} or {error}

// -- describing tags -----------------------------------------------------------

/** Model details for a model id, from the server's table. */
export function modelInfo(id) {
  const m = id == null ? null : S.models[modelHex(id)];
  if (!m) return { known: false, supported: false };
  return { known: true, supported: m.supported, model: m.name, width: m.width, height: m.height, palette: m.palette };
}

/** One tag as the UI sees it: saved record + scan result + model details. */
export function describe(record, seen = null) {
  const modelId = record?.model_id ?? seen?.model_id ?? null;
  return {
    key: record?.key || null,
    transport: record?.transport || "server",
    address: record?.address || seen.address,
    name: record?.name || seen?.name || seen?.address,
    group: record?.group || "",
    ble_name: record?.ble_name || seen?.name || "",
    saved: !!record,
    model_id: modelId,
    ...modelInfo(modelId),
    rssi: seen?.rssi ?? null, volts: seen?.volts ?? null,
    raw: seen?.raw, firmware: seen?.firmware, hardware: seen?.hardware,
  };
}

function entries() {
  const saved = S.devices.filter((d) => d.transport === S.source);
  const list = saved.map((d) => describe(d, S.source === "server" ? S.found.find((f) => f.address === d.address) : null));
  if (S.source === "server") {
    for (const f of S.found) if (!saved.some((d) => d.address === f.address)) list.push(describe(null, f));
  }
  return list;
}

// -- rendering -------------------------------------------------------------------

function signal(tag) {
  if (tag.rssi == null) return "";
  const lit = tag.rssi >= -60 ? 4 : tag.rssi >= -70 ? 3 : tag.rssi >= -80 ? 2 : 1;
  const bars = [4, 6, 8, 11].map((h, i) => `<i style="height:${h}px" class="${i < lit ? "lit" : ""}"></i>`).join("");
  return `<span class="bars">${bars}</span>${tag.rssi} dBm`;
}

const PENCIL = `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M11.2 2.3a1.6 1.6 0 0 1 2.3 2.3l-8 8-3 .7.7-3z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>`;

function row(tag) {
  const wrap = document.createElement("div");
  const selected = S.tag && S.tag.transport === tag.transport && S.tag.address === tag.address;
  wrap.className = "tagrow" + (selected ? " on" : "") + (tag.known && tag.supported ? "" : " off");
  const model = tag.known ? tag.model : tag.model_id != null
    ? t("tags.unknown_model", { id: modelHex(tag.model_id) }) : t("tags.model_missing");
  const extra = tag.known && !tag.supported ? " · " + t("tags.unsupported") : "";
  const where = tag.transport === "web" ? (tag.ble_name && tag.ble_name !== tag.name ? tag.ble_name : "") : tag.address;
  const side = [signal(tag), tag.volts != null ? `<span>${fixed(tag.volts, 1)} V</span>` : "",
    tag.saved ? "" : `<span class="new">${esc(t("tags.new"))}</span>`].join("");
  wrap.innerHTML = `
    <button type="button" class="pick" title="${esc(tag.name)}">
      <span class="mini"></span><b>${esc(tag.name)}</b>
      <span class="sig">${side}</span>
      <small>${esc(model + extra)}${where ? " · " + esc(where) : ""}</small>
    </button>
    <button type="button" class="edit" title="${esc(t("tags.edit"))}" aria-label="${esc(t("tags.edit"))}">${PENCIL}</button>`;
  wrap.querySelector(".pick").onclick = () => pickTag(tag);
  wrap.querySelector(".edit").onclick = () => editDevice(tag);
  return wrap;
}

export function renderTags() {
  // Source switch and the action button
  for (const b of document.querySelectorAll("#source-seg button")) {
    b.classList.toggle("on", b.dataset.src === S.source);
  }
  const btn = $("#scan");
  btn.textContent = scanning ? t("tags.scanning") : t(S.source === "web" ? "tags.add" : "tags.scan");
  const web = webStatus();
  btn.disabled = scanning || (S.source === "web" && web !== "ok");
  const note = $("#srcnote");
  const noteKey = S.source === "web" && web !== "ok" ? `tags.web_${web}` : "";
  note.textContent = noteKey ? t(noteKey) : "";
  note.classList.toggle("hidden", !noteKey);

  const host = $("#tags");
  host.innerHTML = "";
  const list = entries();
  if (!list.length) {
    const text = message.error ? errorText(message.error)
      : t(S.source === "web" && message.key === "tags.empty" ? "tags.empty_web" : message.key, message.params);
    host.innerHTML = `<p class="blank">${esc(text)}</p>`;
    return;
  }
  const groups = new Map();
  for (const tag of list) {
    const g = tag.group || "";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(tag);
  }
  const named = [...groups.keys()].filter(Boolean).sort((a, b) => a.localeCompare(b));
  for (const g of [...named, ...(groups.has("") ? [""] : [])]) {
    if (named.length) {
      const h = document.createElement("div");
      h.className = "taggroup";
      h.textContent = g || t("tags.no_group");
      host.appendChild(h);
    }
    for (const tag of groups.get(g)) host.appendChild(row(tag));
  }
  datalist();
}

function datalist() {
  const groups = [...new Set(S.devices.map((d) => d.group).filter(Boolean))].sort();
  $("#groups").innerHTML = groups.map((g) => `<option value="${esc(g)}"></option>`).join("");
}

export function setMessage(key, params = {}) {
  message = { key, params };
  renderTags();
}

// -- actions ---------------------------------------------------------------------

export async function loadDevices() {
  try {
    S.devices = await api.devices();
  } catch (err) {
    flashError(err);
  }
  renderTags();
}

export function setSource(source) {
  S.source = source;
  store.set("source", source);
  message = { key: "tags.empty" };
  const last = store.get(`tag:${source}`, null);
  const record = last && S.devices.find((d) => d.key === last);
  if (record) pickTag(describe(record), { quiet: true });
  else S.tag = S.tag?.transport === source ? S.tag : null;
  renderTags();
}

/** The Scan / Add button. */
export async function findTags() {
  if (S.source === "web") return addWebDevice();
  scanning = true;
  setMessage("tags.listening", { seconds: 6 });
  try {
    S.found = await api.scan(6);
    message = S.found.length ? { key: "tags.empty" } : { key: "tags.none_found" };
    if (!S.tag || S.tag.transport !== "server") {
      const first = S.found.find((f) => modelInfo(f.model_id).supported) || S.found[0];
      if (first) pickTag(describe(S.devices.find((d) => d.address === first.address && d.transport === "server"), first));
    } else {
      const seen = S.found.find((f) => f.address === S.tag.address);
      if (seen) S.tag = describe(S.devices.find((d) => d.key === S.tag.key), seen);
      if (seen) showAdvert(S.tag);
    }
  } catch (err) {
    message = { error: err };
  } finally {
    scanning = false;
    renderTags();
  }
}

/** Pair a tag with this device's Bluetooth and remember it. */
async function addWebDevice() {
  let device;
  try {
    device = await chooseDevice();
  } catch (err) {
    if (err.code !== "web_cancelled") flashError(err);
    return;
  }
  scanning = true;
  setMessage("tags.reading_model");
  let info = null;
  const advert = await readAdvert(device);
  if (advert) {
    try { info = await api.advert(advert.hex); } catch (_) { /* fall back to asking */ }
  }
  scanning = false;
  const existing = S.devices.find((d) => d.transport === "web" && d.address === device.id);
  const record = await saveDevice({
    transport: "web", address: device.id, ble_name: device.name || "",
    name: existing?.name || "", group: existing?.group || "",
    model_id: info?.model_id ?? existing?.model_id ?? null,
  });
  if (!record) return;
  const tag = describe(record, info ? { ...info, address: device.id, name: device.name, rssi: advert.rssi } : null);
  message = { key: "tags.empty" };
  pickTag(tag);
  if (tag.model_id == null) editDevice(tag, { needModel: true });
}

async function saveDevice(body) {
  try {
    const record = await api.saveDevice(body);
    S.devices = [...S.devices.filter((d) => d.key !== record.key), record];
    return record;
  } catch (err) {
    flashError(err);
    return null;
  }
}

/** Make ``tag`` the destination and adapt the panel size and palette to it. */
export async function pickTag(tag, { quiet = false } = {}) {
  if (!tag) return;
  if (!tag.saved && tag.transport === "server") {
    const record = await saveDevice({ transport: "server", address: tag.address, ble_name: tag.ble_name, model_id: tag.model_id });
    if (record) tag = { ...tag, key: record.key, saved: true, name: record.name };
  }
  S.tag = tag;
  if (tag.key) store.set(`tag:${tag.transport}`, tag.key);
  renderTags();
  showAdvert(tag);
  if (!tag.known) return;
  S.p.model = tag.model_id;
  S.p.width = tag.width;
  S.p.height = tag.height;
  const size = `${tag.width}x${tag.height}`;
  const panel = $("#panel");
  if ([...panel.options].some((o) => o.value === size)) panel.value = size;
  if (S.p.palette !== "bw" || tag.palette === "bw") S.p.palette = tag.palette;
  syncControls();
  layoutPreview();
  if (!quiet) schedule(0);
}

/** Replace a web device's id after the browser handed out a new one. */
export async function rememberWebId(tag, device) {
  if (device.id === tag.address) return tag;
  const record = await saveDevice({ transport: "web", address: device.id, name: tag.name, group: tag.group,
    model_id: tag.model_id, ble_name: device.name || tag.ble_name });
  if (tag.key) await forget(tag.key, { silent: true });
  const fresh = { ...tag, key: record?.key, address: device.id };
  S.tag = fresh;
  if (fresh.key) store.set("tag:web", fresh.key);
  renderTags();
  return fresh;
}

async function forget(key, { silent = false } = {}) {
  try {
    await api.forgetDevice(key);
    S.devices = S.devices.filter((d) => d.key !== key);
  } catch (err) {
    if (!silent) flashError(err);
  }
}

// -- edit dialog -----------------------------------------------------------------

function fillModels(select, current) {
  const opts = Object.entries(S.models)
    .sort((a, b) => a[1].width * a[1].height - b[1].width * b[1].height)
    .map(([hex, m]) => `<option value="${parseInt(hex, 16)}">${esc(m.name)} · ${m.width}×${m.height}${m.supported ? "" : " · " + esc(t("tags.unsupported"))}</option>`);
  select.innerHTML = `<option value="">${esc(t("device.model_unknown"))}</option>` + opts.join("");
  select.value = current == null ? "" : String(current);
}

export function editDevice(tag, { needModel = false } = {}) {
  const dlg = $("#devdialog");
  const form = dlg.querySelector("form");
  form.elements.name.value = tag.saved ? tag.name : "";
  form.elements.name.placeholder = tag.ble_name || tag.address;
  form.elements.group.value = tag.group || "";
  fillModels(form.elements.model, tag.model_id);
  $("#devinfo").textContent = [
    t(tag.transport === "web" ? "device.via_web" : "device.via_server"),
    tag.transport === "server" ? tag.address : tag.ble_name,
  ].filter(Boolean).join(" · ");
  const web = tag.transport === "web";
  const canListen = canReadAdverts();
  const need = $("#devneed");
  need.textContent = needModel ? t(canListen ? "device.need_model_silent" : "device.need_model") : "";
  need.classList.toggle("hidden", !needModel);
  $("#devflag").classList.toggle("hidden", !web || canListen);
  wireDetect(tag, form.elements.model, web, canListen);
  $("#devforget").classList.toggle("hidden", !tag.saved);
  $("#devforget").onclick = async () => {
    dlg.close();
    if (tag.key) await forget(tag.key);
    if (S.tag?.key === tag.key) S.tag = null;
    renderTags();
  };
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const model = form.elements.model.value;
    const record = await saveDevice({
      transport: tag.transport, address: tag.address, ble_name: tag.ble_name,
      name: form.elements.name.value, group: form.elements.group.value,
      model_id: model === "" ? null : Number(model),
    });
    dlg.close();
    if (!record) return;
    flash("status.device_saved", "ok", { name: record.name });
    const seen = tag.rssi != null ? { ...tag, model_id: record.model_id, name: tag.ble_name } : null;
    const fresh = describe(record, seen);
    if (S.tag?.address === tag.address && S.tag?.transport === tag.transport) pickTag(fresh);
    else renderTags();
  };
  dlg.querySelector("[data-close]").onclick = () => dlg.close();
  dlg.showModal();
  if (!needModel) form.elements.name.focus();
}

/** The "Detect model" button: listen to the tag's advert again, for longer, and fill in the model. */
function wireDetect(tag, select, web, canListen) {
  const box = $("#devdetect");
  const btn = $("#devdetectbtn");
  const msg = $("#devdetectmsg");
  box.classList.toggle("hidden", !web);
  btn.disabled = !canListen;
  msg.textContent = "";
  msg.className = "";
  const say = (key, params = {}, kind = "") => { msg.textContent = t(key, params); msg.className = kind; };
  btn.onclick = async () => {
    btn.disabled = true;
    say("device.detecting", { seconds: 20 }, "busy");
    try {
      // Choosing again only works while the tap still counts as a user gesture, so try the remembered handle first.
      let device = await findGranted(tag.address);
      if (!device) device = await chooseDevice();
      const advert = await readAdvert(device, 20000);
      if (!advert) { say("device.detect_silent", {}, "err"); return; }
      const info = await api.advert(advert.hex);
      if (info.known) {
        select.value = String(info.model_id);
        say("device.detected", { model: info.model }, "ok");
      } else {
        say("device.detect_unknown", { id: modelHex(info.model_id) }, "err");
      }
    } catch (err) {
      if (err.code === "web_cancelled") msg.textContent = "";
      else { msg.textContent = errorText(err); msg.className = "err"; }
    } finally {
      btn.disabled = false;
    }
  };
}
