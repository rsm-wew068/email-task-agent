FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Install deps first for layer caching (uv.lock is committed).
COPY pyproject.toml uv.lock ./
# Install the app package as a real wheel: --no-install-project would leave it
# unimportable, uv's default editable install needs `uv run` to inject the source
# path, and src/ must precede the sync or the wheel builds empty. README.md
# precedes the sync because hatchling needs it.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

COPY migrations ./migrations
COPY evals ./evals

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8080
# Factory mode: wires Neon + OpenAI from env when present, else the seeded demo.
CMD ["sh", "-c", "uvicorn email_task_agent.app.main:app_factory --factory --host 0.0.0.0 --port ${PORT:-7860}"]
