"""Turn a pigment image into the exact buffer a Gicisky tag expects.

The output is byte-for-byte identical to hass-gicisky's, which is what the
firmware accepts (see ``tests/test_packing.py``). For the 4.2" B/W/R tag: a
black/white plane (1 = paper, 0 = ink) followed by a red plane (1 = red), one
bit per pixel, rows top to bottom, leftmost pixel in the most significant bit.
"""

from __future__ import annotations

import math
import struct
from typing import Any

import numpy as np
from PIL import Image

from epaper_studio.errors import StudioError
from epaper_studio.gicisky.models import Model

BLOCK = 240  # image bytes per block: fixed by the Gicisky firmware


class UnsupportedModel(StudioError):
    def __init__(self, model: Model):
        super().__init__("unsupported_model", f"{model.name} uses QuickLZ compression, which is not implemented",
                         model=model.name)


def pack(img: Image.Image, m: Model) -> bytes:
    """Pack an image in pure palette colours (``PURE``) for model ``m``."""
    if m.compression2:
        raise UnsupportedModel(m)

    base = Image.new("RGB", (m.width, m.height), "white")
    src = img.convert("RGB")
    if src.width > m.width or src.height > m.height:
        src = src.crop((0, 0, m.width, m.height))
    base.paste(src, (0, 0))
    if m.tft:
        base = base.resize((m.width // 2, m.height * 2), resample=Image.BICUBIC)
    if m.rotation:
        base = base.rotate(m.rotation, expand=True)

    a = np.asarray(base)
    if m.mirror_y:
        a = a[::-1]
    if m.mirror_x:
        a = a[:, ::-1]
    r, g, b = a[..., 0] > 128, a[..., 1] > 128, a[..., 2] > 128
    white = r & g & b
    black = ~r & ~g & ~b
    is_white = black if m.invert_luminance else white

    if m.four_color:
        green = g & ~(r & g & b)
        red = r & ~is_white
        # 00 black · 01 white · 10 yellow · 11 red; a trailing partial byte is dropped
        val = np.where(green, 2, np.where(red, 3, np.where(is_white, 1, 0))).astype(np.uint8).ravel()
        val = val[: len(val) // 4 * 4].reshape(-1, 4)
        return ((val[:, 0] << 6) | (val[:, 1] << 4) | (val[:, 2] << 2) | val[:, 3]).astype(np.uint8).tobytes()

    bw = np.packbits(is_white.ravel()).tobytes()
    red = np.packbits((r & ~g & ~b).ravel()).tobytes()

    if m.compression:
        # The 3.7" "compression" is really per-column framing
        per_line = m.height // 8
        buf = bytearray(4)
        for plane in (bw, red):
            for col in range(m.width):
                buf += bytes([0x75, per_line + 7, per_line, 0, 0, 0, 0])
                buf += plane[col * per_line:(col + 1) * per_line]
        buf[0:4] = len(buf).to_bytes(4, "little")
        return bytes(buf)

    return bw + red if m.red else bw


def planes(data: bytes, m: Model) -> list[dict[str, Any]]:
    """Parts of the buffer, for the explanation."""
    if m.four_color:
        return [{"kind": "2bpp", "bytes": len(data)}]
    if m.compression:
        return [{"kind": "raw", "bytes": len(data)}]
    if m.red:
        half = len(data) // 2
        return [{"kind": "bw", "bytes": half}, {"kind": "red", "bytes": half}]
    return [{"kind": "bw", "bytes": len(data)}]


def data_layout(m: Model, data: bytes) -> dict[str, Any]:
    """How the buffer splits into rows, so the UI can draw it as text."""
    w, h = m.width, m.height
    if m.tft:
        w, h = w // 2, h * 2
    if m.rotation in (90, 270):
        w, h = h, w
    base = {"block": BLOCK, "width": w,
            "transformed": bool(m.tft or m.rotation or m.mirror_x or m.mirror_y)}
    if m.compression:
        return {**base, "row_bytes": 32, "aligned": False,
                "planes": [{"kind": "raw", "start": 0, "length": len(data)}]}
    if m.four_color:
        aligned = w % 4 == 0
        return {**base, "row_bytes": w // 4 if aligned else 32, "aligned": aligned,
                "planes": [{"kind": "2bpp", "start": 0, "length": len(data)}]}
    aligned = w % 8 == 0
    plane = math.ceil(w * h / 8)
    parts = [{"kind": "bw", "start": 0, "length": plane}]
    if m.red:
        parts.append({"kind": "red", "start": plane, "length": plane})
    return {**base, "row_bytes": w // 8 if aligned else 32, "aligned": aligned, "planes": parts}


def size_packet(data: bytes) -> bytes:
    """Command 0x02: announce the image size (u32, little endian) plus 3 zero bytes."""
    return b"\x02" + struct.pack("<I", len(data)) + b"\x00\x00\x00"


def block_packet(data: bytes, part: int) -> bytes:
    """One data write: block number (u32, little endian) followed by up to 240 bytes."""
    return struct.pack("<I", part) + data[part * BLOCK:(part + 1) * BLOCK]


def transport_summary(data: bytes) -> dict[str, Any]:
    """Numbers and sample packets for the explanation."""
    packets = math.ceil(len(data) / BLOCK) if data else 0
    sample = []
    for n in range(min(3, packets)):
        pkt = block_packet(data, n)
        sample.append({
            "index": n,
            "header": pkt[:4].hex(" "),
            "data": pkt[4:24].hex(" "),
            "more": max(0, len(pkt) - 24),
            "reply": "05 00 " + struct.pack("<I", n + 1).hex(" "),
        })
    return {
        "total_bytes": len(data),
        "block": BLOCK,
        "packets": packets,
        "packet_bytes": BLOCK + 4,
        "min_mtu": BLOCK + 4 + 3,
        # Each block is a request/response: a write and a notification back,
        # roughly two connection events of ~15 ms.
        "airtime_s": round(packets * 0.030, 1),
        "size_packet": size_packet(data).hex(" "),
        "sample": sample,
    }
