"""Runtime settings, read from environment variables and an optional ``.env`` file."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = Path(".env")

ENV_TEMPLATE = """\
# E-Paper Studio configuration. Every setting is optional.

# Where the editor listens. 0.0.0.0 = any device on your network,
# 127.0.0.1 = this machine only. Never expose it directly to the internet.
HOST=0.0.0.0
PORT=8080

# Login for the web page. CHANGE THE PASSWORD: the default is admin / patatuelas.
# Leave AUTH_PASSWORD empty (AUTH_PASSWORD=) to turn the login off entirely.
AUTH_USERNAME=admin
AUTH_PASSWORD=patatuelas

# How long a login lasts, in days. It is renewed while you keep using the page.
SESSION_DAYS=30

# Key that signs the login cookie. Leave empty to generate one and keep it in
# DATA_DIR/secret.key. Changing it (or the password) signs everyone out.
SECRET_KEY=

# MAC address of the tag selected when the page opens (optional; you can
# also scan from the UI). It is the one bluetoothctl shows, e.g. AA:BB:CC:DD:EE:FF
TAG_ADDRESS=

# Pause between BLE writes in milliseconds. Raise it (20-50) only if
# transfers keep dropping halfway.
BLE_WRITE_DELAY_MS=0

# Where device names and saved designs are kept.
# Default: $XDG_DATA_HOME/epaper-studio (usually ~/.local/share/epaper-studio)
DATA_DIR=

# HTTPS. Browsers only allow Bluetooth from the page itself ("This device")
# over HTTPS or on localhost. Point these at a certificate and its key.
SSL_CERTFILE=
SSL_KEYFILE=
"""


def default_data_dir(env: Mapping[str, str]) -> Path:
    base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "epaper-studio"


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a minimal ``.env`` file: ``KEY=value`` lines, ``#`` comments, optional quotes."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8080
    tag_address: str = ""
    ble_write_delay: float = 0.0  # seconds
    data_dir: Path | None = None  # None: keep everything in memory (tests)
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    auth_username: str = "admin"
    auth_password: str = "patatuelas"
    session_days: float = 30.0
    secret_key: str = ""  # empty: generated, kept in data_dir/secret.key

    @property
    def auth_enabled(self) -> bool:
        """An empty password turns the login off."""
        return bool(self.auth_password)

    @property
    def https(self) -> bool:
        return bool(self.ssl_certfile and self.ssl_keyfile)

    @classmethod
    def load(cls, env_file: Path | None = ENV_FILE, environ: Mapping[str, str] | None = None) -> Settings:
        """Build settings; real environment variables win over the ``.env`` file."""
        file_values = parse_env_file(env_file) if env_file else {}
        env = os.environ if environ is None else environ

        def get(name: str, default: str) -> str:
            return env.get(name) or file_values.get(name) or default

        def get_allow_empty(name: str, default: str) -> str:
            """Like ``get``, but a variable that is present and empty means "empty", not "default"."""
            if name in env:
                return env[name]
            return file_values.get(name, default)

        return cls(
            host=get("HOST", cls.host),
            port=int(get("PORT", str(cls.port))),
            tag_address=get("TAG_ADDRESS", "").upper(),
            ble_write_delay=float(get("BLE_WRITE_DELAY_MS", "0") or 0) / 1000,
            data_dir=Path(get("DATA_DIR", "")).expanduser() if get("DATA_DIR", "") else default_data_dir(env),
            ssl_certfile=get("SSL_CERTFILE", ""),
            ssl_keyfile=get("SSL_KEYFILE", ""),
            auth_username=get("AUTH_USERNAME", cls.auth_username),
            auth_password=get_allow_empty("AUTH_PASSWORD", cls.auth_password),
            session_days=float(get("SESSION_DAYS", str(cls.session_days))),
            secret_key=get("SECRET_KEY", ""),
        )
