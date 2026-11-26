#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/4] Ensuring Python .venv with Arize Phoenix & search tools..."
if [[ ! -d ".venv" ]]; then
  uv venv --python 3.12 .venv
fi
uv pip install --python .venv/bin/python -r requirements.txt

echo "[2/4] Installing OpenInference / OTel + ddgs into Hermes Agent venv..."
HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
if [[ -x "$HERMES_PY" ]]; then
  uv pip install --python "$HERMES_PY" \
    opentelemetry-sdk \
    opentelemetry-exporter-otlp-proto-http \
    openinference-semantic-conventions \
    ddgs
else
  echo "WARNING: Hermes venv python not found at $HERMES_PY"
fi

echo "[3/4] Installing phoenix-otel plugin & SEO/AEO skill for Hermes..."
mkdir -p "$HOME/.hermes/plugins/phoenix_otel" "$HOME/.hermes/skills/seo-aeo-research"
cp "$ROOT_DIR/config/phoenix_otel_plugin/plugin.yaml" "$HOME/.hermes/plugins/phoenix_otel/plugin.yaml"
cp "$ROOT_DIR/config/phoenix_otel_plugin/__init__.py" "$HOME/.hermes/plugins/phoenix_otel/__init__.py"
cp "$ROOT_DIR/config/hermes/seo_aeo_skill.md" "$HOME/.hermes/skills/seo-aeo-research/SKILL.md"

hermes plugins enable phoenix-otel --no-allow-tool-override || true
hermes plugins enable web-ddgs --no-allow-tool-override || true

echo "[4/4] Making scripts executable..."
chmod +x "$ROOT_DIR/scripts/"*.sh "$ROOT_DIR/scripts/"*.py

echo "Environment setup complete. Run .venv/bin/python scripts/verify_e2e.py to verify."
