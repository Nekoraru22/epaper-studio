/**
 * "This device" Bluetooth: the Gicisky protocol spoken from the browser with
 * the Web Bluetooth API (Chrome/Edge on Android, Windows, macOS, Linux).
 *
 * It mirrors ``epaper_studio/gicisky/protocol.py`` and produces the same job
 * views and log entries, so the transfer card renders both the same way.
 * Web Bluetooth needs a secure context: HTTPS, or http://localhost.
 */

import { hex2 } from "./dom.js";

export const SERVICE = 0xfef0;
export const COMPANY = 0x5053;
const BLOCK = 240;
const REPLY_TIMEOUT = 5000;

class CodeError extends Error {
  constructor(code, params = {}) {
    super(code);
    this.code = code;
    this.params = params;
  }
}

/** "ok", "insecure" (needs HTTPS) or "unsupported" (browser lacks the API). */
export function webStatus() {
  if (!window.isSecureContext) return "insecure";
  if (!navigator.bluetooth?.requestDevice) return "unsupported";
  return "ok";
}

/** True if this browser can listen to adverts (where the model is). Chrome needs a flag for it. */
export function canReadAdverts() {
  return !!(window.BluetoothDevice && "watchAdvertisements" in window.BluetoothDevice.prototype);
}

/** Handles granted in this session, by device id. */
const granted = new Map();

/** Show the browser's chooser filtered to Gicisky tags. Must run inside a click handler. */
export async function chooseDevice() {
  try {
    const device = await navigator.bluetooth.requestDevice({
      filters: [{ manufacturerData: [{ companyIdentifier: COMPANY }] }, { namePrefix: "NEMR" }],
      optionalServices: [SERVICE],
      optionalManufacturerData: [COMPANY],
    });
    granted.set(device.id, device);
    return device;
  } catch (err) {
    if (err.name === "NotFoundError") throw new CodeError("web_cancelled");
    throw new CodeError("web_generic", { detail: err.message });
  }
}

/** A device this browser was allowed to use before, if the browser remembers it. */
export async function findGranted(id) {
  if (granted.has(id)) return granted.get(id);
  if (!navigator.bluetooth?.getDevices) return null;
  try {
    for (const d of await navigator.bluetooth.getDevices()) granted.set(d.id, d);
  } catch (_) { /* permission backend unavailable */ }
  return granted.get(id) || null;
}

/**
 * Listen for the tag's advert to learn its model. Not every browser offers
 * ``watchAdvertisements``; resolves to ``null`` when it is missing or silent.
 */
export async function readAdvert(device, timeout = 8000) {
  if (!device.watchAdvertisements) return null;
  return new Promise((resolve) => {
    const abort = new AbortController();
    const done = (value) => {
      clearTimeout(timer);
      device.removeEventListener("advertisementreceived", onAdvert);
      abort.abort();
      resolve(value);
    };
    const onAdvert = (ev) => {
      const view = ev.manufacturerData?.get(COMPANY);
      if (!view || view.byteLength !== 5) return;
      const bytes = [...new Uint8Array(view.buffer, view.byteOffset, view.byteLength)];
      done({ hex: bytes.map(hex2).join(""), rssi: ev.rssi ?? null });
    };
    const timer = setTimeout(() => done(null), timeout);
    device.addEventListener("advertisementreceived", onAdvert);
    device.watchAdvertisements({ signal: abort.signal }).catch(() => done(null));
  });
}

/** Same shape as ``Job.view()`` on the server. */
export class LocalJob {
  constructor(bytes) {
    this.id = "local";
    this.status = "running";
    this.phase = "scan";
    this.error = null;
    this.part = 0;
    this.blocks = Math.ceil(bytes / BLOCK);
    this.bytes = bytes;
    this.mtu = null;
    this.attempt = 1;
    this.started = performance.now();
    this.finished = null;
    this.log = [];
    this.listeners = new Set();
  }
  push(entry) {
    entry.t = Math.round(performance.now() - this.started);
    this.log.push(entry);
    for (const fn of this.listeners) fn(this);
  }
  note(code, params = {}) { this.push({ kind: "note", code, params }); }
  setPhase(phase, code, params = {}) { this.phase = phase; this.note(code, params); }
  frame(kind, char, data) {
    const hex = [...data.slice(0, 16)].map(hex2).join(" ") + (data.length > 16 ? " …" : "");
    this.push({ kind, char, len: data.length, hex });
  }
  finish(error = null) {
    this.status = error ? "error" : "ok";
    this.error = error;
    this.finished = performance.now();
    if (error) this.phase = "error";
    for (const fn of this.listeners) fn(this);
  }
  view(since = 0) {
    return {
      id: this.id, status: this.status, phase: this.phase, error: this.error, part: this.part,
      blocks: this.blocks, bytes: this.bytes, mtu: this.mtu, attempt: this.attempt,
      elapsed: Math.round(((this.finished ?? performance.now()) - this.started) / 100) / 10,
      log: this.log.slice(since), log_len: this.log.length,
    };
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const u32 = (v) => [v & 255, (v >> 8) & 255, (v >> 16) & 255, (v >>> 24) & 255];
const short = (uuid) => uuid.slice(4, 8);

function withTimeout(promise, ms, code, params) {
  let timer;
  return Promise.race([
    promise.finally(() => clearTimeout(timer)),
    new Promise((_, reject) => { timer = setTimeout(() => reject(new CodeError(code, params)), ms); }),
  ]);
}

class Link {
  constructor(cmd, img, job) {
    this.cmd = cmd;
    this.img = img;
    this.job = job;
    this.queue = [];
    this.waiter = null;
    this.onNotify = (ev) => {
      const v = ev.target.value;
      const data = new Uint8Array(v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength));
      if (this.waiter) { const w = this.waiter; this.waiter = null; w(data); } else this.queue.push(data);
    };
  }
  async start() {
    this.cmd.addEventListener("characteristicvaluechanged", this.onNotify);
    await this.cmd.startNotifications();
    await sleep(1000); // the tag needs a moment after subscribing
  }
  async stop() {
    this.cmd.removeEventListener("characteristicvaluechanged", this.onNotify);
    try { await this.cmd.stopNotifications(); } catch (_) { /* already gone */ }
  }
  reply() {
    if (this.queue.length) return Promise.resolve(this.queue.shift());
    return withTimeout(new Promise((resolve) => { this.waiter = resolve; }), REPLY_TIMEOUT, "tag_silent");
  }
  async request(char, payload, quiet = false) {
    this.queue.length = 0;
    const name = char === this.cmd ? "fef1" : "fef2";
    if (!quiet) this.job.frame("tx", name, payload);
    await char.writeValueWithoutResponse(payload);
    const data = await this.reply();
    if (!quiet) this.job.frame("rx", "fef1", data);
    return data;
  }
  async send(data) {
    const job = this.job;
    const hex = (r) => [...r].map(hex2).join(" ");
    job.setPhase("handshake", "cmd_start");
    let r = await this.request(this.cmd, new Uint8Array([0x01]));
    if (r.length < 3 || r[0] !== 0x01 || r[1] !== 0xf4 || r[2] !== 0x00) {
      throw new CodeError("unexpected_reply", { command: "0x01", reply: hex(r) });
    }
    job.setPhase("handshake", "cmd_size", { bytes: data.length });
    r = await this.request(this.cmd, new Uint8Array([0x02, ...u32(data.length), 0, 0, 0]));
    if (!r.length || r[0] !== 0x02) throw new CodeError("unexpected_reply", { command: "0x02", reply: hex(r) });
    job.setPhase("handshake", "cmd_ready");
    r = await this.request(this.cmd, new Uint8Array([0x03]));
    if (r.length < 6 || r[0] !== 0x05 || r[1] !== 0x00) {
      throw new CodeError("unexpected_reply", { command: "0x03", reply: hex(r) });
    }
    job.setPhase("blocks", "blocks_start");
    let part = 0, last = -1, repeats = 0;
    while (part * BLOCK < data.length) {
      const quiet = part >= 3 && part < job.blocks - 1;
      const chunk = data.subarray(part * BLOCK, (part + 1) * BLOCK);
      const packet = new Uint8Array(4 + chunk.length);
      packet.set(u32(part));
      packet.set(chunk, 4);
      r = await this.request(this.img, packet, quiet);
      if (r.length < 6 || r[0] !== 0x05 || r[1] !== 0x00) break; // the tag considers the image complete
      const asked = r[2] | (r[3] << 8) | (r[4] << 16) | (r[5] << 24);
      if (asked === last) {
        repeats += 1;
        job.note("block_repeat", { part: asked });
        if (repeats >= 3) throw new CodeError("stalled", { part: asked });
      } else {
        repeats = 1;
        last = asked;
      }
      part = asked;
      job.part = Math.min(part, job.blocks);
      if (quiet && part % 25 === 0) job.note("block_progress", { part, total: job.blocks });
    }
    job.part = job.blocks;
  }
}

function asCode(err) {
  if (err instanceof CodeError) return { code: err.code, params: err.params };
  const detail = err?.message || String(err);
  if (err?.name === "NetworkError" && /unsupported device|mtu/i.test(detail)) return { code: "web_mtu", params: { detail } };
  return { code: "web_generic", params: { detail } };
}

/** Upload ``data`` (Uint8Array) to ``device``. Never throws: the outcome is in ``job``. */
export async function transfer(device, data, job, attempts = 3) {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    job.attempt = attempt;
    let link = null;
    try {
      if (attempt > 1) {
        job.note("retry", { attempt, attempts });
        await sleep(1500);
      }
      job.setPhase("connect", "connecting");
      const server = await withTimeout(device.gatt.connect(), 25000, "tag_not_seen", { seconds: 25 });
      job.note("connected_web");
      job.setPhase("gatt", "finding_service");
      let service;
      try {
        service = await server.getPrimaryService(SERVICE);
      } catch (_) {
        throw new CodeError("no_service");
      }
      const chars = (await service.getCharacteristics()).sort((a, b) => a.uuid.localeCompare(b.uuid));
      const cmd = chars.find((c) => short(c.uuid) === "fef1") || chars[0];
      const img = chars.find((c) => short(c.uuid) === "fef2") || chars[1];
      if (!cmd || !img) throw new CodeError("no_service");
      job.note("characteristics", { cmd: short(cmd.uuid), img: short(img.uuid) });
      link = new Link(cmd, img, job);
      await link.start();
      await link.send(data);
      job.setPhase("refresh", "delivered");
      await link.stop();
      device.gatt.disconnect();
      job.finish();
      return;
    } catch (err) {
      if (link) await link.stop();
      try { device.gatt.disconnect(); } catch (_) { /* not connected */ }
      const error = asCode(err);
      job.note("error", error.params ? { code: error.code, ...error.params } : { code: error.code });
      const retry = ["tag_silent", "tag_not_seen", "web_generic"].includes(error.code);
      if (!retry || attempt === attempts) {
        job.finish(error);
        return;
      }
    }
  }
}

/** SHA-1 of the buffer, to warn before re-sending the same image. */
export async function digest(data) {
  const hash = await crypto.subtle.digest("SHA-1", data);
  return [...new Uint8Array(hash)].map(hex2).join("");
}

export function fromBase64(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
