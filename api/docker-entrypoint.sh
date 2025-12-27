#!/bin/sh
set -eu

mkdir -p /app/data/img /tmp/nginx_client_body /tmp/nginx_proxy /tmp/nginx_fastcgi /tmp/nginx_uwsgi /tmp/nginx_scgi

# Generate OBS overlay runtime config from env.
# This keeps all secrets/config out of build-time and injects them only at container start.
escape_js_string() {
  # Minimal JS string escaping for our config values.
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

: "${PHOTO_POLL_INTERVAL_MS:=2000}"
: "${PHOTO_DISPLAY_MS:=10000}"
: "${QUEUE_POLL_INTERVAL_MS:=2000}"

WS_TOKEN_MODE_COMPUTED="${WS_MODE:-${WS_AUTH_MODE:-${WS_TOKEN_MODE:-none}}}"

if [ -z "${OVERLAY_API_TOKEN:-}" ]; then
  echo "[entrypoint] warn: OVERLAY_API_TOKEN is empty; overlay API requests may fail" >&2
fi

mkdir -p /app/overlay
cat > /app/overlay/config.js <<EOF
// Auto-generated at container start from env.
window.__NOVIY_OVERLAY__ = Object.assign(window.__NOVIY_OVERLAY__ || {}, {
  OVERLAY_API_TOKEN: "$(escape_js_string "${OVERLAY_API_TOKEN:-}")",
  WS_URL: "$(escape_js_string "${WS_URL:-}")",
  PHOTO_POLL_INTERVAL_MS: ${PHOTO_POLL_INTERVAL_MS},
  PHOTO_DISPLAY_MS: ${PHOTO_DISPLAY_MS},
  QUEUE_POLL_INTERVAL_MS: ${QUEUE_POLL_INTERVAL_MS},
  WS_TOKEN_MODE: "$(escape_js_string "${WS_TOKEN_MODE_COMPUTED}")"
});
EOF

# Ensure app data is writable even when mounted as a volume
chown -R appuser:appuser /app/data || true

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
