"""Run the web UI against the simulated tag, for development without hardware.

    uv run python tests/run_fake_server.py [port]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn  # noqa: E402

import fake_tag  # noqa: E402
from epaper_studio.config import Settings  # noqa: E402
from epaper_studio.web.app import create_app  # noqa: E402

if __name__ == "__main__":
    fake_tag.install()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"Fake tag {fake_tag.ADDRESS} · http://127.0.0.1:{port}")
    uvicorn.run(create_app(Settings()), host="127.0.0.1", port=port, log_level="warning")
