#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
DESKTOP_DIR="$ROOT_DIR/desktop"

if ! command -v rustc >/dev/null 2>&1; then
  echo "Rust is required. Install with: curl https://sh.rustup.rs -sSf | sh"
  exit 1
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "Cargo is required. Install with rustup."
  exit 1
fi

pushd "$FRONTEND_DIR" >/dev/null
npm install
npm run build:desktop
popd >/dev/null

"$BACKEND_DIR/scripts/build_backend_binary.sh"

pushd "$DESKTOP_DIR" >/dev/null
npm install
npm run tauri:build
popd >/dev/null

echo "Desktop bundle generated. Check: $DESKTOP_DIR/src-tauri/target/release/bundle/macos"
