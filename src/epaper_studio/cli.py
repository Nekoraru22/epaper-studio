"""Command line entry point: ``epaper-studio``."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from epaper_studio import __version__
from epaper_studio.config import ENV_FILE, ENV_TEMPLATE, Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epaper-studio",
        description="Prepare images for Gicisky e-paper tags and send them over Bluetooth.",
    )
    parser.add_argument("--host", help="address to listen on (default: HOST or 0.0.0.0)")
    parser.add_argument("--port", type=int, help="port to listen on (default: PORT or 8080)")
    parser.add_argument("--ssl-certfile", help="HTTPS certificate (default: SSL_CERTFILE)")
    parser.add_argument("--ssl-keyfile", help="HTTPS private key (default: SSL_KEYFILE)")
    parser.add_argument("--data-dir", type=Path, help="where names and designs are kept (default: DATA_DIR)")
    parser.add_argument("--env-file", type=Path, default=ENV_FILE, help="settings file (default: ./.env)")
    parser.add_argument("--init", action="store_true", help="write a commented .env file and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def write_env_template(path: Path) -> int:
    if path.exists():
        print(f"{path} already exists; leaving it untouched.")
        return 1
    path.write_text(ENV_TEMPLATE, encoding="utf-8")
    print(f"Created {path}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.init:
        return write_env_template(args.env_file)

    settings = Settings.load(args.env_file)
    if args.host:
        settings = replace(settings, host=args.host)
    if args.port:
        settings = replace(settings, port=args.port)
    if args.ssl_certfile:
        settings = replace(settings, ssl_certfile=args.ssl_certfile)
    if args.ssl_keyfile:
        settings = replace(settings, ssl_keyfile=args.ssl_keyfile)
    if args.data_dir:
        settings = replace(settings, data_dir=args.data_dir)

    import uvicorn

    from epaper_studio.gicisky.scanner import ble_problem
    from epaper_studio.web.app import create_app

    problem = ble_problem()
    scheme = "https" if settings.https else "http"
    print(f"E-Paper Studio {__version__} on {scheme}://{settings.host}:{settings.port}")
    print(f"Bluetooth: {problem.message if problem else 'bleak ready'}")
    print(f"Data:      {settings.data_dir}")
    if not settings.https:
        print("HTTPS:     off (\"This device\" Bluetooth only works on localhost; see README)")
    if settings.tag_address:
        print(f"Tag:       {settings.tag_address}")
    if not settings.auth_enabled:
        print("Login:     off (AUTH_PASSWORD is empty): anyone who can reach the port can use it")
    else:
        print(f"Login:     {settings.auth_username}")
    if settings.auth_password == Settings.auth_password:
        print("WARNING:   the default password is in use; set AUTH_PASSWORD in .env")
    tls = {"ssl_certfile": settings.ssl_certfile, "ssl_keyfile": settings.ssl_keyfile} if settings.https else {}
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning", **tls)
    return 0
