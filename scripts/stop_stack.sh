#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for svc in hermes openclaw phoenix; do
  pidfile="$ROOT_DIR/logs/${svc}.pid"
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "Stopping ${svc} (PID $pid)..."
      kill "$pid" || true
    fi
    rm -f "$pidfile"
  fi
done
echo "Stack stopped."
