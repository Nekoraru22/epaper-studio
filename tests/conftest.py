import asyncio
import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

TESTS = Path(__file__).parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS / "reference"))

STATIC = TESTS.parent / "src/epaper_studio/web/static"


@pytest.fixture
def photo() -> Image.Image:
    """A small synthetic photo: gradients plus saturated patches, including red and green."""
    h, w = 240, 320
    y, x = np.mgrid[0:h, 0:w]
    rgb = np.stack([x / w * 255, y / h * 255, (1 - x / w) * 200], axis=-1)
    rgb[40:100, 40:140] = (210, 30, 40)   # red
    rgb[140:200, 180:280] = (40, 170, 60)  # green
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


@pytest.fixture
def photo_png(photo: Image.Image) -> bytes:
    buf = io.BytesIO()
    photo.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def fake_ble(monkeypatch: pytest.MonkeyPatch):
    """Patch Bleak with the simulated tag for the duration of a test."""
    import bleak

    import fake_tag

    fake_tag.FakeClient.reset()
    fake_tag.FakeClient.lose_block = 40
    fake_tag.FakeClient.finish_with_end_code = False
    monkeypatch.setattr(bleak, "BleakScanner", fake_tag.FakeScanner)
    monkeypatch.setattr(bleak, "BleakClient", fake_tag.FakeClient)
    # The protocol waits 1 s after subscribing; not needed against the fake.
    from epaper_studio.gicisky import protocol

    class FastAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        def sleep(seconds, *args):
            return asyncio.sleep(min(seconds, 0.01), *args)

    monkeypatch.setattr(protocol, "asyncio", FastAsyncio())
    return fake_tag
