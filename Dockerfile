FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Install deps first for layer caching (uv.lock is committed).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY migrations ./migrations
COPY evals ./evals
COPY README.md ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8080
# Factory mode: wires Neon + OpenAI from env when present, else the seeded demo.
CMD ["sh", "-c", "uvicorn email_task_agent.app.main:app_factory --factory --host 0.0.0.0 --port ${PORT:-7860}"]
