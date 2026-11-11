"""Glue between the imaging pipeline and the tag format.

The web layer calls :func:`prepare_label` and gets back everything it needs:
the dithered image, the exact bytes that would be uploaded and the numbers the
UI shows next to them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image

from epaper_studio.gicisky.models import Model, generic_model, get_model
from epaper_studio.gicisky.packing import UnsupportedModel, data_layout, pack, planes, transport_summary
from epaper_studio.imaging import PALETTES, Params, process_image
from epaper_studio.imaging.pipeline import ImageResult


@dataclass
class LabelResult:
    image: ImageResult
    model: Model
    data: bytes              # empty when the model cannot be packed
    stats: dict[str, Any]

    @property
    def layout(self) -> dict[str, Any]:
        return data_layout(self.model, self.data)


def model_for(p: Params, names: list[str]) -> Model:
    """The selected tag's model if it matches the canvas, otherwise a generic panel."""
    model = get_model(p.model) if p.model is not None else None
    if model and (model.width, model.height) == (p.width, p.height):
        return model
    return generic_model(p.width, p.height, names)


def fit_params_to_model(p: Params, model_id: int, model: Model) -> Params:
    """Force the canvas size and a palette the tag can actually show."""
    allowed = set(PALETTES[model.palette])
    palette = p.palette if set(PALETTES[p.palette]) <= allowed else model.palette
    return p.model_copy(update={"width": model.width, "height": model.height,
                                "palette": palette, "model": model_id})


def prepare_label(src: Image.Image, p: Params) -> LabelResult:
    image = process_image(src, p)
    model = model_for(p, image.names)
    stats: dict[str, Any] = {
        "ms_prepare": image.ms_prepare,
        "ms_quantize": image.ms_quantize,
        "coverage": image.coverage,
        "geometry": image.geometry,
        "size": [p.width, p.height],
        "model": model.name,
    }
    try:
        data = pack(image.to_image(), model)
        stats["planes"] = planes(data, model)
        stats["transport"] = transport_summary(data)
    except UnsupportedModel as exc:
        data = b""
        stats["unsupported"] = exc.to_dict()
    return LabelResult(image, model, data, stats)
