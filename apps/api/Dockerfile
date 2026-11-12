FROM node:22-bookworm-slim AS node

RUN npm install -g openclaw@2026.7.1
RUN npm install -g @openai/codex@0.165.0
# Used only by AI_BACKEND=openclaw_claude with the claude-cli agent runtime.
RUN npm install -g @anthropic-ai/claude-code@2.1.322

FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENCLAW_CODEX_APP_SERVER_BIN=/usr/local/bin/codex \
    CLAUDE_CONFIG_DIR=/root/.claude

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-deu \
        tesseract-ocr-eng \
        tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/openclaw /usr/local/lib/node_modules/openclaw
COPY --from=node /usr/local/lib/node_modules/@openai/codex /usr/local/lib/node_modules/@openai/codex
COPY --from=node /usr/local/lib/node_modules/@anthropic-ai/claude-code /usr/local/lib/node_modules/@anthropic-ai/claude-code
# OpenClaw 2026.7.1 bundles an older CLI that cannot run the current models.
RUN ln -s ../lib/node_modules/openclaw/openclaw.mjs /usr/local/bin/openclaw \
    && ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && ln -s ../lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe /usr/local/bin/claude \
    && codex --version \
    && claude --version

WORKDIR /workspace/apps/api

COPY apps/api/pyproject.toml ./
COPY apps/api/constraints.txt ./
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app
COPY scripts/retry_failed_job_screening.py /workspace/scripts/retry_failed_job_screening.py

RUN python -m pip install --upgrade pip \
    && python -m pip install --constraint constraints.txt . \
    && python -m playwright install --with-deps chromium

EXPOSE 8000

ENTRYPOINT ["python", "-m", "app.core.docker_entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
