"""Reduce an OKLab image to the handful of pigments an e-paper panel has.

Three steps:

1. :func:`prepare` squeezes the image into what the panel can show: lightness
   is mapped between the real ink black and paper white, and chroma is
   projected onto the directions the panel's colour pigments can paint.
2. Each pixel picks its nearest pigment, weighting chroma against lightness.
3. Error diffusion (or ordered dithering) fakes the in-between tones.
"""

from __future__ import annotations

import numpy as np

from epaper_studio.imaging.color import PALETTES, palette_lab
from epaper_studio.imaging.params import Params

# Each kernel lists where the quantisation error goes and how much of it:
# (dx, dy, weight), with the total divisor first. Pixels are visited left to
# right and top to bottom, so error only flows forward and down.
KERNELS: dict[str, tuple[int, list[tuple[int, int, int]]]] = {
    "floyd": (16, [(1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)]),
    # Atkinson spreads only 6/8 of the error: less noise, more contrast.
    "atkinson": (8, [(1, 0, 1), (2, 0, 1), (-1, 1, 1), (0, 1, 1), (1, 1, 1), (0, 2, 1)]),
    "jjn": (48, [(1, 0, 7), (2, 0, 5),
                 (-2, 1, 3), (-1, 1, 5), (0, 1, 7), (1, 1, 5), (2, 1, 3),
                 (-2, 2, 1), (-1, 2, 3), (0, 2, 5), (1, 2, 3), (2, 2, 1)]),
    "stucki": (42, [(1, 0, 8), (2, 0, 4),
                    (-2, 1, 2), (-1, 1, 4), (0, 1, 8), (1, 1, 4), (2, 1, 2),
                    (-2, 2, 1), (-1, 2, 2), (0, 2, 4), (1, 2, 2), (2, 2, 1)]),
    "burkes": (32, [(1, 0, 8), (2, 0, 4),
                    (-2, 1, 2), (-1, 1, 4), (0, 1, 8), (1, 1, 4), (2, 1, 2)]),
    "sierra": (32, [(1, 0, 5), (2, 0, 3),
                    (-2, 1, 2), (-1, 1, 4), (0, 1, 5), (1, 1, 4), (2, 1, 2),
                    (-1, 2, 2), (0, 2, 3), (1, 2, 2)]),
    "sierra_lite": (4, [(1, 0, 2), (-1, 1, 1), (0, 1, 1)]),
}

BAYER8 = (np.array([
    [0, 32, 8, 40, 2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
], dtype=np.float32) + 0.5) / 64.0

# Margin around the panel gamut, in OKLab units, when clamping the input
# (GAMUT_PAD) and when bounding the accumulated error while dithering (ERROR_PAD).
GAMUT_PAD = 0.03
ERROR_PAD = 0.10


def gamut_map(ab: np.ndarray, pal: np.ndarray, names: list[str]) -> np.ndarray:
    """Bring each pixel's chroma to what the panel can paint.

    A black/white/red panel has a single colour axis: the direction of red. A
    green points the opposite way, so it has no red to contribute and must stay
    neutral (it will be dithered in greys); a purple keeps only the part that
    does point towards red. With red and yellow, the panel covers the fan
    between both and pixels are projected onto that sector. Clipping each
    channel separately instead would turn greens reddish.
    """
    chroma = [i for i, n in enumerate(names) if n in ("red", "yellow")]
    if not chroma:
        return np.zeros_like(ab)  # black and white panel: only lightness matters

    dirs, caps = [], []
    for i in chroma:
        v = pal[i, 1:3]
        m = float(np.hypot(*v))
        dirs.append(v / m)
        caps.append(m * (1 + GAMUT_PAD))

    flat = ab.reshape(-1, 2)
    best = np.zeros_like(flat)                   # candidate: neutral
    best_d = np.einsum("ij,ij->i", flat, flat)
    for u, cap in zip(dirs, caps, strict=True):               # candidates: each pigment axis
        t = np.clip(flat @ u, 0, cap)
        proj = t[:, None] * u[None, :]
        d = np.sum((flat - proj) ** 2, axis=1)
        take = d < best_d
        best[take], best_d[take] = proj[take], d[take]

    if len(dirs) == 2:                           # inside the red-yellow fan
        M = np.stack(dirs, axis=1)
        coef = flat @ np.linalg.inv(M).T
        inside = (coef >= 0).all(axis=1)
        cap = max(caps)
        norm = np.hypot(flat[:, 0], flat[:, 1])
        scale = np.where(norm > cap, cap / np.maximum(norm, 1e-9), 1.0)
        best[inside] = flat[inside] * scale[inside, None]

    return best.reshape(ab.shape)


def prepare(lab: np.ndarray, names: list[str], p: Params) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit the image to the range the panel can show.

    Paper white is not pure white and ink black is not pure black. Without
    compressing the range, a white background produces error that can never be
    paid back, and dithering spreads it as grey noise.

    Returns the working image, the palette in OKLab and per-pigment weights.
    """
    pal = palette_lab(names)
    work = lab.astype(np.float64).copy()
    if p.compress_range:
        lo = pal[names.index("black"), 0]
        hi = pal[names.index("white"), 0]
        work[..., 0] = lo + work[..., 0] * (hi - lo)

    work[..., 1:] = gamut_map(work[..., 1:], pal, names)

    # Per-pigment weight: below 1 makes the colour pigments attract more pixels.
    weights = np.ones(len(names))
    for i, name in enumerate(names):
        if name in ("red", "yellow"):
            weights[i] = max(0.05, 1.0 - p.color_bias)
    return work, pal, weights


def nearest(work: np.ndarray, pal: np.ndarray, weights: np.ndarray, color_weight: float) -> np.ndarray:
    """Index of the nearest pigment for every pixel, vectorised."""
    d = work[..., None, :] - pal[None, None, :, :]
    dist = d[..., 0] ** 2 + color_weight * (d[..., 1] ** 2 + d[..., 2] ** 2)
    return np.argmin(dist * weights, axis=-1).astype(np.uint8)


def diffuse(work: np.ndarray, pal: np.ndarray, weights: np.ndarray, p: Params) -> np.ndarray:
    """Error diffusion in OKLab, with optional serpentine scanning.

    The algorithm is inherently sequential (each pixel depends on the error of
    the previous ones), so it is written as a loop over flat Python lists, which
    in CPython is several times faster than indexing NumPy arrays.
    """
    H, W = work.shape[:2]
    div, raw = KERNELS[p.dither]
    s = p.strength
    kern = [(dx, dy, w / div) for dx, dy, w in raw]

    L = work[..., 0].ravel().tolist()
    A = work[..., 1].ravel().tolist()
    B = work[..., 2].ravel().tolist()
    entries = [(float(pal[k, 0]), float(pal[k, 1]), float(pal[k, 2]), float(weights[k]))
               for k in range(len(pal))]
    cw = p.color_weight
    out = bytearray(W * H)
    # Bounds for pixel + accumulated error: the panel gamut plus a margin.
    # Beyond that the error can no longer be paid back and only adds noise.
    lo_l = float(pal[:, 0].min()) - ERROR_PAD
    hi_l = float(pal[:, 0].max()) + ERROR_PAD
    lo_a = float(pal[:, 1].min()) - ERROR_PAD
    hi_a = float(pal[:, 1].max()) + ERROR_PAD
    lo_b = float(pal[:, 2].min()) - ERROR_PAD
    hi_b = float(pal[:, 2].max()) + ERROR_PAD

    for y in range(H):
        rtl = p.serpentine and (y & 1)
        row = y * W
        xs = range(W - 1, -1, -1) if rtl else range(W)
        for x in xs:
            i = row + x
            # Explicit comparisons: min()/max() calls are much slower in this hot loop
            l = L[i]
            if l < lo_l:
                l = lo_l
            elif l > hi_l:
                l = hi_l
            a = A[i]
            if a < lo_a:
                a = lo_a
            elif a > hi_a:
                a = hi_a
            b = B[i]
            if b < lo_b:
                b = lo_b
            elif b > hi_b:
                b = hi_b

            best = 0
            bd = 1e18
            for k, (pl, pa, pb, wt) in enumerate(entries):
                dl = l - pl
                da = a - pa
                db = b - pb
                dist = (dl * dl + cw * (da * da + db * db)) * wt
                if dist < bd:
                    bd = dist
                    best = k
            out[i] = best

            pl, pa, pb, _ = entries[best]
            el = (l - pl) * s
            ea = (a - pa) * s
            eb = (b - pb) * s
            for dx, dy, w in kern:
                nx = x - dx if rtl else x + dx
                ny = y + dy
                if 0 <= nx < W and ny < H:
                    j = ny * W + nx
                    L[j] += el * w
                    A[j] += ea * w
                    B[j] += eb * w

    return np.frombuffer(bytes(out), dtype=np.uint8).reshape(H, W)


def ordered(work: np.ndarray, pal: np.ndarray, weights: np.ndarray, p: Params) -> np.ndarray:
    """Ordered dithering with a Bayer matrix: regular pattern, no noise."""
    H, W = work.shape[:2]
    tile = np.tile(BAYER8, (H // 8 + 1, W // 8 + 1))[:H, :W] - 0.5
    shifted = work.copy()
    spread = 0.42 * p.strength
    shifted[..., 0] += tile * spread
    shifted[..., 1:] += tile[..., None] * spread * 0.35
    return nearest(shifted, pal, weights, p.color_weight)


def quantize(lab: np.ndarray, p: Params) -> tuple[np.ndarray, list[str]]:
    """Return pigment indices (H, W) and the pigment names they refer to."""
    names = PALETTES[p.palette]
    work, pal, weights = prepare(lab, names, p)
    if p.dither == "none" or p.strength <= 0:
        idx = nearest(work, pal, weights, p.color_weight)
    elif p.dither == "bayer":
        idx = ordered(work, pal, weights, p)
    else:
        idx = diffuse(work, pal, weights, p)
    return idx, names
