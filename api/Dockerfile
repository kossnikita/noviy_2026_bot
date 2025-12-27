FROM node:22-alpine AS overlay_builder

WORKDIR /overlay

COPY overlay/package.json /overlay/package.json
RUN npm install

COPY overlay/ /overlay/

RUN npm run build

# Smoke-check: ensure overlay artifact exists and is non-empty
RUN test -s /overlay/dist/overlay.html


FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install nginx for reverse proxy
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app/api
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

# OBS overlay (single-file HTML built by overlay_builder)
RUN mkdir -p /app/overlay
COPY --from=overlay_builder /overlay/dist/overlay.html /app/overlay/index.html

# nginx config lives in this folder
RUN mv /app/api/nginx.conf /etc/nginx/nginx.conf

RUN chmod +x /app/docker-entrypoint.sh

RUN adduser --disabled-password --gecos '' appuser \
    && chown -R appuser:appuser /app

EXPOSE 80

CMD ["/app/docker-entrypoint.sh"]
