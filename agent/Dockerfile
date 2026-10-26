FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 先只裝相依套件（利於 layer cache）；workspace 需要所有成員的 pyproject
COPY pyproject.toml uv.lock ./
COPY agent/pyproject.toml agent/pyproject.toml
COPY mcp_recycle/pyproject.toml mcp_recycle/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-workspace --package recycle-agent

COPY agent agent
COPY scripts scripts
COPY data data
COPY skills skills
COPY public public
COPY .chainlit .chainlit
COPY chainlit.md chainlit.md
RUN uv sync --frozen --no-dev --package recycle-agent

EXPOSE 8000
CMD ["chainlit", "run", "agent/recycle_agent/app.py", "--host", "0.0.0.0", "--port", "8000"]
