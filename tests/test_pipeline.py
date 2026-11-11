import numpy as np
import pytest

from epaper_studio.imaging import Params, process_image
from epaper_studio.service import prepare_label


@pytest.mark.parametrize("dither", ["none", "bayer", "floyd", "atkinson", "jjn", "stucki", "burkes",
                                    "sierra", "sierra_lite"])
def test_every_dither_produces_palette_indices(photo, dither: str) -> None:
    result = process_image(photo, Params(width=120, height=90, dither=dither))
    assert result.indices.shape == (90, 120)
    assert set(np.unique(result.indices)) <= set(range(len(result.names)))
    assert abs(sum(result.coverage.values()) - 1) < 1e-3


def test_green_is_not_turned_red(photo) -> None:
    """Gamut mapping: green has no red component, so it must dither to greys."""
    result = process_image(photo, Params(width=320, height=240, fit="stretch", dither="none"))
    names = result.names
    green = result.indices[150:190, 190:270]
    red = result.indices[50:90, 50:130]
    assert (green == names.index("red")).mean() < 0.02
    assert (red == names.index("red")).mean() > 0.9


def test_prepare_label_packs_for_the_selected_model(photo) -> None:
    label = prepare_label(photo, Params(model=0x004B))
    assert len(label.data) == 30000
    assert label.stats["transport"]["packets"] == 125
    assert label.layout["planes"][0]["kind"] == "bw"


def test_params_reject_unknown_values() -> None:
    with pytest.raises(ValueError):
        Params(dither="nope")
