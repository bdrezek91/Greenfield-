FROM python:3.11.15-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_NO_CACHE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.12.1

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --all-extras --locked

COPY . .

CMD ["sleep", "infinity"]
