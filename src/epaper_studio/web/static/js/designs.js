/**
 * Saved designs: an image together with all its adjustments, kept on the
 * server so it can be reopened, tweaked or re-sent in one tap.
 */

import { api } from "./api.js";
import { $, esc } from "./dom.js";
import { t } from "./i18n.js";
import { DEFAULTS, S } from "./state.js";
import { syncControls } from "./controls.js";
import { drawThumb, layoutPreview, schedule, showSource } from "./render.js";
import { flash, flashError } from "./status.js";
import { send } from "./transfer.js";

const ICONS = {
  send: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 8 14 2l-3 12-3-5z M8 9l6-7" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>`,
  rename: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M11.2 2.3a1.6 1.6 0 0 1 2.3 2.3l-8 8-3 .7.7-3z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>`,
  delete: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>`,
};

export async function loadDesigns() {
  try {
    S.designs = await api.designs();
  } catch (err) {
    flashError(err);
  }
  renderDesigns();
}

export function renderDesigns() {
  $("#dsave").disabled = !S.id;
  const update = $("#dupdate");
  update.classList.toggle("hidden", !S.design || !S.id);
  if (S.design) update.title = t("designs.update_title", { name: S.design.name });

  const host = $("#designs");
  host.innerHTML = "";
  if (!S.designs.length) {
    host.innerHTML = `<p class="blank">${esc(t("designs.empty"))}</p>`;
    return;
  }
  for (const d of S.designs) {
    const card = document.createElement("div");
    card.className = "design" + (S.design?.id === d.id ? " on" : "");
    card.innerHTML = `
      <button type="button" class="open" title="${esc(t("designs.open"))}">
        <img alt="" loading="lazy" src="${api.thumbUrl(d)}"><span>${esc(d.name)}</span>
      </button>
      <div class="acts">
        <button type="button" class="send" title="${esc(t("designs.send"))}" aria-label="${esc(t("designs.send"))}">${ICONS.send}</button>
        <button type="button" class="rename" title="${esc(t("designs.rename"))}" aria-label="${esc(t("designs.rename"))}">${ICONS.rename}</button>
        <button type="button" class="delete" title="${esc(t("designs.delete"))}" aria-label="${esc(t("designs.delete"))}">${ICONS.delete}</button>
      </div>`;
    card.querySelector(".open").onclick = () => openDesign(d);
    card.querySelector(".send").onclick = () => quickSend(d);
    card.querySelector(".rename").onclick = () => rename(d);
    card.querySelector(".delete").onclick = () => remove(d);
    host.appendChild(card);
  }
}

/** Ask for a name in the small dialog. Resolves to the text, or null if cancelled. */
function askName(title, value) {
  const dlg = $("#namedialog");
  const form = dlg.querySelector("form");
  $("#nametitle").textContent = title;
  form.elements.name.value = value;
  return new Promise((resolve) => {
    form.onsubmit = (ev) => { ev.preventDefault(); dlg.close(); resolve(form.elements.name.value.trim()); };
    dlg.querySelector("[data-close]").onclick = () => { dlg.close(); resolve(null); };
    dlg.oncancel = () => resolve(null);
    dlg.showModal();
    form.elements.name.select();
  });
}

const storedParams = () => ({ ...S.p, view: "pure" });

export async function saveNew() {
  if (!S.id) return;
  const base = S.design?.name || S.srcName.replace(/\.[^.]+$/, "") || "";
  const name = await askName(t("designs.save_title"), base);
  if (name === null) return;
  try {
    const d = await api.createDesign({ image: S.id, name, params: storedParams() });
    S.designs = [d, ...S.designs];
    S.design = { id: d.id, name: d.name };
    renderDesigns();
    flash("status.design_saved", "ok", { name: d.name });
  } catch (err) {
    flashError(err);
  }
}

export async function updateCurrent() {
  if (!S.design || !S.id) return;
  try {
    const body = { params: storedParams() };
    if (S.design.image !== S.id) body.image = S.id; // the image itself was replaced
    const d = await api.updateDesign(S.design.id, body);
    S.designs = [d, ...S.designs.filter((x) => x.id !== d.id)];
    S.design = { id: d.id, name: d.name, image: S.id };
    renderDesigns();
    flash("status.design_updated", "ok", { name: d.name });
  } catch (err) {
    flashError(err);
  }
}

/** Load a design into the editor. */
export async function openDesign(d) {
  flash("status.opening", "busy");
  try {
    const { image, design } = await api.openDesign(d.id);
    const keep = S.tag?.known ? { width: S.tag.width, height: S.tag.height, model: S.tag.model_id } : {};
    S.p = { ...DEFAULTS, ...design.params, ...keep, view: S.p.view };
    if (S.tag?.known && S.tag.palette !== "bw" && S.p.palette !== "bw") S.p.palette = S.tag.palette;
    if (!S.tag?.known) {
      const size = `${S.p.width}x${S.p.height}`;
      if ([...$("#panel").options].some((o) => o.value === size)) $("#panel").value = size;
    }
    S.design = { id: design.id, name: design.name, image: image.id };
    showSource(image, design.name, api.sourceUrl(design));
    syncControls();
    layoutPreview();
    drawThumb();
    flash("");
    renderDesigns();
    schedule(0);
  } catch (err) {
    flashError(err);
  }
}

async function quickSend(d) {
  if (!S.tag) { flash("status.pick_tag", "err"); return; }
  // Web Bluetooth needs the tap to still count as a user gesture when the
  // device chooser opens, so the design is loaded first and sent right after.
  await openDesign(d);
  send(false);
}

async function rename(d) {
  const name = await askName(t("designs.rename_title"), d.name);
  if (!name || name === d.name) return;
  try {
    const fresh = await api.updateDesign(d.id, { name });
    S.designs = S.designs.map((x) => (x.id === d.id ? fresh : x));
    if (S.design?.id === d.id) S.design.name = fresh.name;
    renderDesigns();
  } catch (err) {
    flashError(err);
  }
}

async function remove(d) {
  if (!confirm(t("designs.confirm_delete", { name: d.name }))) return;
  try {
    await api.deleteDesign(d.id);
    S.designs = S.designs.filter((x) => x.id !== d.id);
    if (S.design?.id === d.id) S.design = null;
    renderDesigns();
  } catch (err) {
    flashError(err);
  }
}
