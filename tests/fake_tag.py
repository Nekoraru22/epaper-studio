"""A simulated Gicisky tag that stands in for ``BleakScanner`` and ``BleakClient``.

It answers the protocol the way a real tag does (``01`` → ``01 f4 00``,
``02`` → ``02 …``, ``03`` → ``05 00 …``, each block → ``05 00 <next>``),
advertises the manufacturer bytes of a 4.2" black/white/red tag and, to
exercise the retry path, pretends to lose one block.

Used by the test suite and handy for developing the UI without hardware:
see ``tests/run_fake_server.py``.
"""

from __future__ import annotations

import asyncio
import struct
import types
from typing import Any

ADDRESS = "AA:BB:CC:00:12:34"
NAME = "NEMR00001234"
ADVERT = bytes.fromhex("4b 1e 81 01 40")  # model 0x004B, 3.0 V, firmware 0x8101


def u(short: str) -> str:
    return f"0000{short}-0000-1000-8000-00805f9b34fb"


class Char:
    def __init__(self, uuid: str):
        self.uuid = uuid


class Service:
    def __init__(self, uuid: str, chars: list[str]):
        self.uuid = uuid
        self.characteristics = [Char(c if len(c) > 8 else u(c)) for c in chars]


class FakeScanner:
    def __init__(self, detection_callback: Any = None, **_kw: Any):
        self.cb = detection_callback

    async def __aenter__(self) -> FakeScanner:
        loop = asyncio.get_running_loop()
        tag = types.SimpleNamespace(address=ADDRESS, name=NAME)
        tag_adv = types.SimpleNamespace(manufacturer_data={0x5053: ADVERT}, rssi=-61, local_name=NAME)
        other = types.SimpleNamespace(address="11:22:33:44:55:66", name="Some TV")
        other_adv = types.SimpleNamespace(manufacturer_data={0x0075: b"\x01"}, rssi=-70, local_name=None)
        loop.call_later(0.2, self.cb, tag, tag_adv)
        loop.call_later(0.3, self.cb, other, other_adv)
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    @staticmethod
    async def find_device_by_address(address: str, timeout: float = 10.0, **_kw: Any) -> Any:
        await asyncio.sleep(0.1)  # wait for the next advert
        return types.SimpleNamespace(address=address) if address.upper() == ADDRESS else None


class FakeClient:
    """Records what it receives in ``FakeClient.received``."""

    lose_block: int | None = 40
    finish_with_end_code = False
    received: dict[str, Any] = {"data": None, "events": []}

    def __init__(self, device: Any, timeout: float = 30, **_kw: Any):
        self.device = device
        self.services = [
            Service(u("1800"), ["2a00", "2a01"]),
            Service(u("fef0"), ["fef3", "fef1", "fef2"]),
            Service("00010203-0405-0607-0809-0a0b0c0d1912", ["00010203-0405-0607-0809-0a0b0c0d2b12"]),
        ]
        self.cb: Any = None
        self.size = 0
        self.buf = bytearray()
        self.lost = False
        self.mtu_size = 247
        self._backend = types.SimpleNamespace(_acquire_mtu=self._acquire)

    @classmethod
    def reset(cls) -> None:
        cls.received = {"data": None, "events": []}

    async def _acquire(self) -> None:
        return None

    async def __aenter__(self) -> FakeClient:
        await asyncio.sleep(0.05)
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def start_notify(self, uuid: str, cb: Any) -> None:
        assert "fef1" in uuid, uuid
        self.cb = cb

    async def stop_notify(self, _uuid: str) -> None:
        self.cb = None

    def _notify(self, data: bytes) -> None:
        asyncio.get_running_loop().call_later(0.002, self.cb, Char(u("fef1")), bytearray(data))

    async def write_gatt_char(self, uuid: str, data: bytes, response: bool | None = None) -> None:
        data = bytes(data)
        assert response is False, "Gicisky writes are without response"
        events = self.received["events"]
        if "fef1" in uuid:
            events.append(("cmd", data.hex(" ")))
            if data == b"\x01":
                self._notify(b"\x01\xf4\x00")
            elif data[0] == 0x02:
                assert len(data) == 8 and data[5:] == b"\x00\x00\x00", data.hex()
                self.size = struct.unpack("<I", data[1:5])[0]
                self.buf = bytearray(self.size)
                self._notify(b"\x02\x00")
            elif data == b"\x03":
                self._notify(b"\x05\x00" + struct.pack("<I", 0))
            else:
                raise AssertionError("unknown command " + data.hex())
        elif "fef2" in uuid:
            part = struct.unpack("<I", data[:4])[0]
            chunk = data[4:]
            assert len(chunk) <= 240
            if part == self.lose_block and not self.lost:
                self.lost = True  # "lost": ask for the same block again
                events.append(("lost", part))
                self._notify(b"\x05\x00" + struct.pack("<I", part))
                return
            self.buf[part * 240: part * 240 + len(chunk)] = chunk
            nxt = part + 1
            if nxt * 240 >= self.size:
                self.received["data"] = bytes(self.buf)
                if self.finish_with_end_code:
                    self._notify(b"\x05\x08" + struct.pack("<I", nxt))
                    return
            self._notify(b"\x05\x00" + struct.pack("<I", nxt))
        else:
            raise AssertionError("unexpected characteristic " + uuid)


def install() -> None:
    """Replace Bleak's scanner and client with the fakes (process-wide)."""
    import bleak

    bleak.BleakScanner = FakeScanner
    bleak.BleakClient = FakeClient
