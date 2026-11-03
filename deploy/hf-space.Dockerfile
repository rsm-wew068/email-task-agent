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
COPY --from=web /usr/local /usr/local
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY src ./src
COPY migrations ./migrations
COPY evals ./evals
COPY README.md ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY --from=web /web/.next /web/.next
COPY --from=web /web/node_modules /web/node_modules
COPY --from=web /web/package.json /web/next.config.ts /web/
WORKDIR /web
EXPOSE 7860
CMD ["sh", "-c", "(cd /app && uvicorn email_task_agent.app.main:app_factory --factory --host 127.0.0.1 --port 8000 &) && until python3 -c \"import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)\" 2>/dev/null; do sleep 1; done && exec /web/node_modules/.bin/next start -H 0.0.0.0 -p 7860"]
