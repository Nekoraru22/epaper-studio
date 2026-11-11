import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from epaper_studio.config import Settings
from epaper_studio.errors import StudioError
from epaper_studio.library import Library, device_key
from epaper_studio.web.app import create_app


@pytest.fixture(params=["memory", "disk"])
def library(request, tmp_path) -> Library:
    return Library(None if request.param == "memory" else tmp_path)


def test_devices_round_trip(library: Library) -> None:
    rec = library.save_device("server", "aa:bb:cc:00:12:34", ble_name="NEMR00001234", model_id=0x4B)
    assert rec["address"] == "AA:BB:CC:00:12:34"
    assert rec["name"] == "NEMR00001234"  # falls back to the advertised name
    renamed = library.save_device("server", "AA:BB:CC:00:12:34", name="Kitchen door", group="Kitchen")
    assert renamed["key"] == rec["key"] and renamed["model_id"] == 0x4B and renamed["ble_name"] == "NEMR00001234"
    web = library.save_device("web", "Ab+/cd==", name="Fridge", group="Kitchen", model_id=0x33)
    assert "/" not in web["key"] and web["key"] == device_key("web", "Ab+/cd==")
    assert [d["name"] for d in library.devices()] == ["Fridge", "Kitchen door"]
    library.forget_device(web["key"])
    with pytest.raises(StudioError):
        library.forget_device(web["key"])


def test_devices_persist(tmp_path) -> None:
    Library(tmp_path).save_device("server", "AA:BB:CC:00:12:34", name="Hall")
    assert Library(tmp_path).devices()[0]["name"] == "Hall"


def test_damaged_devices_file_is_kept_aside(tmp_path) -> None:
    (tmp_path / "devices.json").write_text("{not json")
    assert Library(tmp_path).devices() == []
    assert (tmp_path / "devices.json.bak").exists()


def test_designs(library: Library) -> None:
    src = Image.new("RGB", (64, 48), "red")
    meta = library.create_design("Door sign", {"dither": "none"}, src, Image.new("RGB", (400, 300), "white"))
    assert library.designs()[0]["id"] == meta["id"]
    assert library.design_source(meta["id"]).size == (64, 48)
    assert Image.open(__import__("io").BytesIO(library.design_thumb(meta["id"]))).width == 320
    updated = library.update_design(meta["id"], name="Front door")
    assert updated["name"] == "Front door" and updated["params"] == {"dither": "none"}
    library.delete_design(meta["id"])
    assert library.designs() == []
    with pytest.raises(StudioError):
        library.design(meta["id"])


def test_design_ids_cannot_escape(tmp_path) -> None:
    with pytest.raises(StudioError):
        Library(tmp_path).design("../../etc")


def test_api(tmp_path, photo_png: bytes) -> None:
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        dev = c.post("/api/devices", json={"transport": "web", "address": "x/y==", "name": "Desk"}).json()
        assert c.get("/api/devices").json()[0]["name"] == "Desk"
        assert c.delete(f"/api/devices/{dev['key']}").json() == {"ok": True}

        image = c.post("/api/image", content=photo_png).json()["id"]
        params = {"dither": "atkinson", "model": 0x4B}
        design = c.post("/api/designs", json={"image": image, "name": "Logo", "params": params}).json()
        assert design["params"]["dither"] == "atkinson"
        assert c.get(f"/api/designs/{design['id']}/thumb.png").headers["content-type"] == "image/png"
        changed = c.patch(f"/api/designs/{design['id']}", json={"params": {**params, "dither": "none"}}).json()
        assert changed["params"]["dither"] == "none"
        opened = c.post(f"/api/designs/{design['id']}/open").json()
        assert opened["design"]["name"] == "Logo"
        render = {"id": opened["image"]["id"], "params": opened["design"]["params"]}
        assert c.post("/api/render", json=render).status_code == 200
        assert c.get(f"/api/designs/{design['id']}/source.png").headers["content-type"] == "image/png"
        assert json.loads((tmp_path / "designs" / design["id"] / "meta.json").read_text())["name"] == "Logo"
        assert c.delete(f"/api/designs/{design['id']}").json() == {"ok": True}
        assert c.get(f"/api/designs/{design['id']}/thumb.png").json()["detail"]["code"] == "design_unknown"

        assert c.get("/api/advert?data=4b1e810140").json()["model_id"] == 0x4B
        assert c.get("/api/advert?data=zz").status_code == 400
