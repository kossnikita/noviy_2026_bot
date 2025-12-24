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

COPY . /app

# nginx config lives in this folder
RUN cp /app/api/nginx.conf /etc/nginx/nginx.conf

RUN chmod +x /app/api/docker-entrypoint.sh

RUN adduser --disabled-password --gecos '' appuser \
    && chown -R appuser:appuser /app

EXPOSE 80

CMD ["/app/docker-entrypoint.sh"]
