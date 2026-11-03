# All-in-one Hugging Face Space (Docker SDK, app_port 7860):
# FastAPI demo backend on 127.0.0.1:8000, Next.js frontend on 0.0.0.0:7860.
# Next's server components/actions talk to the backend via BACKEND_URL
# (defaults to http://127.0.0.1:8000); /api/* and /healthz are proxied
# through the frontend for public access.
FROM node:26-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
# node's binary (copied from the node image) links against libatomic; postgres
# powers the embedded demo database (deploy/space-entrypoint.sh)
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 postgresql \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local /usr/local
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
# src must precede the sync: uv builds the app wheel from the project dir, so a
# missing src/ yields an empty wheel. --no-editable: uv's editable installs only
# register metadata and expect `uv run` to inject the source path at runtime;
# the container starts uvicorn directly.
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
COPY migrations ./migrations
COPY evals ./evals
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY --from=web /web/.next /web/.next
COPY --from=web /web/node_modules /web/node_modules
COPY --from=web /web/package.json /web/next.config.ts /web/
COPY deploy/space-entrypoint.sh /app/space-entrypoint.sh
WORKDIR /web
EXPOSE 7860
CMD ["sh", "/app/space-entrypoint.sh"]
