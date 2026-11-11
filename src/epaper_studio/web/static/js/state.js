/** Application state, defaults and the per-browser preference store. */

/** Pigment colours as sent (``PURE``) and as they look on the panel (``INK``). */
export const PURE = { white: "#FFFFFF", black: "#000000", red: "#FF0000", yellow: "#FFFF00" };
export const INK = { white: "#E8E7DE", black: "#222226", red: "#B02428", yellow: "#DCB820" };

/** Defaults mirror ``epaper_studio.imaging.params.Params``. */
export const DEFAULTS = Object.freeze({
  width: 400, height: 300,
  fit: "cover", zoom: 1, pan_x: 0, pan_y: 0, rotate: 0, flip: false, background: "white",
  auto_levels: false, brightness: 0, contrast: 1, gamma: 1, sharpen: 0,
  saturation: 1, hue: 0, color_weight: 3, color_bias: 0,
  palette: "bwr", dither: "floyd", strength: 1, serpentine: true, compress_range: true,
  view: "pure", model: null,
});

/** Parameters a preset must not touch: they describe the panel and the framing. */
export const FRAMING = ["width", "height", "fit", "zoom", "pan_x", "pan_y", "rotate", "flip",
  "background", "view", "model", "palette"];

export const S = {
  id: null,            // image id on the server
  srcImg: null, srcName: "", srcW: 0, srcH: 0,
  p: { ...DEFAULTS },  // current parameters
  stats: null,         // stats of the last render
  rendered: null,      // parameters of the last render
  zoom: 2,             // requested on-screen zoom
  ez: 2,               // effective zoom after fitting the column
  source: "server",    // whose Bluetooth sends: "server" or "web" (this device)
  models: {},          // "0x004B" -> {name, width, height, palette, supported}
  devices: [],         // saved devices (names, groups, models), from the server
  found: [],           // server scan results
  tag: null,           // the selected tag (see devices.js: describe())
  designs: [],         // saved designs
  design: null,        // the saved design currently open, if any
  job: null,           // upload being followed
  bleError: null,      // {code, params} when Bluetooth is unavailable
  status: null,        // last status message, kept so it can be re-translated
};

/** localStorage, tolerant of private windows and blocked storage. */
export const store = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem("eps:" + key);
      return v === null ? fallback : JSON.parse(v);
    } catch (_) {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem("eps:" + key, JSON.stringify(value));
    } catch (_) { /* storage unavailable: preferences are a convenience */ }
  },
};
