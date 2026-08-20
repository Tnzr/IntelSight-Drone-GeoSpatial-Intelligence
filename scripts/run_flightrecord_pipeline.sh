#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${OUT_DIR:-${ROOT_DIR}/output/flightrecords}"
DATA_DIR="${DATA_DIR:-${ROOT_DIR}/data/flightrecords}"

INTELSIGHT_BIN="${INTELSIGHT_BIN:-/home/tnzr/.local/share/mamba/envs/intelsight/bin}"
INTELSIGHT_PYTHON="${INTELSIGHT_BIN}/python"
if [[ ! -x "${INTELSIGHT_PYTHON}" ]]; then
  echo "Error: intelsight python not found at ${INTELSIGHT_PYTHON}. Set INTELSIGHT_BIN to the env bin dir." >&2
  exit 127
fi

if [[ -f "${ROOT_DIR}/.secrets/dji.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.secrets/dji.env"
  set +a
fi

mkdir -p "${OUT_DIR}"

echo "[1/3] Build Rust parser"
"${INTELSIGHT_BIN}/cargo" build --release --manifest-path "${ROOT_DIR}/modules/flightrecord-parser/Cargo.toml"

PARSER_BIN="${ROOT_DIR}/modules/flightrecord-parser/target/release/intelsight-flightrecord-parser"

echo "[2/3] Parse DJI flight logs"
mapfile -t TXT_FILES < <(find "${DATA_DIR}" -type f \( -name "*.txt" -o -name "*.TXT" \) | sort)

if [[ ${#TXT_FILES[@]} -eq 0 ]]; then
  echo "  - no TXT flight logs found under ${DATA_DIR}"
fi

for file in "${TXT_FILES[@]}"; do
  echo "  - parsing $(basename "$file")"
  if [[ -n "${DJI_API_KEY:-}" ]]; then
    "${PARSER_BIN}" --input "$file" --out-dir "${OUT_DIR}" --api-key "${DJI_API_KEY}"
  else
    "${PARSER_BIN}" --input "$file" --out-dir "${OUT_DIR}"
  fi
done

echo "[3/3] Render maps and collect viz metrics"
for csv_file in "${OUT_DIR}"/*.frames.csv; do
  base="$(basename "$csv_file" .frames.csv)"
  html_file="${OUT_DIR}/${base}.map.html"
  metrics_file="${OUT_DIR}/${base}.viz.metrics.json"
  "${INTELSIGHT_PYTHON}" "${ROOT_DIR}/modules/flight-visualizer/render_map.py" \
    --csv "$csv_file" \
    --html "$html_file" \
    --metrics "$metrics_file" \
    --title "IntelSight Trajectory: ${base}"
done

echo "[4/4] Analyze parser bottlenecks"
"${INTELSIGHT_PYTHON}" "${ROOT_DIR}/modules/flight-visualizer/analyze_bottlenecks.py" \
  --metrics-dir "${OUT_DIR}" \
  --output "${OUT_DIR}/bottleneck-summary.json"

echo "Pipeline completed. Output directory: ${OUT_DIR}"
