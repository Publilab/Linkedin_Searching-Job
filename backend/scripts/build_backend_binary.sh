#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "$BACKEND_DIR"

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt

pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --paths "$BACKEND_DIR" \
  --name seekjob-backend \
  --hidden-import=app.main \
  --hidden-import=uvicorn.logging \
  --hidden-import=uvicorn.loops.auto \
  --hidden-import=uvicorn.protocols.http.auto \
  --hidden-import=uvicorn.lifespan.on \
  desktop_entry.py

mkdir -p dist
chmod +x dist/seekjob-backend

echo "Backend binary ready: ${BACKEND_DIR}/dist/seekjob-backend"
