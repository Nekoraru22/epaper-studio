# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-11-11

### Added
- **This device**: send from the browser's own Bluetooth (Web Bluetooth), next to the server's adapter. Same protocol, log and retries; the bytes are identical to the server path.
- Tag names and groups, plus a manually chosen model for browsers that cannot read adverts. Stored on the server, shown grouped.
- Saved designs: keep an image with its adjustments, reopen, update, rename, delete or resend in one tap.
- HTTPS support (`SSL_CERTFILE`/`SSL_KEYFILE`, `--ssl-certfile`/`--ssl-keyfile`) and `DATA_DIR`/`--data-dir`.
- Phone layout: floating send button, collapsed adjustment sections, pinch to zoom, tap for the data tooltip.

## [0.2.0] - 2026-11-11

### Added
- English and Spanish UI, detected from the browser and switchable live.
- Installable package with an `epaper-studio` command (`--host`, `--port`, `--env-file`, `--init`).
- Test suite: packing checked byte-for-byte against hass-gicisky, protocol run against a simulated tag, API and translation completeness tests.
- `tests/run_fake_server.py` to develop the UI without hardware.
- CI workflow (ruff + pytest).

### Changed
- Code, comments and documentation in English.
- Split the single `app.py` into `imaging`, `gicisky`, `service` and `web` packages, and the UI into ES modules.
- The API returns error and progress *codes* with parameters instead of sentences; the UI translates them.
- Upload status endpoint renamed from `/api/job/{id}` to `/api/jobs/{id}`.

### Fixed
- An error raised during an upload could crash the job logger instead of being reported.

## [0.1.0] - 2026-11-10

- First release (Spanish only, single file): image editor, dithering, data view and direct BLE upload.
