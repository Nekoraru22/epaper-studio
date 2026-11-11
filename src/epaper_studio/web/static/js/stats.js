/**
 * Numbers around the preview: pigment coverage, timings, and the live values
 * in the explanation (which always describe the image you are editing).
 */

import { $, $$, esc, modelHex } from "./dom.js";
import { fixed, int, num, t } from "./i18n.js";
import { INK, PURE, S } from "./state.js";
import { errorText } from "./status.js";

export function updateStats() {
  const st = S.stats;
  if (!st) return;
  const names = Object.keys(st.coverage);
  $("#cover").innerHTML = names
    .map((n) => `<span style="width:${st.coverage[n] * 100}%;background:${INK[n]}"></span>`).join("");
  $("#legend").innerHTML = names.map((n) =>
    `<div><i style="background:${INK[n]}"></i>${esc(t(`pigment.${n}`))}<span class="mono">${fixed(st.coverage[n] * 100, 1)} %</span></div>`).join("");
  $("#timing").textContent = t("timing", { prepare: int(st.ms_prepare), quantize: int(st.ms_quantize) });

  const packets = $("#packets");
  if (st.unsupported) {
    if (packets) packets.innerHTML = `<div class="pkt"><span class="dat">${esc(errorText(st.unsupported))}</span></div>`;
    return;
  }
  const [W, H] = st.size, tr = st.transport;
  const live = {
    dims: `${W} × ${H}`, pixels: int(W * H),
    plane: int(st.planes[0].bytes), planes: String(st.planes.length),
    total: int(tr.total_bytes), packets: int(tr.packets), block: int(tr.block),
    pkt: String(tr.packet_bytes), minmtu: String(tr.min_mtu), sizehex: tr.size_packet,
    airtime: num(tr.airtime_s, { maximumFractionDigits: 1 }) + " s",
  };
  for (const el of $$("[data-live]")) {
    const v = live[el.dataset.live];
    if (v !== undefined) el.textContent = v;
  }
  if (!packets) return;
  packets.innerHTML = tr.sample.map((pk) => `
    <div class="pkt">
      <span class="att" title="${esc(t("packet.att"))}">ATT · 3 B</span>
      <span class="hdr" title="${esc(t("packet.header"))}">${pk.header}</span>
      <span class="dat">${pk.data}</span>
      <span class="more">${pk.more ? "+" + pk.more + " B" : ""}</span>
      <span class="rep" title="${esc(t("packet.reply"))}">← ${pk.reply}</span>
    </div>`).join("") +
    (tr.packets > 3
      ? `<div class="pkt"><span class="dat" style="color:var(--faint)">${esc(t("packet.more", { n: int(tr.packets - 3) }))}</span></div>`
      : "");
}

/** Nearest pigment for an RGB triple, against both colour tables. */
function classify(r, g, b) {
  let best = "white", bd = Infinity;
  for (const set of [PURE, INK]) {
    for (const [k, hex] of Object.entries(set)) {
      const R = parseInt(hex.slice(1, 3), 16), G = parseInt(hex.slice(3, 5), 16), B = parseInt(hex.slice(5, 7), 16);
      const d = (r - R) ** 2 + (g - G) ** 2 + (b - B) ** 2;
      if (d < bd) { bd = d; best = k; }
    }
  }
  return best;
}

/** Take 8 real pixels from the preview and show how they form one byte. */
export function samplePixels() {
  const img = $("#preview");
  if (!img.naturalWidth || !$("#pix")) return;
  const cv = document.createElement("canvas");
  cv.width = img.naturalWidth;
  cv.height = img.naturalHeight;
  const c = cv.getContext("2d", { willReadFrequently: true });
  c.drawImage(img, 0, 0);
  const W = cv.width, H = cv.height;
  const row = (x, y) => {
    const d = c.getImageData(x, y, 8, 1).data;
    return Array.from({ length: 8 }, (_, i) => classify(d[i * 4], d[i * 4 + 1], d[i * 4 + 2]));
  };
  // Look for a row with some ink in it so the example is interesting.
  let best = { x: Math.floor(W / 2) - 4, y: Math.floor(H / 2), score: -1 };
  for (let i = 0; i < 40; i++) {
    const x = Math.floor(W * 0.3), y = Math.floor(((i + 0.5) / 40) * H);
    const ink = row(x, y).filter((k) => k !== "white").length;
    const score = 4 - Math.abs(ink - 4);
    if (score > best.score) best = { x, y, score };
  }
  const cls = row(best.x, best.y);
  const bits = cls.map((k) => (k === "white" ? 1 : 0)); // black/white plane: 1 = white
  $("#pix").innerHTML = cls.map((k) => `<i style="background:${INK[k]}"></i>`).join("");
  $("#pixbits").innerHTML = bits.map((b) => `<span>${b}</span>`).join("");
  const v = bits.reduce((acc, b) => (acc << 1) | b, 0);
  $("#byteval").textContent = "0x" + v.toString(16).toUpperCase().padStart(2, "0") + "  ·  " + v.toString(2).padStart(8, "0");
}

/** Fill the "advertisement" step of the explanation with the selected tag. */
export function showAdvert(tag) {
  if (!tag || !$("#adv0")) return;
  const raw = tag.raw.split(" ");
  const id = modelHex(tag.model_id);
  $("#adv0").textContent = raw[0];
  $("#adv1").textContent = raw[1];
  $("#adv2").textContent = raw[2] + " " + raw[3];
  $("#adv4").textContent = raw[4];
  $("#advm").textContent = id;
  $("#advv").textContent = fixed(tag.volts, 1) + " V";
  $("#advf").textContent = tag.firmware;
  $("#advh").textContent = t("advert.hardware", { id: tag.hardware });
  $("#advwho").textContent = tag.name;
  $("#advmodel").textContent = tag.known
    ? t("advert.model_known", { id, model: tag.model, width: tag.width, height: tag.height })
    : t("advert.model_unknown", { id });
}
