#!/usr/bin/env bash
# Stub service — sleeps indefinitely and responds 200 to /health
# Replace with real binary once the service is implemented.
SERVICE_NAME="$(basename "$0")"
PORT="${1:-8001}"
for arg in "$@"; do
  case "$arg" in --port=*) PORT="${arg#--port=}";; esac
done

echo "[stub] ${SERVICE_NAME} started on port ${PORT} (stub mode)"

# Minimal HTTP health responder using bash + netcat
while true; do
  echo -e "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"status\":\"ok\",\"mode\":\"stub\",\"service\":\"${SERVICE_NAME}\"}" \
    | nc -l -p "${PORT}" -q 1 2>/dev/null || true
done
