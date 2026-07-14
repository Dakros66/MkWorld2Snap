#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
venv_dir="$project_root/.venv-linux"
venv_python="$venv_dir/bin/python"

if [[ "$(uname -s)" != "Linux" ]]; then
  printf 'This script builds the Linux desktop binary and must be run on Linux.\n' >&2
  exit 1
fi

pick_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
    return
  fi
  command -v python3
}

build_frontend() {
  local -a pnpm_cmd
  cd "$project_root/frontend"
  if command -v pnpm >/dev/null 2>&1; then
    pnpm_cmd=("$(command -v pnpm)")
  elif command -v corepack >/dev/null 2>&1; then
    corepack prepare pnpm@11.7.0 --activate
    pnpm_cmd=(corepack pnpm)
  else
    printf 'pnpm is required to build the frontend. Install pnpm or enable Corepack.\n' >&2
    exit 1
  fi
  "${pnpm_cmd[@]}" install --frozen-lockfile || "${pnpm_cmd[@]}" install
  "${pnpm_cmd[@]}" run build
}

prepare_python() {
  local base_python
  base_python="$(pick_python)"
  if [[ ! -x "$venv_python" ]]; then
    "$base_python" -m venv "$venv_dir"
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

verify_app() {
  local binary="$project_root/dist/MkWorld2Snap"
  if [[ ! -x "$binary" ]]; then
    printf 'Linux binary was not created: %s\n' "$binary" >&2
    exit 1
  fi
  file "$binary"
}

build_frontend
prepare_python
bundle_app
verify_app

printf 'Built Linux binary: %s\n' "$project_root/dist/MkWorld2Snap"
