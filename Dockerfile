# syntax=docker/dockerfile:1

# Server image only — the `gui` mode (PySide6) needs a display and isn't a
# container use case. `uv sync` (no --extra) already skips the `gui` extra,
# so PySide6/Qt never gets installed here.
#
# Both stages use the same hardened base so the venv's `python` symlink
# (which points at the builder's interpreter path) still resolves at
# runtime. The image has no shell/package manager, so `uv sync` below is
# exec-form (no `/bin/sh -c` wrapper needed) — same reason `CMD` is exec-form.

FROM dhi.io/python:3.13.15-debian13 AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
RUN ["/bin/uv", "sync", "--frozen", "--no-dev"]


FROM dhi.io/python:3.13.15-debian13

# hardened image: no shell/package manager, runs as `nonroot` (uid 65532) by
# default already — nothing to apt-get or useradd here.
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY main.py ./
COPY app ./app

# pre-create rembg's model cache dir owned by nonroot (uid 65532): a fresh
# named volume mounted here would otherwise be root-owned and unwritable —
# docker seeds a new volume from whatever already exists at that path
RUN ["/usr/bin/python", "-c", "import os; d='/home/nonroot/.rembg/models'; os.makedirs(d, exist_ok=True); [os.chown(p, 65532, 65532) for p in ('/home/nonroot/.rembg', d)]"]

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
