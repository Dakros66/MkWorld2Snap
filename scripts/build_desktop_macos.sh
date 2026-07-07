#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
venv_python="$project_root/.venv/bin/python"

pick_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
    return
  fi
  if command -v python3.12 >/dev/null 2>&1; then
    command -v python3.12
    return
  fi
  command -v python3
}

build_frontend() {
  cd "$project_root/frontend"
  if command -v pnpm >/dev/null 2>&1; then
    pnpm install
    pnpm run build
  else
    npm install
    npm run build
  fi
}

prepare_python() {
  local base_python
  base_python="$(pick_python)"
  if [[ ! -x "$venv_python" ]]; then
    "$base_python" -m venv "$project_root/.venv"
  fi
  "$venv_python" -m pip install --upgrade pip
  "$venv_python" -m pip install -r "$project_root/requirements-desktop.txt"
}

bundle_app() {
  cd "$project_root"
  PYINSTALLER_CONFIG_DIR="$project_root/.pyinstaller-cache" \
    "$venv_python" -m PyInstaller \
      --clean \
      --noconfirm \
      --distpath "$project_root/dist" \
      --workpath "$project_root/build" \
      "$project_root/MkWorld2Snap.spec"
}

build_frontend
prepare_python
bundle_app

printf 'Built app: %s\n' "$project_root/dist/MkWorld2Snap.app"
