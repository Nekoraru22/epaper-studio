"""In-memory stores for uploaded images and upload jobs."""

from __future__ import annotations

import io
import threading
import uuid
from collections import OrderedDict

from PIL import Image, ImageOps

from epaper_studio.errors import StudioError
from epaper_studio.gicisky.protocol import Job

WORKING_MAX = 2400  # longest side of the working copy, in pixels


class ImageStore:
    """Keeps the last few uploads, normalised to RGB and a sensible size."""

    def __init__(self, limit: int = 12):
        self._items: OrderedDict[str, Image.Image] = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def add(self, raw: bytes) -> tuple[str, Image.Image]:
        try:
            img = Image.open(io.BytesIO(raw))
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                flat = Image.new("RGBA", img.size, (255, 255, 255, 255))
                flat.alpha_composite(img)
                img = flat
            img = img.convert("RGB")
        except Exception as exc:  # noqa: BLE001 - any decoding failure means "not an image"
            raise StudioError("not_an_image", "Pillow cannot open this file", status=415) from exc
        return self.add_image(img)

    def add_image(self, img: Image.Image) -> tuple[str, Image.Image]:
        """Store an already decoded RGB image."""
        img.thumbnail((WORKING_MAX, WORKING_MAX), Image.LANCZOS)
        key = uuid.uuid4().hex[:12]
        with self._lock:
            self._items[key] = img
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
        return key, img

    def get(self, key: str) -> Image.Image:
        with self._lock:
            img = self._items.get(key)
            if img is None:
                raise StudioError("image_expired", "The image is no longer in memory", status=404)
            self._items.move_to_end(key)
            return img


class JobRegistry:
    """Recent upload jobs, so the UI can poll them."""

    def __init__(self, limit: int = 20):
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._limit = limit

    def add(self, job: Job) -> Job:
        self._jobs[job.id] = job
        while len(self._jobs) > self._limit:
            self._jobs.popitem(last=False)
        return job

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise StudioError("job_unknown", "Unknown upload", status=404)
        return job
