"""Discover nearby Gicisky tags from their BLE advertisements."""

from __future__ import annotations

import asyncio
from typing import Any

from epaper_studio.errors import StudioError
from epaper_studio.gicisky.models import MANUFACTURER_ID, parse_advert


def ble_problem() -> StudioError | None:
    """Return why BLE cannot be used at all, or ``None`` if Bleak is importable."""
    try:
        import bleak  # noqa: F401
    except ImportError:
        return StudioError("bleak_missing", "The bleak library is not installed", status=503)
    return None


async def scan(seconds: float) -> list[dict[str, Any]]:
    """Listen for ``seconds`` and return the Gicisky tags heard, strongest first."""
    from bleak import BleakScanner

    found: dict[str, dict[str, Any]] = {}

    def seen(device: Any, adv: Any) -> None:
        raw = adv.manufacturer_data.get(MANUFACTURER_ID)
        if raw is None:
            return
        info = parse_advert(bytes(raw))
        if not info:
            return
        info.update({"address": device.address, "rssi": adv.rssi,
                     "name": adv.local_name or device.name or device.address})
        found[device.address] = info

    async with BleakScanner(detection_callback=seen):
        await asyncio.sleep(seconds)
    return sorted(found.values(), key=lambda i: -(i.get("rssi") or -999))
