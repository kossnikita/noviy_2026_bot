#!/bin/sh
set -eu

mkdir -p /app/data /tmp/nginx_client_body /tmp/nginx_proxy /tmp/nginx_fastcgi /tmp/nginx_uwsgi /tmp/nginx_scgi

# Start FastAPI (uvicorn) on :8080
python -m api.main &
API_PID=$!

# Start nginx reverse proxy on :80
nginx -g 'daemon off;' &
NGINX_PID=$!

echo "[entrypoint] started api pid=$API_PID, nginx pid=$NGINX_PID" >&2

# Exit container if either process exits.
while :; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "[entrypoint] api exited" >&2
    exit 1
  fi
  if ! kill -0 "$NGINX_PID" 2>/dev/null; then
    echo "[entrypoint] nginx exited" >&2
    exit 1
  fi
  sleep 1
done
