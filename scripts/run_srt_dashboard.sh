#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRT_INPUT_DIR="${SRT_INPUT_DIR:-${ROOT_DIR}/data/flightrecords/flight_mission_drone}"
SRT_OUTPUT_DIR="${SRT_OUTPUT_DIR:-${ROOT_DIR}/output/flightrecords/flight_mission_drone}"

INTELSIGHT_PYTHON="${INTELSIGHT_PYTHON:-/home/tnzr/.local/share/mamba/envs/intelsight/bin/python}"
PY_RUNNER=()
if [[ -x "${INTELSIGHT_PYTHON}" ]]; then
  PY_RUNNER=("${INTELSIGHT_PYTHON}")
elif command -v conda >/dev/null 2>&1; then
  PY_RUNNER=(conda run -n intelsight python)
else
  echo "Error: intelsight python not found at ${INTELSIGHT_PYTHON} and no conda runner available." >&2
  exit 127
fi

mkdir -p "${SRT_OUTPUT_DIR}"

echo "[1/2] Parse SRT telemetry"
"${PY_RUNNER[@]}" "${ROOT_DIR}/modules/flight-visualizer/parse_dji_srt.py" \
  --input-dir "${SRT_INPUT_DIR}" \
  --output-dir "${SRT_OUTPUT_DIR}"

echo "[2/2] Build lightweight trajectory dashboard"
"${PY_RUNNER[@]}" "${ROOT_DIR}/modules/flight-visualizer/build_trajectory_dashboard.py" \
  --input-dir "${SRT_OUTPUT_DIR}" \
  --output "${SRT_OUTPUT_DIR}/trajectory-dashboard.html"

echo "Dashboard ready: ${SRT_OUTPUT_DIR}/trajectory-dashboard.html"
