/**
 * Sending to the tag and following the upload.
 *
 * Server Bluetooth: the backend runs the transfer and keeps a log, which this
 * module polls. This device: ``webble.js`` runs it in the page. Both produce
 * the same job views, rendered here in the current language
 * (``job.note.<code>`` and ``error.<code>`` keys).
 */

import { api } from "./api.js";
import { $, $$, esc } from "./dom.js";
import { has, int, num, t } from "./i18n.js";
import { S, store } from "./state.js";
import { updateStick } from "./render.js";
import { errorText, flash, flashError } from "./status.js";
import { rememberWebId } from "./devices.js";
import { chooseDevice, digest, findGranted, fromBase64, LocalJob, transfer as webTransfer, webStatus } from "./webble.js";

const PHASES = ["scan", "connect", "gatt", "handshake", "blocks", "refresh"];
const LOG_LIMIT = 300;

function busy(on) {
  $("#send").disabled = on;
  document.querySelectorAll(".design .send").forEach((b) => { b.disabled = on; });
}

/** Send the current image to the selected tag. Call from a click handler. */
export async function send(force = false) {
  if (!S.id) return;
  if (!S.tag) { flash("status.pick_tag", "err"); return; }
  if (!S.tag.known) { flash("status.pick_model", "err"); return; }
  if (!S.tag.supported) { flash("status.unsupported", "err"); return; }
  return S.tag.transport === "web" ? sendFromBrowser(force) : sendFromServer(force);
}

async function sendFromServer(force) {
  busy(true);
  flash("status.preparing", "busy");
  try {
    const res = await api.send({ id: S.id, address: S.tag.address, model: S.tag.model_id, params: S.p, force });
    if (res.duplicate) {
      busy(false);
      flash("");
      if (confirm(t("confirm.duplicate"))) send(true);
      return;
    }
    flash("");
    open(res.job);
    poll();
  } catch (err) {
    busy(false);
    flashError(err);
  }
}

async function sendFromBrowser(force) {
  const status = webStatus();
  if (status !== "ok") { flash(`tags.web_${status}`, "err"); return; }
  let tag = S.tag;
  busy(true);
  try {
    // Ask for the device first, while the click still counts as a user gesture.
    let device = await findGranted(tag.address);
    if (!device) {
      flash("status.choose_again", "busy");
      device = await chooseDevice();
      tag = await rememberWebId(tag, device);
    }
    flash("status.preparing", "busy");
    const packed = await api.packed(S.id, { ...S.p, view: "pure", model: tag.model_id, width: tag.width, height: tag.height });
    if (packed.stats.unsupported) throw packed.stats.unsupported;
    const data = fromBase64(packed.data);
    const hash = await digest(data);
    const sentKey = `sent:${tag.key || tag.address}`;
    if (!force && store.get(sentKey, null) === hash) {
      busy(false);
      flash("");
      if (confirm(t("confirm.duplicate"))) send(true);
      return;
    }
    flash("");
    const job = new LocalJob(data.length);
    open(job.id, job);
    let seen = 0;
    job.listeners.add(() => {
      const v = job.view(seen);
      seen = v.log_len;
      update(v);
    });
    await webTransfer(device, data, job);
    if (job.status === "ok") store.set(sentKey, hash);
  } catch (err) {
    busy(false);
    if (err.code !== "web_cancelled") flashError(err);
    else flash("");
  }
}

function open(jobId, local = null) {
  const card = $("#xfer");
  card.classList.remove("hidden", "ok", "err");
  $("#xlog").innerHTML = "";
  $("#pfill").style.width = "0";
  S.job = { id: jobId, local, seen: 0, entries: [], view: null, tagName: S.tag.name, finished: false };
  paintHeader();
  updateStick();
  card.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function poll() {
  const job = S.job;
  if (!job || job.local) return;
  try {
    const v = await api.job(job.id, job.seen);
    if (S.job !== job) return;
    job.seen = v.log_len;
    update(v);
    if (v.status === "running") setTimeout(poll, 250);
  } catch (err) {
    busy(false);
    flash("status.lost_track", "err", { detail: errorText(err) });
  }
}

/** Apply a job view (with only the new log entries). */
function update(v) {
  const job = S.job;
  job.view = v;
  job.entries.push(...v.log);
  if (job.entries.length > LOG_LIMIT) job.entries.splice(0, job.entries.length - LOG_LIMIT);
  paintJob(v.log);
  if (v.status !== "running" && !job.finished) {
    job.finished = true;
    busy(false);
    if (v.status === "ok") flash("status.sent", "ok", { seconds: num(v.elapsed) });
    else flashError(v.error);
  }
}

/** Text of one note entry. Error notes reuse the ``error.*`` strings. */
function noteText(e) {
  if (e.code === "error") {
    const { code, ...params } = e.params;
    return errorText({ code, params });
  }
  const key = `job.note.${e.code}`;
  const params = Object.fromEntries(Object.entries(e.params).map(([k, v]) => [k, typeof v === "number" ? int(v) : v]));
  return has(key) ? t(key, params) : e.code;
}

function entryRow(e) {
  const row = document.createElement("div");
  const time = `<span class="t">${(e.t / 1000).toFixed(2)} s</span>`;
  row.innerHTML = e.kind === "note"
    ? time + `<span class="note">${esc(noteText(e))}</span>`
    : time + `<span class="${e.kind}">${e.kind === "tx" ? "→" : "←"} ${esc(e.hex)}</span> <span class="ch">${esc(e.char)} · ${e.len} B</span>`;
  return row;
}

function paintHeader() {
  const job = S.job, v = job.view;
  const via = t(job.local ? "transfer.via_web" : "transfer.via_server");
  const title = !v || v.status === "running" ? t("transfer.sending", { name: job.tagName })
    : v.status === "ok" ? t("transfer.sent") : t("transfer.failed");
  $("#xtitle").textContent = title;
  $("#xmeta").textContent = [
    via,
    v && (v.phase === "blocks" || v.status === "ok") ? t("transfer.block", { part: v.part, total: v.blocks }) : "",
    v?.mtu ? `MTU ${v.mtu}` : "",
    v?.attempt > 1 ? t("transfer.attempt", { n: v.attempt }) : "",
    v ? `${num(v.elapsed)} s` : "",
  ].filter(Boolean).join(" · ");
}

function paintJob(fresh) {
  const v = S.job.view;
  const card = $("#xfer");
  const now = v.status === "ok" ? PHASES.length : Math.max(0, PHASES.indexOf(v.phase));
  $$("#phases li").forEach((li, i) => {
    li.classList.toggle("done", i < now);
    li.classList.toggle("now", i === now && v.status !== "ok");
  });
  const blockShare = v.blocks ? v.part / v.blocks : 0;
  const share = v.status === "ok" ? 1
    : v.phase === "blocks" || v.phase === "refresh" ? 0.12 + 0.88 * blockShare
    : (now / PHASES.length) * 0.5;
  $("#pfill").style.width = Math.round(share * 100) + "%";
  card.classList.toggle("ok", v.status === "ok");
  card.classList.toggle("err", v.status === "error");
  paintHeader();

  const log = $("#xlog");
  for (const e of fresh) log.appendChild(entryRow(e));
  while (log.children.length > LOG_LIMIT) log.firstChild.remove();
  if (fresh.length) log.scrollTop = log.scrollHeight;
}

/** Redraw the whole card in the current language. */
export function repaintTransfer() {
  if (!S.job) return;
  paintHeader();
  const log = $("#xlog");
  log.innerHTML = "";
  for (const e of S.job.entries) log.appendChild(entryRow(e));
  log.scrollTop = log.scrollHeight;
}
