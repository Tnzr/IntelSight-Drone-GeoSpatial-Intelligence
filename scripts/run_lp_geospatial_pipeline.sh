#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VIDEO_DIR="${1:-$ROOT_DIR/data/flightrecords/flight_mission_drone}"
SRT_CSV_DIR="${2:-$ROOT_DIR/output/flightrecords/flight_mission_drone}"
OUTPUT_BASE="${3:-$ROOT_DIR/output/cv/flight_mission_drone}"
DEVICES="${DEVICES:-0}"
FRAME_STEP="${FRAME_STEP:-2}"
BATCH_SIZE="${BATCH_SIZE:-16}"
OCR_FRAME_INTERVAL="${OCR_FRAME_INTERVAL:-3}"
MAX_PLATE_BOXES="${MAX_PLATE_BOXES:-6}"
MAX_OCR_CROPS="${MAX_OCR_CROPS:-3}"
MIN_PLATE_CROP_AREA="${MIN_PLATE_CROP_AREA:-400}"
DISABLE_FULL_FRAME_PLATE_DETECTOR="${DISABLE_FULL_FRAME_PLATE_DETECTOR:-1}"

INTELSIGHT_PYTHON="${INTELSIGHT_PYTHON:-/home/tnzr/.local/share/mamba/envs/intelsight/bin/python}"

resolve_mamba_bin() {
  local candidate
  for candidate in \
    "/home/tnzr/anaconda3/bin/mamba" \
    "/home/tnzr/.local/share/mamba/bin/mamba" \
    "/home/tnzr/.local/bin/mamba" \
    "/usr/local/bin/mamba" \
    "/opt/micromamba/bin/micromamba" \
    "/home/tnzr/micromamba/bin/micromamba" \
    "/home/tnzr/mambaforge/bin/mamba" \
    "/home/tnzr/miniforge3/bin/mamba" \
    "/home/tnzr/miniconda3/bin/conda" \
    "/home/tnzr/anaconda3/bin/conda" \
    "/home/tnzr/.local/share/mamba/bin/conda" \
    "/home/tnzr/.local/bin/conda" \
    "/usr/local/bin/conda"; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  if command -v mamba >/dev/null 2>&1; then
    command -v mamba
    return 0
  fi
  if command -v micromamba >/dev/null 2>&1; then
    command -v micromamba
    return 0
  fi
  if command -v conda >/dev/null 2>&1; then
    command -v conda
    return 0
  fi

  return 1
}

MAMBA_BIN="$(resolve_mamba_bin || true)"
if [[ -n "${MAMBA_BIN}" ]]; then
  export PATH="$(dirname "$MAMBA_BIN"):$PATH"
fi

PY_RUNNER=()
if [[ -x "${INTELSIGHT_PYTHON}" ]]; then
  PY_RUNNER=("${INTELSIGHT_PYTHON}")
else
  RUNNER=()
  if [[ -n "${MAMBA_BIN}" ]]; then
    RUNNER=("$MAMBA_BIN" run -n intelsight)
  fi
  if [[ ${#RUNNER[@]} -eq 0 ]]; then
    if command -v mamba >/dev/null 2>&1; then
      RUNNER=(mamba run -n intelsight)
    elif command -v micromamba >/dev/null 2>&1; then
      RUNNER=(micromamba run -n intelsight)
    elif command -v conda >/dev/null 2>&1; then
      RUNNER=(conda run -n intelsight)
    fi
  fi
  if [[ ${#RUNNER[@]} -eq 0 ]]; then
    echo "Error: no suitable mamba/conda runner found in PATH or common install locations." >&2
    exit 127
  fi
  PY_RUNNER=("${RUNNER[@]}" python)
fi

resolve_video_path() {
  local base="$1"
  local candidate
  for ext in MP4 mp4 MOV mov; do
    candidate="$VIDEO_DIR/$base.$ext"
    if [[ -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

CV_DIR="$OUTPUT_BASE/detections"
SYNC_DIR="$OUTPUT_BASE/synced"
FUSED_DIR="$OUTPUT_BASE/fused"
REPORT_HTML="$OUTPUT_BASE/lp_vehicle_report.html"
REPORT_SUMMARY="$OUTPUT_BASE/lp_vehicle_report.summary.json"
REPORT_GEOJSON="$OUTPUT_BASE/lp_vehicle_report.geojson"
OVERLAY_DIR="$OUTPUT_BASE/overlay"

mkdir -p "$CV_DIR" "$SYNC_DIR" "$FUSED_DIR" "$OVERLAY_DIR"

log_step() {
  printf '%s %s\n' "[$(date +%H:%M:%S)]" "$1"
}

log_step "[1/5] Running CV detection with env=${MAMBA_BIN:-unknown}"
cv_args=(
  --input-dir "$VIDEO_DIR"
  --output-dir "$CV_DIR"
  --devices "$DEVICES"
  --frame-step "$FRAME_STEP"
  --batch-size "$BATCH_SIZE"
  --ocr-frame-interval "$OCR_FRAME_INTERVAL"
  --max-plate-boxes "$MAX_PLATE_BOXES"
  --max-ocr-crops "$MAX_OCR_CROPS"
  --min-plate-crop-area "$MIN_PLATE_CROP_AREA"
)
if [[ "$DISABLE_FULL_FRAME_PLATE_DETECTOR" == "1" ]]; then
  cv_args+=(--disable-full-frame-plate-detector)
fi

"${PY_RUNNER[@]}" "$ROOT_DIR/modules/cv-pipeline/run_cv_pipeline.py" \
  "${cv_args[@]}"

echo "[2/5] Syncing detections with SRT telemetry"
"${PY_RUNNER[@]}" "$ROOT_DIR/modules/cv-pipeline/sync_detections_with_srt.py" \
  --detections-dir "$CV_DIR" \
  --srt-csv-dir "$SRT_CSV_DIR" \
  --output-dir "$SYNC_DIR"

echo "[3/5] Fusing plate observations across frames"
"${PY_RUNNER[@]}" "$ROOT_DIR/modules/cv-pipeline/fuse_plate_observations.py" \
  --input-dir "$SYNC_DIR" \
  --output-dir "$FUSED_DIR" \
  --frame-window 12

echo "[4/5] Building interactive map and listing"
"${PY_RUNNER[@]}" "$ROOT_DIR/modules/cv-pipeline/build_detection_report.py" \
  --input-dir "$FUSED_DIR" \
  --output "$REPORT_HTML" \
  --summary-output "$REPORT_SUMMARY" \
  --geojson-output "$REPORT_GEOJSON"

echo "[5/5] Rendering overlay video(s)"
for det in "$CV_DIR"/*.detections.jsonl; do
  [[ -e "$det" ]] || continue
  base="$(basename "$det" .detections.jsonl)"
  video="$(resolve_video_path "$base" || true)"
  srt_csv="$SRT_CSV_DIR/$base.srt.csv"
  geotagged_csv="$SYNC_DIR/$base.detections.geotagged.csv"
  if [[ -z "$video" || ! -f "$video" ]]; then
    echo "skip overlay: missing video for $base"
    continue
  fi
  "${PY_RUNNER[@]}" "$ROOT_DIR/modules/cv-pipeline/render_overlay_video.py" \
    --video "$video" \
    --detections "$det" \
    --output "$OVERLAY_DIR/$base.overlay.mp4" \
    --srt-csv "$srt_csv" \
    --geotagged-csv "$geotagged_csv" \
    --frame-step "$FRAME_STEP"
done

echo "Complete"
echo "report: $REPORT_HTML"
echo "report summary: $REPORT_SUMMARY"
echo "report geojson: $REPORT_GEOJSON"
