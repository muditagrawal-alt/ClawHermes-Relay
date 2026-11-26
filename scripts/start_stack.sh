#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

mkdir -p ".openclaw-state" "phoenix_data" "docs/screenshots" "logs"

PHOENIX_PORT="${PHOENIX_PORT:-6006}"
PHOENIX_GRPC_PORT="${PHOENIX_GRPC_PORT:-4317}"

echo "Starting Arize Phoenix on http://localhost:${PHOENIX_PORT} (OTLP gRPC :${PHOENIX_GRPC_PORT})..."
PHOENIX_PORT="$PHOENIX_PORT" PHOENIX_GRPC_PORT="$PHOENIX_GRPC_PORT" PHOENIX_WORKING_DIR="$ROOT_DIR/phoenix_data" \
  nohup "$ROOT_DIR/.venv/bin/phoenix" serve > "$ROOT_DIR/logs/phoenix.log" 2>&1 &
echo $! > "$ROOT_DIR/logs/phoenix.pid"

for i in $(seq 1 30); do
  if curl -sf "http://localhost:${PHOENIX_PORT}" >/dev/null 2>&1; then
    echo "Arize Phoenix is up at http://localhost:${PHOENIX_PORT}"
    break
  fi
  sleep 1
done

echo "Starting OpenClaw Gateway..."
nohup openclaw gateway run > "$ROOT_DIR/logs/openclaw.log" 2>&1 &
echo $! > "$ROOT_DIR/logs/openclaw.pid"

echo "Starting Hermes Agent Gateway..."
nohup hermes gateway run > "$ROOT_DIR/logs/hermes.log" 2>&1 &
echo $! > "$ROOT_DIR/logs/hermes.pid"

echo "All services launched. Logs are in $ROOT_DIR/logs/"
