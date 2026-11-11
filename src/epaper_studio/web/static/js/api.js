/**
 * HTTP client for the backend.
 *
 * Failures throw an ``ApiError`` carrying the backend's translatable
 * ``code`` and ``params`` (see ``epaper_studio/errors.py``).
 */

export class ApiError extends Error {
  constructor(code, params = {}, status = 0, message = "") {
    super(message || code);
    this.code = code;
    this.params = params;
    this.status = status;
  }
}

async function failure(res) {
  const body = await res.json().catch(() => ({}));
  const d = body.detail;
  if (d && typeof d === "object" && !Array.isArray(d) && d.code) {
    return new ApiError(d.code, d.params || {}, res.status, d.message);
  }
  if (Array.isArray(d)) return new ApiError("invalid_request", {}, res.status, JSON.stringify(d));
  return new ApiError("http_error", { status: res.status }, res.status);
}

async function call(url, { method = "GET", json, body, headers = {}, signal } = {}) {
  let res;
  try {
    res = await fetch(url, {
      method, signal,
      headers: json !== undefined ? { "Content-Type": "application/json", ...headers } : headers,
      body: json !== undefined ? JSON.stringify(json) : body,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("network", {}, 0, err.message);
  }
  if (!res.ok) throw await failure(res);
  return res;
}

export const api = {
  config: async () => (await call("/api/config")).json(),
  scan: async (seconds = 6) => (await call(`/api/scan?seconds=${seconds}`)).json(),
  upload: async (file) => (await call("/api/image", {
    method: "POST", body: file, headers: { "Content-Type": file.type || "application/octet-stream" },
  })).json(),
  /** Returns ``{blob, stats}``. */
  render: async (id, params, signal) => {
    const res = await call("/api/render", { method: "POST", json: { id, params }, signal });
    return { stats: JSON.parse(res.headers.get("X-Stats") || "{}"), blob: await res.blob() };
  },
  packed: async (id, params, signal) =>
    (await call("/api/packed", { method: "POST", json: { id, params }, signal })).json(),
  send: async (body) => (await call("/api/send", { method: "POST", json: body })).json(),
  job: async (id, since) => (await call(`/api/jobs/${id}?since=${since}`)).json(),
  advert: async (hex) => (await call(`/api/advert?data=${hex}`)).json(),

  devices: async () => (await call("/api/devices")).json(),
  saveDevice: async (body) => (await call("/api/devices", { method: "POST", json: body })).json(),
  forgetDevice: async (key) => (await call(`/api/devices/${key}`, { method: "DELETE" })).json(),

  designs: async () => (await call("/api/designs")).json(),
  createDesign: async (body) => (await call("/api/designs", { method: "POST", json: body })).json(),
  updateDesign: async (id, body) => (await call(`/api/designs/${id}`, { method: "PATCH", json: body })).json(),
  deleteDesign: async (id) => (await call(`/api/designs/${id}`, { method: "DELETE" })).json(),
  openDesign: async (id) => (await call(`/api/designs/${id}/open`, { method: "POST" })).json(),
  importDesigns: async (file, mode) => (await call(`/api/designs/import?mode=${mode}`, {
    method: "POST", body: file, headers: { "Content-Type": "application/zip" },
  })).json(),
  thumbUrl: (d) => `/api/designs/${d.id}/thumb.png?v=${d.updated}`,
  sourceUrl: (d) => `/api/designs/${d.id}/source.png?v=${d.updated}`,
};
