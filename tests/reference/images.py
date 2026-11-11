"""Deterministic test images shared by the reference generator and the tests."""

from __future__ import annotations

import numpy as np
from PIL import Image

from epaper_studio.gicisky.models import Model
from epaper_studio.imaging import PALETTES, PURE
from epaper_studio.imaging.pipeline import indices_to_image


def model_image(model_id: int, model: Model) -> Image.Image:
    """Random pixels in the model's pure palette colours, seeded by the model id."""
    names = PALETTES[model.palette]
    rng = np.random.default_rng(model_id)
    idx = rng.integers(0, len(names), size=(model.height, model.width)).astype(np.uint8)
    return indices_to_image(idx, names, PURE)
