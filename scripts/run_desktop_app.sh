#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="$repo_root/desktop-app"
stage_dir="${INTELSIGHT_DESKTOP_STAGE:-${TMPDIR:-/tmp}/intelsight-desktop-run}"
node_bin="${INTELSIGHT_NODE_BIN:-$HOME/.nvm/versions/node/v20.20.2/bin}"

command -v rsync >/dev/null || {
  echo "IntelSight desktop requires rsync." >&2
  exit 1
}

if [[ -x "$node_bin/node" ]]; then
  export PATH="$node_bin:$PATH"
fi

if command -v fuser >/dev/null; then
  for listener_pid in $(fuser 1420/tcp 2>/dev/null || true); do
    listener_command="$(tr '\0' ' ' < "/proc/$listener_pid/cmdline" 2>/dev/null || true)"
    if [[ "$listener_command" == *"$stage_dir"* ]] && [[ "$listener_command" == *"vite"* ]]; then
      kill "$listener_pid"
    fi
  done
fi

mkdir -p "$stage_dir"
rsync -a --delete \
  --exclude node_modules \
  --exclude dist \
  --exclude src-tauri/target \
  "$source_dir/" "$stage_dir/"

cd "$stage_dir"
if [[ ! -x node_modules/.bin/tauri ]]; then
  npm ci --prefer-offline --no-audit
  cp package-lock.json .installed-package-lock.json
elif [[ ! -f .installed-package-lock.json ]]; then
  npm ci --prefer-offline --no-audit
  cp package-lock.json .installed-package-lock.json
elif ! cmp -s package-lock.json .installed-package-lock.json; then
  npm ci --prefer-offline --no-audit
  cp package-lock.json .installed-package-lock.json
fi

export PATH="$HOME/.cargo/bin:$PATH"
export RUSTUP_TOOLCHAIN="${RUSTUP_TOOLCHAIN:-stable}"
export INTELSIGHT_REPO_ROOT="$repo_root"
unset GTK_PATH GIO_MODULE_DIR
if [[ -n "${XDG_DATA_HOME:-}" ]] && [[ "$XDG_DATA_HOME" == "$HOME/snap/"* ]]; then
  snap_app_data="$XDG_DATA_HOME/com.tnzr.desktop-app"
  host_app_data="$HOME/.local/share/com.tnzr.desktop-app"
  if [[ -d "$snap_app_data" ]]; then
    mkdir -p "$host_app_data"
    rsync -a --ignore-existing "$snap_app_data/" "$host_app_data/"
  fi
  unset XDG_DATA_HOME
fi
if [[ -n "${XDG_CACHE_HOME:-}" ]] && [[ "$XDG_CACHE_HOME" == "$HOME/snap/"* ]]; then
  unset XDG_CACHE_HOME
fi
if [[ -n "${XDG_DATA_DIRS_VSCODE_SNAP_ORIG:-}" ]]; then
  export XDG_DATA_DIRS="$XDG_DATA_DIRS_VSCODE_SNAP_ORIG"
fi
exec npm run tauri dev