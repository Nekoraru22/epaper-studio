"""Gicisky tag models and their BLE advertisement.

Every tag advertises its model in its manufacturer data (company id 0x5053).
The table below says how each model expects the image: size, whether it has
red, and whether it must be rotated, mirrored or framed before packing.

The values come from hass-gicisky (https://github.com/eigger/hass-gicisky,
MIT licence), where they were worked out model by model.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

MANUFACTURER_ID = 0x5053


@dataclass(frozen=True)
class Model:
    name: str
    width: int
    height: int
    red: bool = True
    tft: bool = False
    mirror_x: bool = False
    mirror_y: bool = False
    rotation: int = 0
    compression: bool = False      # per-column framing (not real compression)
    compression2: bool = False     # QuickLZ compression: not implemented
    invert_luminance: bool = False
    four_color: bool = False
    min_voltage: float = 2.5
    max_voltage: float = 2.9

    @property
    def supported(self) -> bool:
        return not self.compression2

    @property
    def palette(self) -> str:
        return "bwry" if self.four_color else ("bwr" if self.red else "bw")


MODELS: dict[int, Model] = {
    0x00A0: Model('TFT 2.1" B/W', 250, 132, red=False, tft=True, rotation=90, mirror_x=True),
    0x000B: Model('EPD 2.1" B/W/R', 212, 104, rotation=270, mirror_x=True),
    0x010B: Model('EPD 2.1" B/W/R', 250, 128, rotation=270, mirror_x=True),
    0x0028: Model('EPD 2.9" B/W', 296, 128, rotation=90, red=False),
    0x0033: Model('EPD 2.9" B/W/R', 296, 128, rotation=90),
    0x002E: Model('EPD 2.9" B/W/R/Y', 296, 128, rotation=90, four_color=True),
    0x022B: Model('EPD 3.7" B/W/R', 240, 416, rotation=180, mirror_x=True, compression=True),
    0x004E: Model('EPD 4.2" B/W/R/Y', 400, 300, four_color=True),
    0x004B: Model('EPD 4.2" B/W/R', 400, 300),
    0x012B: Model('EPD 7.5" B/W/R', 800, 480, mirror_y=True, invert_luminance=True, compression2=True),
    0x008B: Model('EPD 10.2" B/W/R', 960, 640, compression2=True),
}


def get_model(model_id: int, firmware: int = 0) -> Model | None:
    """Look up a model, applying known firmware quirks."""
    model = MODELS.get(model_id)
    # The 7.5" with firmware 0x8101 uses the older column framing, not QuickLZ
    if model and model_id == 0x012B and firmware == 0x8101:
        model = replace(model, compression=True, compression2=False)
    return model


def generic_model(width: int, height: int, names: list[str]) -> Model:
    """A plain panel, for previews when no known tag is selected."""
    return Model("Generic panel", width, height, red="red" in names, four_color=len(names) == 4)


def parse_advert(data: bytes) -> dict[str, Any] | None:
    """Decode the 5 manufacturer bytes a tag advertises.

    ``[0]`` model id, low byte · ``[1]`` voltage in tenths · ``[2:4]`` firmware ·
    ``[4]`` model id, high byte. The model id keeps the lower 14 bits.
    """
    if len(data) != 5:
        return None
    model_id = ((data[4] << 8) | data[0]) & 0x3FFF
    firmware = (data[2] << 8) | data[3]
    model = get_model(model_id, firmware)
    volts = data[1] / 10
    info: dict[str, Any] = {
        "raw": data.hex(" "),
        "model_id": model_id,
        "hardware": f"0x{(data[4] << 8) | data[0]:04X}",
        "firmware": f"0x{firmware:04X}",
        "volts": round(volts, 1),
        "known": model is not None,
    }
    if model:
        battery = (volts - model.min_voltage) * 100 / (model.max_voltage - model.min_voltage)
        info.update({
            "model": model.name, "width": model.width, "height": model.height,
            "palette": model.palette, "battery": max(0, min(100, round(battery))),
            "supported": model.supported,
        })
    return info
