"""HTTP API and static web UI.

Errors are returned as ``{"detail": {"code", "message", "params"}}`` so the UI
can translate them (see :mod:`epaper_studio.errors`).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from epaper_studio import __version__
from epaper_studio.config import Settings
from epaper_studio.errors import StudioError
from epaper_studio.gicisky.models import MODELS, get_model, parse_advert
from epaper_studio.gicisky.protocol import Job, ble_error, transfer
from epaper_studio.gicisky.scanner import ble_problem, scan
from epaper_studio.imaging import INK, PURE, Params
from epaper_studio.library import Library
from epaper_studio.service import fit_params_to_model, prepare_label
from epaper_studio.web.schemas import DesignCreate, DesignUpdate, DeviceRequest, RenderRequest, SendRequest
from epaper_studio.web.store import ImageStore, JobRegistry

STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD = 40 * 1024 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="E-Paper Studio", version=__version__, docs_url="/api/docs", redoc_url=None)

    images = ImageStore()
    library = Library(settings.data_dir)
    jobs = JobRegistry()
    ble_lock = asyncio.Lock()
    last_sent: dict[str, str] = {}  # tag address -> digest of the last image sent

    @app.exception_handler(StudioError)
    async def studio_error(_request: Request, exc: StudioError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.to_dict()})

    def require_ble() -> None:
        problem = ble_problem()
        if problem:
            raise problem

    # -- configuration -------------------------------------------------------
    @app.get("/api/config")
    def config() -> dict[str, Any]:
        problem = ble_problem()
        return {
            "version": __version__,
            "tag_address": settings.tag_address,
            "https": settings.https,
            "persistent": settings.data_dir is not None,
            "ble_error": problem.to_dict() if problem else None,
            "models": {f"0x{k:04X}": {"name": m.name, "width": m.width, "height": m.height,
                                      "palette": m.palette, "supported": m.supported}
                       for k, m in MODELS.items()},
        }

    # -- tags ------------------------------------------------------------------
    @app.get("/api/scan")
    async def scan_tags(seconds: float = 6.0) -> list[dict[str, Any]]:
        require_ble()
        if ble_lock.locked():
            raise StudioError("busy", "An upload is in progress", status=409)
        async with ble_lock:
            try:
                return await scan(max(2.0, min(seconds, 20.0)))
            except Exception as exc:  # noqa: BLE001
                error, _ = ble_error(exc)
                error.status = 503
                raise error from exc

    @app.get("/api/advert")
    def advert(data: str) -> dict[str, Any]:
        """Decode advert bytes captured by the browser (hex), so parsing lives in one place."""
        try:
            info = parse_advert(bytes.fromhex(data))
        except ValueError:
            info = None
        if info is None:
            raise StudioError("invalid_request", "Expected 5 bytes of hex")
        return info

    # -- saved devices ---------------------------------------------------------
    @app.get("/api/devices")
    def list_devices() -> list[dict[str, Any]]:
        return library.devices()

    @app.post("/api/devices")
    def save_device(body: DeviceRequest) -> dict[str, Any]:
        return library.save_device(body.transport, body.address, name=body.name, group=body.group,
                                   model_id=body.model_id, ble_name=body.ble_name)

    @app.delete("/api/devices/{key}")
    def forget_device(key: str) -> dict[str, Any]:
        library.forget_device(key)
        return {"ok": True}

    # -- saved designs ---------------------------------------------------------
    def preview_of(image: Any, params: Params) -> Any:
        return prepare_label(image, params.model_copy(update={"view": "ink"})).image.to_image(INK)

    @app.get("/api/designs")
    def list_designs() -> list[dict[str, Any]]:
        return library.designs()

    @app.post("/api/designs")
    async def create_design(body: DesignCreate) -> dict[str, Any]:
        source = images.get(body.image)
        preview = await asyncio.to_thread(preview_of, source, body.params)
        return library.create_design(body.name, body.params.model_dump(), source, preview)

    @app.patch("/api/designs/{design_id}")
    async def update_design(design_id: str, body: DesignUpdate) -> dict[str, Any]:
        meta = library.design(design_id)
        source = images.get(body.image) if body.image else None
        params = body.params
        preview = None
        if source is not None or params is not None:
            base = source if source is not None else library.design_source(design_id)
            params = params or Params(**meta["params"])
            preview = await asyncio.to_thread(preview_of, base, params)
        return library.update_design(design_id, name=body.name,
                                     params=params.model_dump() if params is not None else None,
                                     source=source, preview=preview)

    @app.delete("/api/designs/{design_id}")
    def delete_design(design_id: str) -> dict[str, Any]:
        library.delete_design(design_id)
        return {"ok": True}

    @app.get("/api/designs/{design_id}/thumb.png")
    def design_thumb(design_id: str) -> Response:
        return Response(library.design_thumb(design_id), media_type="image/png",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/api/designs/{design_id}/source.png")
    def design_source(design_id: str) -> Response:
        return Response(library.design_source_bytes(design_id), media_type="image/png",
                        headers={"Cache-Control": "no-cache"})

    @app.post("/api/designs/{design_id}/open")
    def open_design(design_id: str) -> dict[str, Any]:
        """Load a design into the editor: returns a fresh image id and its parameters."""
        meta = library.design(design_id)
        key, img = images.add_image(library.design_source(design_id))
        return {"image": {"id": key, "width": img.width, "height": img.height}, "design": meta}

    # -- images ----------------------------------------------------------------
    @app.post("/api/image")
    async def upload_image(request: Request) -> dict[str, Any]:
        raw = await request.body()
        if not raw:
            raise StudioError("no_image", "No image received")
        if len(raw) > MAX_UPLOAD:
            raise StudioError("image_too_large", "The image is larger than 40 MB", status=413, limit_mb=40)
        key, img = images.add(raw)
        return {"id": key, "width": img.width, "height": img.height}

    @app.post("/api/render")
    def render(body: RenderRequest) -> Response:
        """Preview as PNG. Statistics travel in the ``X-Stats`` header."""
        result = prepare_label(images.get(body.id), body.params)
        view = body.params.view
        if view == "tone":
            out = result.image.tone_image()
        else:
            out = result.image.to_image(INK if view == "ink" else PURE)
        buf = io.BytesIO()
        out.save(buf, format="PNG", compress_level=1)
        return Response(buf.getvalue(), media_type="image/png",
                        headers={"Cache-Control": "no-store", "X-Stats": json.dumps(result.stats)})

    @app.post("/api/packed")
    def packed(body: RenderRequest) -> dict[str, Any]:
        """The exact buffer that would be uploaded, for the data view."""
        result = prepare_label(images.get(body.id), body.params)
        return {"stats": result.stats, "layout": result.layout,
                "data": base64.b64encode(result.data).decode("ascii")}

    # -- uploads ---------------------------------------------------------------
    @app.post("/api/send")
    async def send(body: SendRequest) -> dict[str, Any]:
        require_ble()
        model = get_model(body.model)
        if model is None:
            raise StudioError("unknown_model", "Unknown model", model=f"0x{body.model:04X}")
        if not model.supported:
            raise StudioError("unsupported_model", "Model not supported", model=model.name)
        if ble_lock.locked():
            raise StudioError("busy", "An upload is in progress", status=409)

        params = fit_params_to_model(body.params, body.model, model)
        result = await asyncio.to_thread(prepare_label, images.get(body.id), params)
        data = result.data

        address = body.address.strip().upper()
        digest = hashlib.sha1(data).hexdigest()
        if not body.force and last_sent.get(address) == digest:
            return {"duplicate": True}

        job = jobs.add(Job(address, len(data)))

        async def worker() -> None:
            async with ble_lock:
                await transfer(job, data, write_delay=settings.ble_write_delay)
            if job.status == "ok":
                last_sent[address] = digest

        app.state.background = asyncio.create_task(worker())  # keep a reference
        return {"job": job.id, "bytes": len(data), "blocks": job.blocks}

    @app.get("/api/jobs/{job_id}")
    def job_state(job_id: str, since: int = 0) -> dict[str, Any]:
        return jobs.get(job_id).view(since)

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
