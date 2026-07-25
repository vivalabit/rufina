FROM node:22-bookworm-slim AS node

RUN npm install -g openclaw@2026.7.1

FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

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
RUN ln -s ../lib/node_modules/openclaw/openclaw.mjs /usr/local/bin/openclaw

WORKDIR /workspace/apps/api

COPY apps/api/pyproject.toml ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -e .

COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
