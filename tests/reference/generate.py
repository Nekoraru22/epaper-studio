"""Regenerate ``hass_gicisky_digests.json`` from the reference implementation.

The packing tests compare our output with hass-gicisky
(https://github.com/eigger/hass-gicisky, MIT), the integration this project's
protocol knowledge comes from. Rather than vendoring its code, we store the
SHA-256 of what its ``GiciskyClient._make_image_packet`` produces for a
deterministic random image per model.

    git clone https://github.com/eigger/hass-gicisky /tmp/hass-gicisky
    uv run python tests/reference/generate.py /tmp/hass-gicisky
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from images import model_image  # noqa: E402

from epaper_studio.gicisky.models import get_model  # noqa: E402


def load_reference(repo: Path) -> tuple[types.ModuleType, types.ModuleType]:
    src = repo / "custom_components/gicisky/gicisky_ble"
    pkg = types.ModuleType("gb")
    pkg.__path__ = [str(src)]
    sys.modules["gb"] = pkg
    sys.modules["bleak_retry_connector"] = types.SimpleNamespace(establish_connection=None)
    for name in ("devices", "compression", "writer"):
        spec = importlib.util.spec_from_file_location(f"gb.{name}", src / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"gb.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["gb.devices"], sys.modules["gb.writer"]


def main(repo: Path) -> None:
    devices, writer = load_reference(repo)
    out: dict[str, object] = {}
    for dev_id, entry in sorted(devices.DEVICE_TYPES.items()):
        model = get_model(dev_id)
        if model is None or entry.compression2:
            continue
        img = model_image(dev_id, model)
        client = writer.GiciskyClient.__new__(writer.GiciskyClient)
        for k in ("width", "height", "tft", "rotation", "mirror_x", "mirror_y", "compression",
                  "compression2", "invert_luminance", "four_color"):
            setattr(client, k, getattr(entry, k))
        client.support_red = entry.red
        data = bytes(client._make_image_packet(img))
        out[f"0x{dev_id:04X}"] = {"name": model.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    git = ["git", "-C", str(repo), "rev-parse", "HEAD"]
    commit = subprocess.run(git, capture_output=True, text=True).stdout.strip()
    doc = {"source": "https://github.com/eigger/hass-gicisky", "commit": commit or "unknown", "models": out}
    (HERE / "hass_gicisky_digests.json").write_text(json.dumps(doc, indent=2) + "\n")
    print(f"{len(out)} models written")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
