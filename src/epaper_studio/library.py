"""Things the user keeps between sessions: named devices and saved designs.

Everything lives in one data directory::

    <data_dir>/devices.json             names, groups and models of known tags
    <data_dir>/designs/<id>/meta.json   name, adjustment parameters, dates
    <data_dir>/designs/<id>/source.png  the working copy of the original image
    <data_dir>/designs/<id>/thumb.png   a small preview in real ink colours

Files are written atomically (write to a temporary file, then rename), so a
crash never leaves half a JSON file behind. With ``data_dir=None`` the library
keeps everything in memory, which is what the tests use.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from epaper_studio.errors import StudioError

Transport = Literal["server", "web"]
THUMB_WIDTH = 320
DESIGN_LIMIT = 500
BACKUP_FORMAT = "epaper-studio-designs"
BACKUP_MANIFEST = "epaper-studio.json"
BACKUP_MAX_PNG = 40 * 1024 * 1024  # per image, uncompressed
ImportMode = Literal["merge", "replace"]


def device_key(transport: str, address: str) -> str:
    """Stable, URL-safe key. Browser device ids may contain ``/`` and ``+``."""
    return hashlib.sha1(f"{transport}|{address}".encode()).hexdigest()[:16]


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


@dataclass
class _Design:
    meta: dict[str, Any]
    source: bytes = b""
    thumb: bytes = b""


@dataclass
class Library:
    data_dir: Path | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _devices: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    _designs: dict[str, _Design] = field(default_factory=dict, repr=False)  # memory mode only

    def __post_init__(self) -> None:
        if self.data_dir is None:
            return
        self.data_dir = Path(self.data_dir)
        path = self.data_dir / "devices.json"
        if path.is_file():
            try:
                self._devices = {d["key"]: d for d in json.loads(path.read_text("utf-8")).get("devices", [])}
            except (ValueError, KeyError, TypeError):
                # A damaged file should not stop the program: keep a copy and start afresh.
                shutil.copy(path, path.with_suffix(".json.bak"))
                self._devices = {}

    # -- devices -------------------------------------------------------------
    def devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._devices.values(), key=lambda d: (d["group"].lower(), d["name"].lower()))

    def save_device(self, transport: Transport, address: str, *, name: str = "", group: str = "",
                    model_id: int | None = None, ble_name: str = "") -> dict[str, Any]:
        address = address.strip()
        if transport == "server":
            address = address.upper()
        if not address:
            raise StudioError("invalid_request", "A device needs an address")
        key = device_key(transport, address)
        with self._lock:
            old = self._devices.get(key, {})
            ble_name = ble_name.strip() or old.get("ble_name", "")
            record = {
                "key": key, "transport": transport, "address": address,
                "name": name.strip()[:60] or old.get("name") or ble_name or address,
                "group": group.strip()[:40],
                "model_id": model_id if model_id is not None else old.get("model_id"),
                "ble_name": ble_name,
                "added": old.get("added", int(time.time())),
            }
            self._devices[key] = record
            self._flush_devices()
            return record

    def forget_device(self, key: str) -> None:
        with self._lock:
            if self._devices.pop(key, None) is None:
                raise StudioError("device_unknown", "Unknown device", status=404)
            self._flush_devices()

    def _flush_devices(self) -> None:
        if self.data_dir is not None:
            doc = {"version": 1, "devices": list(self._devices.values())}
            _atomic_write(self.data_dir / "devices.json", json.dumps(doc, indent=2, ensure_ascii=False).encode())

    # -- designs -------------------------------------------------------------
    def _dir(self, design_id: str) -> Path:
        if not design_id.isalnum():
            raise StudioError("design_unknown", "Unknown design", status=404)
        assert self.data_dir is not None
        return self.data_dir / "designs" / design_id

    def designs(self) -> list[dict[str, Any]]:
        with self._lock:
            if self.data_dir is None:
                metas = [d.meta for d in self._designs.values()]
            else:
                metas = []
                for meta_path in (self.data_dir / "designs").glob("*/meta.json"):
                    try:
                        metas.append(json.loads(meta_path.read_text("utf-8")))
                    except ValueError:
                        continue
            return sorted(metas, key=lambda m: -m["updated"])

    def design(self, design_id: str) -> dict[str, Any]:
        with self._lock:
            if self.data_dir is None:
                found = self._designs.get(design_id)
                if found is None:
                    raise StudioError("design_unknown", "Unknown design", status=404)
                return found.meta
            path = self._dir(design_id) / "meta.json"
            if not path.is_file():
                raise StudioError("design_unknown", "Unknown design", status=404)
            return json.loads(path.read_text("utf-8"))

    def create_design(self, name: str, params: dict[str, Any], source: Image.Image,
                      preview: Image.Image) -> dict[str, Any]:
        with self._lock:
            if len(self.designs()) >= DESIGN_LIMIT:
                raise StudioError("design_limit", "Too many saved designs", status=409, limit=DESIGN_LIMIT)
            now = int(time.time())
            meta = {"id": uuid.uuid4().hex[:12], "name": name.strip()[:60] or "Untitled",
                    "params": params, "width": source.width, "height": source.height,
                    "created": now, "updated": now}
            self._write_design(meta, _png(source), _png(self._thumb(preview)))
            return meta

    def update_design(self, design_id: str, *, name: str | None = None, params: dict[str, Any] | None = None,
                      source: Image.Image | None = None, preview: Image.Image | None = None) -> dict[str, Any]:
        with self._lock:
            meta = dict(self.design(design_id))
            if name is not None:
                meta["name"] = name.strip()[:60] or meta["name"]
            if params is not None:
                meta["params"] = params
            if source is not None:
                meta["width"], meta["height"] = source.size
            meta["updated"] = int(time.time())
            self._write_design(meta, _png(source) if source is not None else None,
                               _png(self._thumb(preview)) if preview is not None else None)
            return meta

    def delete_design(self, design_id: str) -> None:
        with self._lock:
            self.design(design_id)  # raises if unknown
            if self.data_dir is None:
                del self._designs[design_id]
            else:
                shutil.rmtree(self._dir(design_id))

    def design_source(self, design_id: str) -> Image.Image:
        return Image.open(io.BytesIO(self._read(design_id, "source"))).convert("RGB")

    def design_source_bytes(self, design_id: str) -> bytes:
        return self._read(design_id, "source")

    def design_thumb(self, design_id: str) -> bytes:
        return self._read(design_id, "thumb")

    @staticmethod
    def _thumb(preview: Image.Image) -> Image.Image:
        img = preview.convert("RGB")
        if img.width > THUMB_WIDTH:
            img = img.resize((THUMB_WIDTH, max(1, round(img.height * THUMB_WIDTH / img.width))), Image.NEAREST)
        return img

    def _read(self, design_id: str, part: str) -> bytes:
        with self._lock:
            self.design(design_id)
            if self.data_dir is None:
                return getattr(self._designs[design_id], part)
            return (self._dir(design_id) / f"{part}.png").read_bytes()

    # -- backup ----------------------------------------------------------------
    def export_designs(self) -> bytes:
        """Every saved design as one zip: a JSON manifest plus each design's PNGs."""
        with self._lock:
            metas = self.designs()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                doc = {"format": BACKUP_FORMAT, "version": 1, "exported": int(time.time()), "designs": metas}
                zf.writestr(BACKUP_MANIFEST, json.dumps(doc, indent=2, ensure_ascii=False))
                for m in metas:
                    # PNGs are already compressed: store them as they are.
                    zf.writestr(f"designs/{m['id']}/source.png", self._read(m["id"], "source"), zipfile.ZIP_STORED)
                    zf.writestr(f"designs/{m['id']}/thumb.png", self._read(m["id"], "thumb"), zipfile.ZIP_STORED)
            return buf.getvalue()

    def import_designs(
        self,
        raw: bytes,
        mode: ImportMode = "merge",
        check_params: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        """Restore a zip made by :meth:`export_designs`.

        ``replace`` deletes every saved design first. ``merge`` keeps them, and a
        design whose name matches an existing one (ignoring case) overwrites it.
        The whole file is validated before anything is changed.
        """
        incoming = _read_backup(raw, check_params)
        with self._lock:
            current = [] if mode == "replace" else self.designs()
            by_name = {m["name"].casefold(): m for m in current}
            new_count = sum(1 for meta, _, _ in incoming if meta["name"].casefold() not in by_name)
            if len(current) + new_count > DESIGN_LIMIT:
                raise StudioError("design_limit", "Too many saved designs", status=409, limit=DESIGN_LIMIT)
            if mode == "replace":
                for m in self.designs():
                    self.delete_design(m["id"])
            added = replaced = 0
            now = int(time.time())
            for meta, source, thumb in incoming:
                old = by_name.get(meta["name"].casefold())
                if old is not None:
                    meta = {**meta, "id": old["id"], "created": old["created"], "updated": now}
                    replaced += 1
                else:
                    meta = {**meta, "id": uuid.uuid4().hex[:12]}
                    by_name[meta["name"].casefold()] = meta
                    added += 1
                self._write_design(meta, source, thumb)
            return {"added": added, "replaced": replaced}

    def _write_design(self, meta: dict[str, Any], source: bytes | None, thumb: bytes | None) -> None:
        if self.data_dir is None:
            old = self._designs.get(meta["id"])
            self._designs[meta["id"]] = _Design(meta, source if source is not None else old.source,
                                                thumb if thumb is not None else old.thumb)
            return
        folder = self._dir(meta["id"])
        if source is not None:
            _atomic_write(folder / "source.png", source)
        if thumb is not None:
            _atomic_write(folder / "thumb.png", thumb)
        _atomic_write(folder / "meta.json", json.dumps(meta, indent=2, ensure_ascii=False).encode())


def _png_size(data: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format != "PNG":
                raise ValueError("not a PNG")
            img.verify()
            return img.size
    except Exception as exc:  # noqa: BLE001 - any decoding failure means a bad file
        raise StudioError("backup_invalid", "The backup contains a damaged image") from exc


def _read_backup(
    raw: bytes, check_params: Callable[[dict[str, Any]], dict[str, Any]] | None
) -> list[tuple[dict[str, Any], bytes, bytes]]:
    """Parse and validate a backup zip into (meta, source PNG, thumb PNG) tuples."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise StudioError("backup_invalid", "Not a backup file") from exc
    with zf:

        def member(name: str) -> bytes:
            try:
                info = zf.getinfo(name)
            except KeyError as exc:
                raise StudioError("backup_invalid", f"Missing {name}") from exc
            if info.file_size > BACKUP_MAX_PNG:
                raise StudioError("backup_invalid", f"{name} is too large")
            return zf.read(info)

        try:
            doc = json.loads(member(BACKUP_MANIFEST))
        except ValueError as exc:
            raise StudioError("backup_invalid", "Damaged manifest") from exc
        if not isinstance(doc, dict) or doc.get("format") != BACKUP_FORMAT or not isinstance(doc.get("designs"), list):
            raise StudioError("backup_invalid", "Not an E-Paper Studio backup")
        if doc.get("version") != 1:
            raise StudioError("backup_version", "Backup made by a newer version", version=doc.get("version"))

        out: list[tuple[dict[str, Any], bytes, bytes]] = []
        seen: set[str] = set()
        now = int(time.time())
        for item in doc["designs"]:
            if not isinstance(item, dict) or not str(item.get("id", "")).isalnum():
                raise StudioError("backup_invalid", "Damaged design entry")
            params = item.get("params")
            if not isinstance(params, dict):
                raise StudioError("backup_invalid", "Damaged design entry")
            if check_params is not None:
                try:
                    params = check_params(params)
                except Exception as exc:  # noqa: BLE001 - e.g. a pydantic ValidationError
                    raise StudioError("backup_invalid", "Invalid design settings") from exc
            name = str(item.get("name", "")).strip()[:60] or "Untitled"
            if name.casefold() in seen:
                continue  # the same name twice in one backup: the first one wins
            seen.add(name.casefold())
            source = member(f"designs/{item['id']}/source.png")
            thumb = member(f"designs/{item['id']}/thumb.png")
            width, height = _png_size(source)
            _png_size(thumb)
            created = item["created"] if isinstance(item.get("created"), int) else now
            updated = item["updated"] if isinstance(item.get("updated"), int) else now
            meta = {
                "id": item["id"],
                "name": name,
                "params": params,
                "width": width,
                "height": height,
                "created": created,
                "updated": updated,
            }
            out.append((meta, source, thumb))
        return out
