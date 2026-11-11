"""Username and password login, kept in a signed cookie.

The cookie holds ``<username>.<expiry>.<signature>``. The signature is an
HMAC over the username, the expiry and a fingerprint of the password, keyed
with a secret. Nothing is stored on the server, sessions survive restarts, and
changing the password or the secret signs everyone out.

Every request goes through :func:`install`'s middleware: API calls without a
valid session get ``401`` with code ``auth_required``; pages redirect to
``/login``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from epaper_studio.config import Settings
from epaper_studio.errors import StudioError

COOKIE = "eps_session"
LOGIN_PAGE = Path(__file__).parent / "static" / "login.html"
# Reachable without a session: the login page, what it loads, and the login call itself.
PUBLIC_PATHS = {"/login", "/api/login", "/api/logout", "/api/session"}
PUBLIC_PREFIXES = ("/css/", "/locales/")


def load_secret(settings: Settings) -> bytes:
    """``SECRET_KEY`` if set; otherwise a random key kept in ``data_dir/secret.key``."""
    if settings.secret_key:
        return settings.secret_key.encode()
    if settings.data_dir is None:
        return secrets.token_bytes(32)  # memory mode (tests): sessions end with the process
    path = Path(settings.data_dir) / "secret.key"
    try:
        key = path.read_bytes().strip()
        if len(key) >= 32:
            return key
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


class Sessions:
    def __init__(self, settings: Settings):
        self.username = settings.auth_username
        self.password = settings.auth_password
        self.lifetime = max(60, int(settings.session_days * 86400))
        self.secure = settings.https
        self._key = load_secret(settings)
        self._fingerprint = hashlib.sha256(f"{self.username}\0{self.password}".encode()).hexdigest()

    def check_credentials(self, username: str, password: str) -> bool:
        # Compare both, always, in constant time: no hint about which one was wrong.
        user_ok = hmac.compare_digest(username.encode(), self.username.encode())
        pass_ok = hmac.compare_digest(password.encode(), self.password.encode())
        return user_ok and pass_ok

    def _sign(self, user: str, expiry: int) -> str:
        msg = f"{user}\0{expiry}\0{self._fingerprint}".encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()

    def issue(self) -> str:
        expiry = int(time.time()) + self.lifetime
        user = base64.urlsafe_b64encode(self.username.encode()).decode().rstrip("=")
        return f"{user}.{expiry}.{self._sign(self.username, expiry)}"

    def verify(self, token: str | None) -> int | None:
        """Seconds left on a valid session, or ``None``."""
        if not token or token.count(".") != 2:
            return None
        user_b64, expiry_s, sig = token.split(".")
        try:
            user = base64.urlsafe_b64decode(user_b64 + "=" * (-len(user_b64) % 4)).decode()
            expiry = int(expiry_s)
        except ValueError:
            return None
        if not hmac.compare_digest(sig, self._sign(user, expiry)) or user != self.username:
            return None
        left = expiry - int(time.time())
        return left if left > 0 else None

    def set_cookie(self, response: Response) -> None:
        response.set_cookie(
            COOKIE, self.issue(), max_age=self.lifetime, httponly=True, samesite="lax", secure=self.secure, path="/"
        )

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=self.secure)


def _safe_next(target: str | None) -> str:
    """Only allow redirects back into this site."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


def install(app: FastAPI, settings: Settings) -> Sessions:
    sessions = Sessions(settings)

    @app.middleware("http")
    async def require_login(request: Request, call_next):  # noqa: ANN001, ANN202 - Starlette signature
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        left = sessions.verify(request.cookies.get(COOKIE))
        if left is None:
            if path.startswith("/api/"):
                err = StudioError("auth_required", "Sign in first", status=401)
                return JSONResponse(status_code=401, content={"detail": err.to_dict()})
            nxt = path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(nxt, safe='/')}", status_code=303)
        response = await call_next(request)
        if left < sessions.lifetime / 2:  # sliding session: renew while it is being used
            sessions.set_cookie(response)
        return response

    @app.get("/login", include_in_schema=False)
    def login_page(request: Request) -> Response:
        if sessions.verify(request.cookies.get(COOKIE)) is not None:
            return RedirectResponse(_safe_next(request.query_params.get("next")), status_code=303)
        return FileResponse(LOGIN_PAGE, headers={"Cache-Control": "no-store"})

    @app.post("/api/login")
    async def login(request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise StudioError("invalid_request", "Expected username and password")
        username, password = str(body.get("username", "")), str(body.get("password", ""))
        if not sessions.check_credentials(username, password):
            await asyncio.sleep(1.0)  # slow down guessing
            raise StudioError("bad_credentials", "Wrong username or password", status=401)
        response = JSONResponse({"ok": True, "next": _safe_next(body.get("next"))})
        sessions.set_cookie(response)
        return response

    @app.post("/api/logout")
    def logout() -> Response:
        response = JSONResponse({"ok": True})
        sessions.clear_cookie(response)
        return response

    @app.get("/api/session")
    def session(request: Request) -> dict[str, object]:
        left = sessions.verify(request.cookies.get(COOKIE))
        return {"authenticated": left is not None, "username": sessions.username if left else None}

    return sessions
