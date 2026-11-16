# syntax=docker/dockerfile:1
# AutoApply as a container: the program, its browser and everything a server otherwise lacks for it - the libraries
# the browser needs, a virtual screen and its viewer (Xvfb, x11vnc), LibreOffice for PDFs, Chinese fonts.
#
#   docker compose up -d                              (docker-compose.yml: one volume for everything that is yours)
#   docker compose exec autoapply autoapply set-admin     the first time: the administrator's name and password
#   docker compose exec autoapply autoapply doctor --deep
#
# Your data lives in the volume mounted at /data and nowhere else; the image holds no secrets and no state.
# The program runs as an ordinary user (uid 10001), never as root.

# --- the interface, built here so that the image does not depend on a build on someone's computer ---
FROM node:22-bookworm-slim AS interface
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- the program ---
FROM python:3.12-slim-bookworm
# uv, one fixed version (the same as the installers carry: scripts/fetch_uv.py)
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PLAYWRIGHT_BROWSERS_PATH=/opt/browsers \
    AUTOAPPLY_DATA=/data/data \
    AUTOAPPLY_KNOWLEDGE=/data/knowledge \
    PATH=/opt/autoapply/.venv/bin:$PATH

# tini: signals reach the program, and what it leaves behind is reaped.  xvfb, x11vnc: the virtual screen for sites
# that refuse a hidden browser, and the way to see it.  chromium: the ordinary browser the optional second backend
# drives.  libreoffice-writer: Word documents to PDF.  fonts: Chinese text in PDFs and screenshots.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini xvfb x11vnc chromium libreoffice-writer fonts-noto-cjk fonts-liberation fontconfig ca-certificates curl procps \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/autoapply
# dependencies first: this layer changes only when the lock does
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY backend/ backend/
RUN uv sync --frozen --no-dev --extra nodriver
# the program's own browser, with the system libraries it needs (this is the step a bare server is missing)
RUN playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/* && chmod -R a+rX /opt/browsers

COPY scripts/ scripts/
COPY frontend/src/i18n/ frontend/src/i18n/
COPY frontend/public/ frontend/public/
COPY --from=interface /src/frontend/dist/ frontend/dist/
COPY CHANGELOG.md ./

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin autoapply \
 && mkdir -p /data && chown autoapply:autoapply /data
USER autoapply
VOLUME /data
EXPOSE 8000

# the one address that answers without a login
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/auth/state > /dev/null || exit 1

ENTRYPOINT ["tini", "--"]
# every network of the container: which of the computer's networks can reach it is decided where the port is published
CMD ["autoapply", "serve", "--host", "0.0.0.0", "--port", "8000"]
