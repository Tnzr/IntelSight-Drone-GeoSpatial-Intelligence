#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PATH="$ROOT_DIR/modules/web-dashboard/app.py"
PORT="${PORT:-8501}"
HOST="${HOST:-0.0.0.0}"

resolve_mamba_bin() {
  local candidate
  for candidate in \
    "/home/tnzr/.local/share/mamba/bin/mamba" \
    "/home/tnzr/.local/share/mamba/bin/conda" \
    "/home/tnzr/.local/bin/mamba" \
    "/home/tnzr/.local/bin/conda" \
    "/tmp/micromamba-bin/bin/micromamba" \
    "/usr/local/bin/micromamba" \
    "/usr/local/bin/mamba" \
    "/usr/local/bin/conda" \
    "/opt/micromamba/bin/micromamba" \
    "/home/tnzr/micromamba/bin/micromamba" \
    "/home/tnzr/mambaforge/bin/mamba" \
    "/home/tnzr/miniforge3/bin/mamba" \
    "/home/tnzr/miniconda3/bin/conda" \
    "/home/tnzr/anaconda3/bin/conda"; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  if command -v mamba >/dev/null 2>&1; then
    command -v mamba
    return 0
  fi
  if command -v conda >/dev/null 2>&1; then
    command -v conda
    return 0
  fi
  if command -v micromamba >/dev/null 2>&1; then
    command -v micromamba
    return 0
  fi

  return 1
}

MAMBA_BIN="$(resolve_mamba_bin || true)"

INTELSIGHT_PYTHON="${INTELSIGHT_PYTHON:-/home/tnzr/.local/share/mamba/envs/intelsight/bin/python}"
if [[ -x "${INTELSIGHT_PYTHON}" ]]; then
  exec "${INTELSIGHT_PYTHON}" -m streamlit run "$APP_PATH" --server.address "$HOST" --server.port "$PORT" "$@"
fi

if [[ -n "${MAMBA_BIN}" ]]; then
  export PATH="$(dirname "$MAMBA_BIN"):$PATH"
fi

if [[ -n "${MAMBA_BIN}" ]]; then
  exec "$MAMBA_BIN" run -n intelsight streamlit run "$APP_PATH" --server.address "$HOST" --server.port "$PORT" "$@"
fi

if command -v streamlit >/dev/null 2>&1; then
  exec streamlit run "$APP_PATH" --server.address "$HOST" --server.port "$PORT" "$@"
fi

echo "Error: no suitable environment runner found. Install mamba/conda/micromamba or activate an environment with streamlit available." >&2
exit 127