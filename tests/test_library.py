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


def _make(library: Library, name: str, colour: str) -> dict:
    src = Image.new("RGB", (32, 24), colour)
    return library.create_design(name, {"dither": "none"}, src, Image.new("RGB", (40, 30)))


def test_export_import_merge_overwrites_same_name(library: Library) -> None:
    _make(library, "Door", "red")
    _make(library, "Desk", "blue")
    backup = library.export_designs()

    other = Library()
    kept = _make(other, "door", "green")  # same name, different case: gets overwritten
    _make(other, "Kitchen", "white")
    assert other.import_designs(backup, "merge") == {"added": 1, "replaced": 1}
    names = sorted(d["name"] for d in other.designs())
    assert names == ["Desk", "Door", "Kitchen"]
    door = next(d for d in other.designs() if d["name"] == "Door")
    assert door["id"] == kept["id"]
    assert other.design_source(door["id"]).getpixel((0, 0)) == (255, 0, 0)


def test_import_replace_deletes_everything_first(library: Library) -> None:
    _make(library, "Door", "red")
    backup = library.export_designs()
    other = Library()
    _make(other, "Kitchen", "white")
    assert other.import_designs(backup, "replace") == {"added": 1, "replaced": 0}
    assert [d["name"] for d in other.designs()] == ["Door"]


def test_import_rejects_bad_files(library: Library) -> None:
    _make(library, "Door", "red")
    with pytest.raises(StudioError) as err:
        library.import_designs(b"not a zip", "replace")
    assert err.value.code == "backup_invalid"
    assert len(library.designs()) == 1  # nothing was deleted


def test_backup_api(tmp_path, photo_png: bytes) -> None:
    from fastapi.testclient import TestClient

    from epaper_studio.config import Settings
    from epaper_studio.web.app import create_app

    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        image = c.post("/api/image", content=photo_png, headers={"Content-Type": "image/png"}).json()["id"]
        c.post("/api/designs", json={"image": image, "name": "Logo"})
        res = c.get("/api/designs/export")
        assert res.headers["content-type"] == "application/zip"
        assert "attachment" in res.headers["content-disposition"]
        out = c.post("/api/designs/import?mode=merge", content=res.content).json()
        assert out["replaced"] == 1
        assert len(out["designs"]) == 1
        bad = c.post("/api/designs/import?mode=merge", content=b"junk")
        assert bad.json()["detail"]["code"] == "backup_invalid"
