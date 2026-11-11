"""The Gicisky upload protocol over BLE.

The tag exposes service ``fef0``. Commands are written to ``fef1`` (which
also notifies the replies) and image data to ``fef2``:

1. ``01``                      -> ``01 f4 00``          ready?
2. ``02 <size u32 LE> 00 00 00`` -> ``02 ...``           image size
3. ``03``                      -> ``05 00 <0 u32 LE>``   start, send block 0
4. ``<n u32 LE><240 bytes>``   -> ``05 00 <next u32 LE>`` the tag asks for each
   block, repeats one if it arrived corrupted, and is done once it asks for a
   block past the end (or replies with anything other than ``05 00``).

Progress is recorded in a :class:`Job` as translatable log entries, so the UI
can follow the transfer live.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from typing import Any

from epaper_studio.errors import StudioError
from epaper_studio.gicisky.packing import BLOCK, block_packet, size_packet


class TransferError(StudioError):
    """Something went wrong while talking to the tag."""


class Job:
    """State of one upload, readable while it runs."""

    def __init__(self, address: str, total_bytes: int):
        self.id = uuid.uuid4().hex[:10]
        self.address = address
        self.total_bytes = total_bytes
        self.blocks = math.ceil(total_bytes / BLOCK)
        self.part = 0
        self.phase = "queued"
        self.status = "running"          # running | ok | error
        self.error: dict[str, Any] | None = None
        self.mtu: int | None = None
        self.attempt = 0
        self.started = time.monotonic()
        self.finished: float | None = None
        self.log: list[dict[str, Any]] = []

    # -- log ---------------------------------------------------------------
    def set_phase(self, phase: str, code: str, /, **params: Any) -> None:
        self.phase = phase
        self.note(code, **params)

    def note(self, code: str, /, **params: Any) -> None:
        self._push({"kind": "note", "code": code, "params": params})

    def frame(self, direction: str, char: str, data: bytes) -> None:
        self._push({"kind": direction, "char": char, "len": len(data),
                    "hex": data[:16].hex(" ") + (" …" if len(data) > 16 else "")})

    def _push(self, entry: dict[str, Any]) -> None:
        entry["t"] = round((time.monotonic() - self.started) * 1000)
        self.log.append(entry)
        if len(self.log) > 2000:
            del self.log[:500]

    # -- outcome -----------------------------------------------------------
    def succeed(self) -> None:
        self.status = "ok"
        self.finished = time.monotonic()

    def fail(self, error: StudioError) -> None:
        self.status, self.phase = "error", "error"
        self.error = error.to_dict()
        self.finished = time.monotonic()

    def view(self, since: int = 0) -> dict[str, Any]:
        return {
            "id": self.id, "status": self.status, "phase": self.phase, "error": self.error,
            "part": self.part, "blocks": self.blocks, "bytes": self.total_bytes,
            "mtu": self.mtu, "attempt": self.attempt,
            "elapsed": round((self.finished or time.monotonic()) - self.started, 1),
            "log": self.log[since:], "log_len": len(self.log),
        }


class GiciskyLink:
    """Speaks the protocol over an already connected Bleak client."""

    def __init__(self, client: Any, cmd_uuid: str, img_uuid: str, job: Job, delay: float = 0.0):
        self.client = client
        self.cmd = cmd_uuid
        self.img = img_uuid
        self.job = job
        self.delay = delay
        self.loop = asyncio.get_running_loop()
        self.waiting: asyncio.Future[bytes] | None = None

    def _on_notify(self, _char: Any, data: bytearray) -> None:
        def deliver() -> None:
            if self.waiting and not self.waiting.done():
                self.waiting.set_result(bytes(data))
        self.loop.call_soon_threadsafe(deliver)

    async def start(self) -> None:
        await self.client.start_notify(self.cmd, self._on_notify)
        await asyncio.sleep(1.0)  # the tag needs a moment after subscribing

    async def stop(self) -> None:
        try:
            await self.client.stop_notify(self.cmd)
        except Exception:  # noqa: BLE001 - the tag may already be gone
            pass

    async def request(self, char_uuid: str, payload: bytes, *, quiet: bool = False) -> bytes:
        """Write without response and wait for the tag's notification."""
        self.waiting = self.loop.create_future()
        name = "fef1" if char_uuid == self.cmd else "fef2"
        if not quiet:
            self.job.frame("tx", name, payload)
        await self.client.write_gatt_char(char_uuid, payload, response=False)
        if self.delay:
            await asyncio.sleep(self.delay)
        try:
            data = await asyncio.wait_for(self.waiting, 5.0)
        except asyncio.TimeoutError:
            raise TransferError("tag_silent", "The tag stopped responding") from None
        if not quiet:
            self.job.frame("rx", "fef1", data)
        return data

    async def send(self, data: bytes) -> None:
        job = self.job
        job.set_phase("handshake", "cmd_start")
        r = await self.request(self.cmd, b"\x01")
        if len(r) < 3 or r[:3] != b"\x01\xf4\x00":
            raise TransferError("unexpected_reply", "Unexpected reply", command="0x01", reply=r.hex(" "))

        job.set_phase("handshake", "cmd_size", bytes=len(data))
        r = await self.request(self.cmd, size_packet(data))
        if not r or r[0] != 0x02:
            raise TransferError("unexpected_reply", "Unexpected reply", command="0x02", reply=r.hex(" "))

        job.set_phase("handshake", "cmd_ready")
        r = await self.request(self.cmd, b"\x03")
        if len(r) < 6 or r[0] != 0x05 or r[1] != 0x00:
            raise TransferError("unexpected_reply", "Unexpected reply", command="0x03", reply=r.hex(" "))

        job.set_phase("blocks", "blocks_start")
        part, last, repeats = 0, -1, 0
        while part * BLOCK < len(data):
            # Only the first blocks and the last one are logged in full
            quiet = 3 <= part < job.blocks - 1
            r = await self.request(self.img, block_packet(data, part), quiet=quiet)
            if len(r) < 6 or r[0] != 0x05 or r[1] != 0x00:
                break  # the tag considers the image complete
            asked = int.from_bytes(r[2:6], "little")
            if asked == last:
                repeats += 1
                job.note("block_repeat", part=asked)
                if repeats >= 3:
                    raise TransferError("stalled", "The tag keeps asking for the same block", part=asked)
            else:
                repeats, last = 1, asked
            part = asked
            job.part = min(part, job.blocks)
            if quiet and part % 25 == 0:
                job.note("block_progress", part=part, total=job.blocks)
        job.part = job.blocks


def short_uuid(value: str) -> str:
    """``'0000fef1-0000-1000-8000-00805f9b34fb'`` -> ``'fef1'``."""
    value = str(value).lower()
    return value[4:8] if len(value) > 8 else value


async def acquire_mtu(client: Any) -> int | None:
    """Ask BlueZ for the negotiated MTU (Bleak only knows it after this)."""
    try:
        backend = getattr(client, "_backend", None)
        if backend is not None and hasattr(backend, "_acquire_mtu"):
            await backend._acquire_mtu()
        return client.mtu_size
    except Exception:  # noqa: BLE001 - informative only
        return None


def _exc_text(exc: BaseException) -> str:
    """A readable message for ``exc``: Bleak errors often carry extra args that
    ``str()`` would render as a tuple, so keep only the textual parts."""
    parts = [str(a) for a in getattr(exc, "args", ()) if isinstance(a, str) and a.strip()]
    return " ".join(parts) or str(exc) or type(exc).__name__


def _not_available(exc: Exception) -> StudioError | None:
    """Map Bleak's ``BleakBluetoothNotAvailableError`` (Bleak >= 2) by its reason."""
    try:
        from bleak.exc import BleakBluetoothNotAvailableError
        from bleak.exc import BleakBluetoothNotAvailableReason as R
    except ImportError:
        return None
    if not isinstance(exc, BleakBluetoothNotAvailableError):
        return None
    reason = exc.reason
    if reason == R.NO_BLUETOOTH:
        return StudioError("ble_no_adapter", "No Bluetooth adapter found", status=503)
    if reason == R.NO_BLE_CENTRAL_ROLE:
        return StudioError("ble_no_central", "The Bluetooth adapter does not support BLE", status=503)
    if reason == R.POWERED_OFF:
        return StudioError("ble_powered_off", "The Bluetooth adapter is powered off", status=503)
    if reason in (R.DENIED_BY_USER, R.DENIED_BY_SYSTEM, R.DENIED_BY_UNKNOWN):
        return StudioError("ble_denied", "Permission to use Bluetooth was denied", status=503)
    text = _exc_text(exc)
    return StudioError("ble_generic", text, status=503, detail=text)


def ble_error(exc: Exception) -> tuple[StudioError, bool]:
    """Translate common Bluetooth failures. Returns (error, worth retrying)."""
    if isinstance(exc, StudioError):
        return exc, exc.code in ("tag_silent", "tag_not_seen")
    mapped = _not_available(exc)
    if mapped is not None:
        return mapped, False
    text = _exc_text(exc)
    low = text.lower()
    name = type(exc).__name__
    if name == "BleakDeviceNotFoundError":
        return TransferError("tag_not_seen", "The tag was not seen", seconds=25), True
    if "inprogress" in low or "in progress" in low:
        return StudioError("ble_busy_adapter", "The adapter is busy with another connection"), True
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return StudioError("ble_timeout", "The Bluetooth operation timed out"), True
    if "no bluetooth adapter" in low or ("adapter" in low and "not found" in low):
        return StudioError("ble_no_adapter", "No Bluetooth adapter found", status=503), False
    if isinstance(exc, (FileNotFoundError, ConnectionRefusedError)) or "dbus" in low:
        return StudioError("ble_service_missing", "Bluetooth service (BlueZ) not found", status=503), False
    if "not ready" in low or "powered" in low or "turned off" in low:
        return StudioError("ble_powered_off", "The Bluetooth adapter is powered off", status=503), False
    if "access" in low and "denied" in low:
        return StudioError("ble_denied", "Permission to use Bluetooth was denied", status=503), False
    return StudioError("ble_generic", text, detail=text), True


async def transfer(job: Job, data: bytes, *, attempts: int = 3, write_delay: float = 0.0) -> None:
    """Find the tag, connect and upload ``data``. Never raises: the outcome is in ``job``."""
    from bleak import BleakClient, BleakScanner

    for attempt in range(1, attempts + 1):
        job.attempt = attempt
        try:
            if attempt > 1:
                job.note("retry", attempt=attempt, attempts=attempts)
            job.set_phase("scan", "waiting_advert")
            device = await BleakScanner.find_device_by_address(job.address, timeout=25)
            if device is None:
                raise TransferError("tag_not_seen", "The tag was not seen", seconds=25)

            job.set_phase("connect", "connecting")
            async with BleakClient(device, timeout=20) as client:
                job.mtu = await acquire_mtu(client)
                job.note("connected", mtu=job.mtu or "?")
                if job.mtu and job.mtu < BLOCK + 7:
                    job.note("mtu_low", mtu=job.mtu, need=BLOCK + 7)

                job.set_phase("gatt", "finding_service")
                chars = [c.uuid for s in client.services if s.uuid.lower().startswith("0000f")
                         for c in s.characteristics]
                if len(chars) < 2:
                    raise TransferError("no_service", "The tag does not expose service fef0")
                chars.sort(key=lambda u: int(short_uuid(u), 16))
                cmd, img = chars[:2]
                job.note("characteristics", cmd=short_uuid(cmd), img=short_uuid(img))

                link = GiciskyLink(client, cmd, img, job, write_delay + 0.05 * (attempt - 1))
                await link.start()
                await link.send(data)
                await link.stop()

            job.set_phase("refresh", "delivered")
            job.succeed()
            return
        except Exception as exc:  # noqa: BLE001 - every failure ends up in the job
            error, retry = ble_error(exc)
            job.note("error", code=error.code, **error.params)
            if attempt == attempts or not retry:
                job.fail(error)
                return
            await asyncio.sleep(2.0)
