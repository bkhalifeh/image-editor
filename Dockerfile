# syntax=docker/dockerfile:1

# Server image only — the `gui` mode (PySide6) needs a display and isn't a
# container use case.

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev


FROM python:3.13-slim

# onnxruntime (rembg) needs libgomp at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY main.py ./
COPY app ./app

ENV PATH="/app/.venv/bin:$PATH"
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
