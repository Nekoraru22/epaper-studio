# Contributing

Thanks for helping! Bug reports with the tag's model id (shown in the tag list and in the explanation at the bottom of the page) are especially useful.

## Setup

```bash
uv sync
uv run pytest
uv run ruff check .
uv run python tests/run_fake_server.py    # UI against a simulated tag
```

## Guidelines

- Keep the layers apart: `imaging` knows nothing about tags, `gicisky` knows nothing about HTTP, `web` only wires things together.
- User-facing text never lives in Python. Raise `StudioError("some_code", "English fallback", param=value)` and add `error.some_code` to every locale. Upload progress works the same way, using `job.note.<code>` keys.
- The UI is plain ES modules with no build step. Strings go through `t("key", {params})`; markup uses `data-i18n` attributes.
- Run the tests before opening a pull request. `tests/test_i18n.py` will tell you about any missing translation.

## Adding a tag model

1. Add it to `MODELS` in `src/epaper_studio/gicisky/models.py` (size, rotation, mirroring, colours, compression flags). The model id is in the advert, see `parse_advert`.
2. If hass-gicisky supports it, regenerate the reference digests:
   ```bash
   git clone https://github.com/eigger/hass-gicisky /tmp/hass-gicisky
   uv run python tests/reference/generate.py /tmp/hass-gicisky
   ```
3. Add a row to the table in the README, and mention whether you tested it on real hardware.

## Adding a language

See [README → Adding a language](README.md#adding-a-language). Native speakers reviewing the existing Spanish text are welcome too.

## Commit messages

Short imperative subject (`Add 2.6" model`, `Fix block retry`), with details in the body if needed.
