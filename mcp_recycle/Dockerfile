FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY agent/pyproject.toml agent/pyproject.toml
COPY mcp_recycle/pyproject.toml mcp_recycle/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-workspace --package mcp-recycle

COPY mcp_recycle mcp_recycle
RUN uv sync --frozen --no-dev --package mcp-recycle

EXPOSE 8001
CMD ["python", "-m", "recycle_schedule.server"]
