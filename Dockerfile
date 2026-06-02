# syntax=docker/dockerfile:1.7
# CRITICAL Phase 1 NEEDS-PIVOT: cloakbrowser requires libnspr4 + libnss3
# These are NOT bundled in the cloakbrowser wheel. Must install in runtime image.

# --- builder ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# --- runtime ---
# DEPLOY-01 pin: cloakhq/cloakbrowser:0.3.31
FROM cloakhq/cloakbrowser:0.3.31 AS runtime
# D1 pin: chromium-v146.0.7680.177.5
# Phase 1 NEEDS-PIVOT: system deps required — absent in the wheel, needed at runtime
# SPIKE.md §Risks confirmed: "libnspr4 + libnss3 are NOT bundled in the cloakbrowser wheel"
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnspr4 \
    libnss3 \
    tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# DEPLOY-04: tini for zombie reaping (Chromium leaks defunct procs without PID-1 init)
ENTRYPOINT ["/usr/bin/tini", "--"]

# D6 FOOT-GUN: --loop asyncio --workers 1 ALWAYS. Never uvloop.
# DEPLOY-03: uvicorn CMD must use --loop asyncio and --workers 1.
CMD ["uvicorn", "src.artiscrapper.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--loop", "asyncio"]
