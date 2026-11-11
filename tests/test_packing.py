"""Packing must match hass-gicisky byte for byte (see tests/reference/generate.py)."""

import hashlib
import json
from pathlib import Path

import pytest
from images import model_image

from epaper_studio.gicisky.models import MODELS, get_model
from epaper_studio.gicisky.packing import (
    BLOCK,
    UnsupportedModel,
    block_packet,
    data_layout,
    pack,
    planes,
    size_packet,
    transport_summary,
)

REFERENCE = json.loads((Path(__file__).parent / "reference/hass_gicisky_digests.json").read_text())["models"]


@pytest.mark.parametrize("model_hex", sorted(REFERENCE))
def test_pack_matches_reference(model_hex: str) -> None:
    model_id = int(model_hex, 16)
    model = get_model(model_id)
    data = pack(model_image(model_id, model), model)
    assert len(data) == REFERENCE[model_hex]["bytes"]
    assert hashlib.sha256(data).hexdigest() == REFERENCE[model_hex]["sha256"]


def test_every_supported_model_has_a_reference() -> None:
    supported = {f"0x{k:04X}" for k, m in MODELS.items() if m.supported}
    assert supported <= set(REFERENCE)


def test_unsupported_models_raise() -> None:
    for model in MODELS.values():
        if not model.supported:
            with pytest.raises(UnsupportedModel):
                pack(model_image(0, model), model)


def test_bwr_layout_and_planes() -> None:
    model = get_model(0x004B)
    data = pack(model_image(0x004B, model), model)
    assert len(data) == 30000
    assert [p["kind"] for p in planes(data, model)] == ["bw", "red"]
    layout = data_layout(model, data)
    assert layout["row_bytes"] == 50 and layout["aligned"]
    assert layout["planes"][1] == {"kind": "red", "start": 15000, "length": 15000}


def test_packets() -> None:
    data = bytes(range(256)) * 2
    assert size_packet(data) == bytes.fromhex("02 00 02 00 00 00 00 00")
    assert block_packet(data, 1) == b"\x01\x00\x00\x00" + data[BLOCK:2 * BLOCK]
    summary = transport_summary(data)
    assert summary["packets"] == 3 and summary["min_mtu"] == 247
    assert summary["sample"][0]["reply"] == "05 00 01 00 00 00"
