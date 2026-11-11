"""Every language must define the same keys, and every key the UI uses must exist."""

import json
import re
from pathlib import Path

import pytest

from conftest import STATIC

LOCALES = STATIC / "locales"
LANGS = sorted(p.stem for p in LOCALES.glob("*.json"))
EN = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
JS = {p.name: p.read_text(encoding="utf-8") for p in (STATIC / "js").glob("*.js")}
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def load(lang: str) -> dict[str, str]:
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def test_languages_are_registered_in_js() -> None:
    for lang in LANGS:
        assert re.search(rf"\b{lang}: \{{ label:", JS["i18n.js"]), f"{lang} missing from LANGUAGES"


@pytest.mark.parametrize("lang", LANGS)
def test_same_keys_and_placeholders(lang: str) -> None:
    other = load(lang)
    assert set(other) == set(EN), set(other) ^ set(EN)
    for key, text in EN.items():
        assert set(PLACEHOLDER.findall(other[key])) == set(PLACEHOLDER.findall(text)), key
        assert other[key].strip(), key


def test_static_markup_keys_exist() -> None:
    keys = re.findall(r'data-i18n(?:-\w+)?="([^"]+)"', HTML)
    assert keys
    assert [k for k in keys if k not in EN] == []


def test_literal_t_calls_exist() -> None:
    used = {k for src in JS.values() for k in re.findall(r'\bt\("([\w.]+)"', src)}
    used |= {k for src in JS.values() for k in re.findall(r'flash\("([\w.]+)"', src)}
    used |= {k for src in JS.values() for k in re.findall(r'setPlaceholder\("([\w.]+)"', src)}
    assert used
    assert sorted(k for k in used if k not in EN) == []


def test_generated_keys_exist() -> None:
    """Keys built from data (controls, options, presets, codes) are listed here explicitly."""
    from epaper_studio.imaging.params import Params

    fields = Params.model_fields
    for name in ("fit", "background", "palette", "dither"):
        for value in fields[name].annotation.__args__:
            assert f"option.{name}.{value}" in EN
    controls = re.findall(r'\{ k: "(\w+)"', JS["controls.js"])
    assert controls and all(f"control.{k}" in EN for k in controls)
    for preset in re.findall(r'\{ id: "(\w+)", set:', JS["controls.js"]):
        assert f"preset.{preset}" in EN and f"preset.{preset}.note" in EN
    for section in re.findall(r'\{ id: "(\w+)", items:', JS["controls.js"]):
        assert f"section.{section}" in EN
    for name in ("white", "black", "red", "yellow"):
        assert f"pigment.{name}" in EN
    for kind in ("bw", "red", "2bpp", "raw"):
        assert f"plane.{kind}" in EN


def _codes(pattern: str) -> set[str]:
    src = "\n".join(p.read_text() for p in (STATIC.parent.parent).rglob("*.py"))
    return set(re.findall(pattern, src))


def test_backend_error_codes_are_translated() -> None:
    codes = _codes(r'(?:StudioError|TransferError)\(\s*"(\w+)"') | _codes(r'super\(\).__init__\("(\w+)"')
    assert "tag_silent" in codes
    assert sorted(c for c in codes if f"error.{c}" not in EN) == []


def test_browser_error_codes_are_translated() -> None:
    codes = set(re.findall(r'CodeError\("(\w+)"', JS["webble.js"])) | {"web_generic", "web_mtu"}
    assert "web_cancelled" in codes
    assert sorted(c for c in codes if f"error.{c}" not in EN) == []
    notes = set(re.findall(r'(?:note|setPhase)\((?:"\w+", )?"(\w+)"', JS["webble.js"])) - {"error"}
    assert sorted(c for c in notes if f"job.note.{c}" not in EN) == []


def test_backend_note_codes_are_translated() -> None:
    codes = _codes(r'(?:note|set_phase)\((?:"\w+", )?"(\w+)"') - {"error"}
    assert "block_repeat" in codes
    assert sorted(c for c in codes if f"job.note.{c}" not in EN) == []


@pytest.mark.parametrize("lang", LANGS)
def test_explanation_partials_share_live_hooks(lang: str) -> None:
    def hooks(path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return sorted(re.findall(r'\b(?:id|data-live)="([^"]+)"', text))

    assert hooks(LOCALES / f"how.{lang}.html") == hooks(LOCALES / "how.en.html")
