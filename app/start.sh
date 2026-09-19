#!/usr/bin/env bash
# start.sh — KVK iXBRL v2 launcher
#
# Usage (development, default):
#   bash KVK_v2/app/start.sh
#
# Usage (production — no auto-reload, single worker):
#   PROD=1 bash KVK_v2/app/start.sh
#
# Run from any directory; script resolves paths automatically.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KVK_V2_DIR="$(dirname "$SCRIPT_DIR")"
DOCUMENTS_DIR="$(dirname "$KVK_V2_DIR")"
VENV="$SCRIPT_DIR/.venv"
PROD="${PROD:-0}"

echo ""
echo "  ┌──────────────────────────────────────────────────┐"
echo "  │   KVK iXBRL v2  —  http://localhost:8000         │"
echo "  └──────────────────────────────────────────────────┘"
echo ""

if [ "$PROD" = "1" ]; then
  echo "  ⚠  PRODUCTION mode: no auto-reload, no debug output."
  echo "  ⚠  This tool is a LOCAL FILING PREPARATION AID only."
  echo "  ⚠  It has no Digipoort WUS 1.3 submission path."
  echo ""
fi

# ── Virtual environment ──────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  echo "▶ Creating virtual environment…"
  python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"

# ── Install pinned dependencies ──────────────────────────────────────────────
if [ "${INSTALL_DEPS:-0}" = "1" ] || ! python -c "import fastapi, uvicorn, docx, lxml" >/dev/null 2>&1; then
  echo "▶ Installing pinned dependencies from requirements.txt…"
  python -m pip install -q -r "$SCRIPT_DIR/requirements.txt"
fi

# ── Taxonomy check ───────────────────────────────────────────────────────────
TAXONOMY_DIR="${KVK_TAXONOMY_DIR:-$SCRIPT_DIR/data/taxonomies}"
mkdir -p "$TAXONOMY_DIR"

TAX_COUNT=$(find "$TAXONOMY_DIR" -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
if [ "$TAX_COUNT" -eq 0 ]; then
  echo ""
  echo "  ⚠  WARNING: No taxonomy manifests found in app/data/taxonomies/"
  echo "  ⚠  Validation and export will be blocked until a verified"
  echo "  ⚠  final taxonomy package and independent validator are installed."
  echo "  ⚠  See TAXONOMY_SETUP.md for instructions."
  echo ""
fi

echo "▶ Starting server…"
echo ""

# PYTHONPATH = Documents/ so 'import KVK_v2' resolves to KVK_v2/
cd "$DOCUMENTS_DIR"

if [ "$PROD" = "1" ]; then
  # Production: no reload, bind to localhost only
  PYTHONPATH="$DOCUMENTS_DIR" uvicorn KVK_v2.app.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --no-access-log
else
  # Development: auto-reload on file changes
  PYTHONPATH="$DOCUMENTS_DIR" uvicorn KVK_v2.app.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --reload \
    --reload-dir "$KVK_V2_DIR"
fi
