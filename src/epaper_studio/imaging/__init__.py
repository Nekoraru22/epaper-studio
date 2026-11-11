"""Image processing: framing, tone, colour mapping and dithering."""

from epaper_studio.imaging.color import INK, PALETTES, PURE
from epaper_studio.imaging.params import Params
from epaper_studio.imaging.pipeline import ImageResult, process_image

__all__ = ["INK", "PALETTES", "PURE", "ImageResult", "Params", "process_image"]
