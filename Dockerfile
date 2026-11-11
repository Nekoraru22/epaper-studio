# E-Paper Studio. See "Docker" in the README for how to run it with Bluetooth.

# -- build: install the locked dependencies and the app into /app/.venv ----------
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, so editing the code does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# -- runtime -------------------------------------------------------------------
FROM python:3.13-slim
WORKDIR /app
COPY --from=build /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    DATA_DIR=/data

# Runs as root: BlueZ only lets root (or the host's "bluetooth" group) drive the
# adapter over D-Bus, and the container has no access to anything else of the host.
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os,ssl,urllib.request as u; s='https' if os.environ.get('SSL_CERTFILE') else 'http'; u.urlopen(s+'://127.0.0.1:8080/login', context=ssl._create_unverified_context(), timeout=4)"]

CMD ["epaper-studio"]
