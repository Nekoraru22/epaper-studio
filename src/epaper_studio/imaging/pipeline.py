"""From an uploaded picture to pigment indices: framing, tone and dithering."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from epaper_studio.imaging.color import PURE, oklab_to_rgb, rgb_to_oklab
from epaper_studio.imaging.dither import quantize
from epaper_studio.imaging.params import Params


@dataclass
class ImageResult:
    indices: np.ndarray          # (H, W) pigment index per pixel
    names: list[str]             # pigment names the indices refer to
    lab: np.ndarray              # (H, W, 3) image after tone and colour, before dithering
    geometry: dict[str, Any]     # framing, used by the UI to drag and show the visible area
    ms_prepare: int
    ms_quantize: int

    @property
    def coverage(self) -> dict[str, float]:
        counts = np.bincount(self.indices.ravel(), minlength=len(self.names))
        return {n: round(int(c) / self.indices.size, 4) for n, c in zip(self.names, counts, strict=True)}

    def to_image(self, table: dict[str, tuple[int, int, int]] = PURE) -> Image.Image:
        """Render the indices with a colour table (``PURE`` or ``INK``)."""
        return indices_to_image(self.indices, self.names, table)

    def tone_image(self) -> Image.Image:
        rgb = (oklab_to_rgb(self.lab) * 255).round().astype(np.uint8)
        return Image.fromarray(rgb, "RGB")


def indices_to_image(indices: np.ndarray, names: list[str], table: dict[str, tuple[int, int, int]]) -> Image.Image:
    lut = np.array([table[n] for n in names], dtype=np.uint8)
    return Image.fromarray(lut[indices], "RGB")


def frame(src: Image.Image, p: Params) -> tuple[Image.Image, dict[str, Any]]:
    """Mirror, rotate, scale and crop the source to the panel size.

    Returns the RGB canvas and the framing geometry. ``visible`` is the part of
    the (rotated) source that ends up on the panel, as fractions of its size.
    """
    bg = PURE[p.background]
    img = ImageOps.mirror(src) if p.flip else src
    if p.rotate % 360:
        img = img.rotate(-p.rotate, expand=True, resample=Image.BICUBIC, fillcolor=bg)

    iw, ih = img.size
    W, H = p.width, p.height
    if p.fit == "stretch":
        nw, nh = max(1, round(W * p.zoom)), max(1, round(H * p.zoom))
    else:
        pick = max if p.fit == "cover" else min
        s = pick(W / iw, H / ih) * p.zoom
        nw, nh = max(1, round(iw * s)), max(1, round(ih * s))

    # reducing_gap makes large photos much faster with no visible loss
    resized = img.resize((nw, nh), Image.LANCZOS, reducing_gap=3.0)
    ox = (W - nw) / 2 * (1 + p.pan_x)
    oy = (H - nh) / 2 * (1 + p.pan_y)

    canvas = Image.new("RGB", (W, H), bg)
    canvas.paste(resized, (round(ox), round(oy)))

    sx, sy = nw / iw, nh / ih
    visible = [
        max(0.0, -ox / sx) / iw, max(0.0, -oy / sy) / ih,
        min(iw, (W - ox) / sx) / iw, min(ih, (H - oy) / sy) / ih,
    ]
    geometry = {"nw": nw, "nh": nh, "ox": ox, "oy": oy,
                "rotated": [iw, ih], "visible": [round(v, 5) for v in visible]}
    return canvas, geometry


def tone(canvas: Image.Image, p: Params) -> np.ndarray:
    """Tone and colour adjustments. Returns the image in OKLab (H, W, 3)."""
    if p.auto_levels:
        canvas = ImageOps.autocontrast(canvas, cutoff=1)
    if p.sharpen > 0:
        canvas = canvas.filter(ImageFilter.UnsharpMask(radius=1.4, percent=int(p.sharpen * 180), threshold=1))

    rgb = np.asarray(canvas, dtype=np.float32) / 255.0
    rgb = (rgb - 0.5) * p.contrast + 0.5 + p.brightness
    rgb = np.clip(rgb, 0, 1)
    if abs(p.gamma - 1) > 1e-3:
        rgb = np.power(rgb, 1 / p.gamma)

    lab = rgb_to_oklab(rgb)
    if abs(p.saturation - 1) > 1e-3 or abs(p.hue) > 1e-3:
        angle = math.radians(p.hue)
        ca, sa = math.cos(angle), math.sin(angle)
        a, b = lab[..., 1].copy(), lab[..., 2].copy()
        lab[..., 1] = (a * ca - b * sa) * p.saturation
        lab[..., 2] = (a * sa + b * ca) * p.saturation
    return lab


def process_image(src: Image.Image, p: Params) -> ImageResult:
    """Run the whole imaging pipeline on a source picture."""
    t0 = time.perf_counter()
    canvas, geometry = frame(src, p)
    lab = tone(canvas, p)
    t1 = time.perf_counter()
    indices, names = quantize(lab, p)
    t2 = time.perf_counter()
    return ImageResult(indices, names, lab, geometry,
                       ms_prepare=round((t1 - t0) * 1000), ms_quantize=round((t2 - t1) * 1000))
