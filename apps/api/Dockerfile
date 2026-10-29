FROM node:22-bookworm-slim AS node

RUN npm install -g openclaw@2026.7.1
RUN npm install -g @openai/codex@0.165.0

FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENCLAW_CODEX_APP_SERVER_BIN=/usr/local/bin/codex

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        poppler-utils \
        texlive-fonts-extra \
        texlive-latex-extra \
        texlive-luatex \
        texlive-xetex \
        tesseract-ocr \
        tesseract-ocr-deu \
        tesseract-ocr-eng \
        tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/openclaw /usr/local/lib/node_modules/openclaw
COPY --from=node /usr/local/lib/node_modules/@openai/codex /usr/local/lib/node_modules/@openai/codex
# OpenClaw 2026.7.1 bundles an older CLI that cannot run the current models.
RUN ln -s ../lib/node_modules/openclaw/openclaw.mjs /usr/local/bin/openclaw \
    && ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && codex --version

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

# hyperref uses the Zapf Dingbats metric (pzdr.tfm) when compiling links with
# XeLaTeX. Keep this in a separate late layer so the large TeX image layer can
# remain cached when the font dependency changes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends texlive-fonts-recommended \
    && kpsewhich pzdr.tfm >/dev/null \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

ENTRYPOINT ["python", "-m", "app.core.docker_entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
