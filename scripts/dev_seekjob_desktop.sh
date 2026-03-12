#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
DESKTOP_DIR="$ROOT_DIR/desktop"

if [[ ! -d "$BACKEND_DIR/.venv" ]]; then
  python3 -m venv "$BACKEND_DIR/.venv"
fi

source "$BACKEND_DIR/.venv/bin/activate"
pip install -r "$BACKEND_DIR/requirements.txt"

export SEEKJOB_BACKEND_DEV_PYTHON="$BACKEND_DIR/.venv/bin/python"
export SEEKJOB_BACKEND_DEV_SCRIPT="$BACKEND_DIR/desktop_entry.py"

pushd "$DESKTOP_DIR" >/dev/null
npm install
npm run tauri:dev
popd >/dev/null
