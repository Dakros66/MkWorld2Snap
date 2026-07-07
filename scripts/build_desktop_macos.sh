#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
venv_dir="$project_root/.venv-universal2"
venv_python="$venv_dir/bin/python"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'This script builds the macOS app and must be run on macOS.\n' >&2
  exit 1
fi

pick_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
    return
  fi
  if [[ -x /usr/local/bin/python3 ]]; then
    printf '%s\n' /usr/local/bin/python3
    return
  fi
  command -v python3
}

assert_universal_python() {
  local python_bin="$1"
  if ! file "$python_bin" | grep -q 'universal binary'; then
    printf 'Python is not universal2: %s\n' "$python_bin" >&2
    printf 'Set PYTHON_BIN to a universal2 Python, for example /usr/local/bin/python3.\n' >&2
    exit 1
  fi
}

build_frontend() {
  cd "$project_root/frontend"
  if command -v pnpm >/dev/null 2>&1; then
    pnpm install --frozen-lockfile || pnpm install
    pnpm run build
  else
    npm install
    npm run build
  fi
}

prepare_python() {
  local base_python
  base_python="$(pick_python)"
  assert_universal_python "$base_python"
  if [[ ! -x "$venv_python" ]]; then
    "$base_python" -m venv "$venv_dir"
  fi
  "$venv_python" -m pip install --upgrade pip
  "$venv_python" -m pip install -r "$project_root/requirements-desktop.txt"
}

find_rust_tools() {
  local rustup_bin cargo_bin rust_bin_dir
  rustup_bin="$(find "$HOME/Library/Caches/puccinialin" "$HOME/.cargo" -path '*/bin/rustup' -type f 2>/dev/null | head -n 1 || true)"
  cargo_bin="$(find "$HOME/Library/Caches/puccinialin" "$HOME/.cargo" -path '*/bin/cargo' -type f 2>/dev/null | head -n 1 || true)"
  if [[ -n "$rustup_bin" ]]; then
    rust_bin_dir="$(dirname "$rustup_bin")"
    export PATH="$rust_bin_dir:$PATH"
    if [[ "$rustup_bin" == "$HOME/Library/Caches/puccinialin/cargo/bin/rustup" ]]; then
      export CARGO_HOME="$HOME/Library/Caches/puccinialin/cargo"
      export RUSTUP_HOME="$HOME/Library/Caches/puccinialin/rustup"
    fi
  fi
  if [[ -n "$cargo_bin" ]]; then
    rust_bin_dir="$(dirname "$cargo_bin")"
    export PATH="$rust_bin_dir:$PATH"
  fi
}

ensure_universal_pydantic_core() {
  local extension_file version work_dir source_archive source_dir
  extension_file="$("$venv_python" - <<'PY'
from pathlib import Path
import pydantic_core
for path in Path(pydantic_core.__file__).parent.glob('_pydantic_core*.so'):
    print(path)
    break
PY
)"
  if file "$extension_file" | grep -q 'x86_64' && file "$extension_file" | grep -q 'arm64'; then
    return
  fi

  printf 'Rebuilding pydantic-core as universal2...\n'
  "$venv_python" -m pip install maturin
  find_rust_tools
  if command -v rustup >/dev/null 2>&1; then
    rustup target add x86_64-apple-darwin
  fi
  if ! command -v cargo >/dev/null 2>&1; then
    printf 'Rust/cargo is required to build pydantic-core as universal2.\n' >&2
    printf 'Install Rust, then run this script again: https://rustup.rs\n' >&2
    exit 1
  fi

  version="$("$venv_python" - <<'PY'
import pydantic_core
print(pydantic_core.__version__)
PY
)"
  work_dir="/private/tmp/mkworld2snap-pydantic-core"
  rm -rf "$work_dir"
  mkdir -p "$work_dir"
  "$venv_python" -m pip download --no-binary pydantic-core --no-deps --dest "$work_dir" "pydantic-core==$version"
  source_archive="$(find "$work_dir" -maxdepth 1 -name 'pydantic_core-*.tar.gz' -print | head -n 1)"
  tar -xzf "$source_archive" -C "$work_dir"
  source_dir="$(find "$work_dir" -maxdepth 1 -type d -name 'pydantic_core-*' -print | head -n 1)"
  cd "$source_dir"
  "$venv_python" -m maturin build \
    --release \
    --strip \
    --interpreter "$venv_python" \
    --compatibility off \
    --target universal2-apple-darwin
  "$venv_python" -m pip install --force-reinstall target/wheels/*.whl
  file "$extension_file"
}

bundle_app() {
  cd "$project_root"
  PYINSTALLER_CONFIG_DIR="$project_root/.pyinstaller-cache" \
  PYINSTALLER_TARGET_ARCH="universal2" \
    "$venv_python" -m PyInstaller \
      --clean \
      --noconfirm \
      --distpath "$project_root/dist" \
      --workpath "$project_root/build" \
      "$project_root/MkWorld2Snap.spec"
}

verify_app() {
  local app_binary="$project_root/dist/MkWorld2Snap.app/Contents/MacOS/MkWorld2Snap"
  file "$app_binary"
  if ! file "$app_binary" | grep -q 'x86_64'; then
    printf 'The app binary does not contain x86_64.\n' >&2
    exit 1
  fi
  if ! file "$app_binary" | grep -q 'arm64'; then
    printf 'The app binary does not contain arm64.\n' >&2
    exit 1
  fi
}

build_frontend
prepare_python
ensure_universal_pydantic_core
bundle_app
verify_app

printf 'Built universal2 app: %s\n' "$project_root/dist/MkWorld2Snap.app"
