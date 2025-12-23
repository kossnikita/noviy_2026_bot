#!/bin/sh
set -eu

mkdir -p /app/data/img /tmp/nginx_client_body /tmp/nginx_proxy /tmp/nginx_fastcgi /tmp/nginx_uwsgi /tmp/nginx_scgi

# Start bot+API (API runs in background thread inside the process)
python . &
PY_PID=$!

# Start nginx reverse proxy
nginx -g 'daemon off;' -c /app/nginx.conf &
NG_PID=$!

echo "[entrypoint] started python pid=$PY_PID, nginx pid=$NG_PID" >&2

# Exit the container if either process exits.
while :; do
  if ! kill -0 "$PY_PID" 2>/dev/null; then
    echo "[entrypoint] python exited" >&2
    exit 1
  fi
  if ! kill -0 "$NG_PID" 2>/dev/null; then
    echo "[entrypoint] nginx exited" >&2
    exit 1
  fi
  sleep 1
done
