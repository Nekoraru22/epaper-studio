"""Colour spaces and panel pigments.

OKLab is a perceptual colour space: the Euclidean distance between two colours
roughly matches how different they look. Choosing the "nearest" pigment and
spreading the quantisation error in this space gives much better results than
doing it in RGB, especially for in-between colours such as purples or oranges.
"""

from __future__ import annotations

import numpy as np

# Values used when packing: each one maps unambiguously to its pigment when the
# image is turned into bit planes.
PURE: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "yellow": (255, 255, 0),
}

# What each pigment actually looks like on e-paper. Matching pixels against the
# real ink colour, rather than ideal RGB, is what keeps a dark red in a photo
# from turning black. Also used by the "real ink" preview.
INK: dict[str, tuple[int, int, int]] = {
    "white": (232, 231, 222),
    "black": (34, 34, 38),
    "red": (176, 36, 40),
    "yellow": (220, 184, 32),
}

PALETTES: dict[str, list[str]] = {
    "bw": ["white", "black"],
    "bwr": ["white", "black", "red"],
    "bwy": ["white", "black", "yellow"],
    "bwry": ["white", "black", "red", "yellow"],
}


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def rgb_to_oklab(rgb01: np.ndarray) -> np.ndarray:
    """sRGB in [0, 1] (..., 3) to OKLab (..., 3)."""
    lin = srgb_to_linear(np.clip(rgb01, 0, 1))
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = np.cbrt(l), np.cbrt(m), np.cbrt(s)
    return np.stack([
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    ], axis=-1)


def oklab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """OKLab (..., 3) to sRGB in [0, 1] (..., 3)."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = np.stack([
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    ], axis=-1)
    return linear_to_srgb(lin)


def palette_lab(names: list[str]) -> np.ndarray:
    """OKLab coordinates of the real ink colours, in palette order."""
    return rgb_to_oklab(np.array([INK[n] for n in names], dtype=np.float32) / 255.0)
