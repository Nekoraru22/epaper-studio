import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epaper_studio.config import ENV_TEMPLATE, Settings
from epaper_studio.web import auth
from epaper_studio.web.app import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


def test_everything_needs_a_session(client: TestClient) -> None:
    res = client.get("/api/designs")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "auth_required"
    page = client.get("/", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/login?next=/")
    assert client.get("/js/main.js", follow_redirects=False).status_code == 303
    # The login page and what it needs stay public.
    assert "login" in client.get("/login").text
    assert client.get("/css/app.css").status_code == 200
    assert client.get("/locales/en.json").status_code == 200


def test_login_session_and_logout(client: TestClient) -> None:
    bad = client.post("/api/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    assert bad.json()["detail"]["code"] == "bad_credentials"

    ok = client.post("/api/login", json={"username": "admin", "password": "patatuelas", "next": "//evil.example"})
    assert ok.json() == {"ok": True, "next": "/"}  # open redirects are refused
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "max-age=2592000" in cookie  # 30 days: the session survives closing the browser
    assert client.get("/api/designs").status_code == 200
    assert client.get("/api/session").json() == {"authenticated": True, "username": "admin"}

    client.post("/api/logout")
    assert client.get("/api/designs").status_code == 401


def test_credentials_from_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("AUTH_USERNAME=neko\nAUTH_PASSWORD=s3cret\nSESSION_DAYS=7\n")
    s = Settings.load(env, environ={})
    assert (s.auth_username, s.auth_password, s.session_days) == ("neko", "s3cret", 7.0)
    with TestClient(create_app(s)) as c:
        assert c.post("/api/login", json={"username": "admin", "password": "patatuelas"}).status_code == 401
        assert c.post("/api/login", json={"username": "neko", "password": "s3cret"}).status_code == 200


def test_tokens_are_signed_and_expire(tmp_path: Path) -> None:
    sessions = auth.Sessions(Settings(data_dir=tmp_path))
    token = sessions.issue()
    assert sessions.verify(token)
    user, expiry, sig = token.split(".")
    assert sessions.verify(f"{user}.{int(expiry) + 999}.{sig}") is None  # tampered
    assert sessions.verify(f"{user}.{int(time.time()) - 1}.{sessions._sign('admin', int(time.time()) - 1)}") is None
    # The secret is kept, so sessions survive a restart; a new password ends them.
    assert auth.Sessions(Settings(data_dir=tmp_path)).verify(token)
    assert auth.Sessions(Settings(data_dir=tmp_path, auth_password="other")).verify(token) is None


def test_env_example_matches_template() -> None:
    example = Path(__file__).parent.parent / ".env.example"
    assert example.read_text(encoding="utf-8") == ENV_TEMPLATE, "regenerate .env.example from config.ENV_TEMPLATE"
