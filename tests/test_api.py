import json
import time

import pytest
from fastapi.testclient import TestClient

from epaper_studio.config import Settings
from epaper_studio.web.app import create_app


@pytest.fixture
def client():
    # The context manager keeps one event loop alive, so background uploads run.
    with TestClient(create_app(Settings(tag_address="AA:BB:CC:00:12:34"))) as c:
        yield c


def upload(client: TestClient, png: bytes) -> str:
    res = client.post("/api/image", content=png, headers={"Content-Type": "image/png"})
    assert res.status_code == 200
    return res.json()["id"]


def test_index_and_assets_are_served(client: TestClient) -> None:
    assert "E-Paper Studio" in client.get("/").text
    assert client.get("/js/main.js").status_code == 200
    assert client.get("/locales/es.json").json()["tags.scan"] == "Buscar"


def test_config(client: TestClient) -> None:
    cfg = client.get("/api/config").json()
    assert cfg["tag_address"] == "AA:BB:CC:00:12:34"
    assert cfg["models"]["0x004B"]["palette"] == "bwr"


def test_render_and_packed(client: TestClient, photo_png: bytes) -> None:
    image_id = upload(client, photo_png)
    res = client.post("/api/render", json={"id": image_id, "params": {"model": 0x004B}})
    assert res.headers["content-type"] == "image/png"
    stats = json.loads(res.headers["X-Stats"])
    assert stats["transport"]["total_bytes"] == 30000
    packed = client.post("/api/packed", json={"id": image_id, "params": {"model": 0x004B}}).json()
    assert packed["layout"]["row_bytes"] == 50


def test_errors_carry_codes(client: TestClient) -> None:
    res = client.post("/api/image", content=b"not an image")
    assert res.status_code == 415
    assert res.json()["detail"]["code"] == "not_an_image"
    res = client.post("/api/render", json={"id": "missing"})
    assert res.status_code == 404 and res.json()["detail"]["code"] == "image_expired"
    assert client.get("/api/jobs/nope").json()["detail"]["code"] == "job_unknown"


def test_send_follow_and_duplicate(client: TestClient, photo_png: bytes, fake_ble) -> None:
    image_id = upload(client, photo_png)
    body = {"id": image_id, "address": fake_ble.ADDRESS, "model": 0x004B}
    started = client.post("/api/send", json=body).json()
    assert started["blocks"] == 125
    for _ in range(200):
        view = client.get(f"/api/jobs/{started['job']}").json()
        if view["status"] != "running":
            break
        time.sleep(0.05)
    assert view["status"] == "ok", view["error"]
    assert client.post("/api/send", json=body).json() == {"duplicate": True}
    assert "job" in client.post("/api/send", json={**body, "force": True}).json()


def test_scan_finds_the_fake_tag(client: TestClient, fake_ble) -> None:
    tags = client.get("/api/scan?seconds=2").json()
    assert [t["address"] for t in tags] == [fake_ble.ADDRESS]
    assert tags[0]["model_id"] == 0x004B
