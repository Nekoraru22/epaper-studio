"""User-adjustable conversion parameters."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Fit = Literal["cover", "contain", "stretch"]
Background = Literal["white", "black"]
PaletteName = Literal["bw", "bwr", "bwy", "bwry"]
DitherName = Literal["none", "bayer", "floyd", "atkinson", "jjn", "stucki", "burkes", "sierra", "sierra_lite"]
View = Literal["pure", "ink", "tone", "data"]


class Params(BaseModel):
    """Everything the editor can tweak. Defaults give a sensible first result."""

    # Panel
    width: int = Field(400, ge=16, le=1600)
    height: int = Field(300, ge=16, le=1600)

    # Framing
    fit: Fit = "cover"
    zoom: float = Field(1.0, ge=0.1, le=10)
    pan_x: float = Field(0.0, ge=-1, le=1)
    pan_y: float = Field(0.0, ge=-1, le=1)
    rotate: float = 0.0
    flip: bool = False
    background: Background = "white"

    # Tone
    auto_levels: bool = False
    brightness: float = Field(0.0, ge=-1, le=1)
    contrast: float = Field(1.0, ge=0, le=5)
    gamma: float = Field(1.0, ge=0.05, le=5)
    sharpen: float = Field(0.0, ge=0, le=4)

    # Colour
    saturation: float = Field(1.0, ge=0, le=5)
    hue: float = Field(0.0, ge=-180, le=180)
    # Weight of chroma against lightness when choosing a pigment. At 1, mid
    # greys "look like" red (it has a middling lightness) and fill with red
    # specks; from 2-3 up, only things that are actually red go red.
    color_weight: float = Field(3.0, ge=0.1, le=20)
    # Values above 0 make the colour pigments win close calls.
    color_bias: float = Field(0.0, ge=0, le=0.95)

    # Dithering
    palette: PaletteName = "bwr"
    dither: DitherName = "floyd"
    strength: float = Field(1.0, ge=0, le=1)
    serpentine: bool = True
    compress_range: bool = True

    # Output
    view: View = "pure"
    model: int | None = None  # Gicisky model id when a tag is selected
