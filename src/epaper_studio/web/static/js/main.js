/** Entry point: builds the UI, wires events and loads the configuration. */

import { api } from "./api.js";
import { buildControls, buildPresets, syncControls } from "./controls.js";
import { loadDesigns, renderDesigns, saveNew, updateCurrent } from "./designs.js";
import { describe, findTags, loadDevices, pickTag, renderTags, setMessage, setSource } from "./devices.js";
import { $, $$ } from "./dom.js";
import { drawDump, wireDump } from "./dump.js";
import { detectLanguage, onLanguageChange, setLanguage } from "./i18n.js";
import { applyDragOffset, applyView, drawThumb, layoutPreview, loadFile, schedule, updateStick, wirePan } from "./render.js";
import { S, store } from "./state.js";
import { samplePixels, showAdvert, updateStats } from "./stats.js";
import { flash, paint as paintStatus } from "./status.js";
import { repaintTransfer, send } from "./transfer.js";

const NARROW = window.matchMedia("(max-width: 920px)");

function wire() {
  const drop = $("#drop"), file = $("#file");
  drop.onclick = () => file.click();
  drop.onkeydown = (ev) => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); file.click(); }
  };
  file.onchange = () => { loadFile(file.files[0]); file.value = ""; };
  for (const type of ["dragenter", "dragover"]) {
    document.addEventListener(type, (ev) => { ev.preventDefault(); drop.classList.add("over"); });
  }
  for (const type of ["dragleave", "drop"]) {
    document.addEventListener(type, (ev) => { ev.preventDefault(); drop.classList.remove("over"); });
  }
  document.addEventListener("drop", (ev) => {
    const f = ev.dataTransfer?.files[0];
    if (f) loadFile(f);
  });
  document.addEventListener("paste", (ev) => {
    const item = [...(ev.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (item) loadFile(item.getAsFile());
  });

  $("#panel").onchange = (ev) => {
    const [w, h] = ev.target.value.split("x").map(Number);
    S.p.width = w;
    S.p.height = h;
    store.set("panel", ev.target.value);
    layoutPreview();
    schedule(0);
  };
  $("#send").onclick = () => send(false);
  $("#scan").onclick = findTags;
  for (const b of $$("#source-seg button")) b.onclick = () => setSource(b.dataset.src);
  $("#dsave").onclick = saveNew;
  $("#dupdate").onclick = updateCurrent;
  $("#xclose").onclick = () => { $("#xfer").classList.add("hidden"); updateStick(); };

  for (const b of $$("#view button")) {
    b.onclick = () => {
      $$("#view button").forEach((x) => x.classList.toggle("on", x === b));
      S.p.view = b.dataset.v;
      schedule(0);
    };
  }
  for (const b of $$("#zoom button")) {
    b.onclick = () => {
      $$("#zoom button").forEach((x) => x.classList.toggle("on", x === b));
      S.zoom = Number(b.dataset.z);
      store.set("zoom", S.zoom);
      layoutPreview();
      applyDragOffset();
    };
  }
  window.addEventListener("resize", () => { drawThumb(); layoutPreview(); applyDragOffset(); });
}

/** Everything that is built from strings in code is redrawn on a language change. */
function retranslate() {
  buildControls();
  buildPresets();
  renderTags();
  renderDesigns();
  applyView();
  updateStats();
  samplePixels();
  if (S.tag) showAdvert(S.tag);
  repaintTransfer();
  paintStatus();
  drawDump();
}

async function boot() {
  await setLanguage(detectLanguage());
  onLanguageChange(retranslate);
  buildControls({ collapsed: NARROW.matches });
  buildPresets();
  wire();
  wirePan();
  wireDump();
  applyView();

  const panel = store.get("panel", "400x300");
  if ([...$("#panel").options].some((o) => o.value === panel)) {
    $("#panel").value = panel;
    [S.p.width, S.p.height] = panel.split("x").map(Number);
  }
  S.zoom = store.get("zoom", 2);
  $$("#zoom button").forEach((x) => x.classList.toggle("on", Number(x.dataset.z) === S.zoom));
  syncControls();
  layoutPreview();
  renderDesigns();

  try {
    const cfg = await api.config();
    S.bleError = cfg.ble_error;
    S.models = cfg.models;
    await Promise.all([loadDevices(), loadDesigns()]);
    setSource(store.get("source", "server") === "web" ? "web" : "server");
    if (!S.tag && cfg.tag_address && S.source === "server") {
      const configured = S.devices.find((d) => d.transport === "server" && d.address === cfg.tag_address);
      if (configured) pickTag(describe(configured), { quiet: true });
      else setMessage("tags.configured", { address: cfg.tag_address });
    }
    if (cfg.ble_error && S.source === "server") flash({ error: cfg.ble_error }, "err");
  } catch (_) {
    renderTags(); // the UI still works for previews
  }
}

boot();
