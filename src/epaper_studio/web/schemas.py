"""Request bodies of the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from epaper_studio.imaging import Params


class RenderRequest(BaseModel):
    id: str = Field(description="Image id returned by POST /api/image")
    params: Params = Field(default_factory=Params)


class SendRequest(BaseModel):
    id: str = Field(description="Image id returned by POST /api/image")
    address: str = Field(description="BLE address of the tag")
    model: int = Field(description="Gicisky model id, from the scan result")
    params: Params = Field(default_factory=Params)
    force: bool = Field(False, description="Send even if the tag already shows this image")


class DeviceRequest(BaseModel):
    transport: Literal["server"] = Field(
        "server", description="Only tags reached by the server's Bluetooth are stored; browser tags stay in the page"
    )
    address: str = Field(min_length=1, max_length=200, description="MAC address, or the browser's device id")
    name: str = Field("", max_length=60, description="Name chosen by the user")
    group: str = Field("", max_length=40, description="Free-form group, e.g. a room")
    model_id: int | None = Field(None, ge=0, le=0x3FFF, description="Gicisky model id, if known")
    ble_name: str = Field("", max_length=60, description="Name the tag advertises")


class DesignCreate(BaseModel):
    image: str = Field(description="Image id returned by POST /api/image")
    name: str = Field("", max_length=60)
    params: Params = Field(default_factory=Params)


class DesignUpdate(BaseModel):
    name: str | None = Field(None, max_length=60)
    image: str | None = Field(None, description="Replace the source image with this upload")
    params: Params | None = None
