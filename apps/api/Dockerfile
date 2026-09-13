FROM node:22-bookworm-slim AS node

RUN npm install -g openclaw@2026.7.1

FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

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
RUN ln -s ../lib/node_modules/openclaw/openclaw.mjs /usr/local/bin/openclaw

WORKDIR /workspace/apps/api

COPY apps/api/pyproject.toml ./
COPY apps/api/constraints.txt ./
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app

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
