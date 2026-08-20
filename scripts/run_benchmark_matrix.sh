#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_DIR="${1:-$ROOT_DIR/data/flightrecords/flight_mission_drone}"
OUTPUT_ROOT="${2:-$ROOT_DIR/output/benchmarks}"

export PATH="/home/tnzr/anaconda3/bin:/home/tnzr/anaconda3/condabin:${PATH:-}"

mkdir -p "$OUTPUT_ROOT"

for profile in "4K24" "1080p60" "4K60"; do
  case "$profile" in
    "4K24") FRAME_STEP=2; BATCH=16 ;;
    "1080p60") FRAME_STEP=1; BATCH=12 ;;
    "4K60") FRAME_STEP=1; BATCH=8 ;;
  esac

  RUN_DIR="$OUTPUT_ROOT/$profile"
  mkdir -p "$RUN_DIR"
  echo "Running profile: $profile -> $RUN_DIR"

  /home/tnzr/anaconda3/bin/mamba run -n intelsight python "$ROOT_DIR/modules/cv-pipeline/run_cv_pipeline.py" \
    --input-dir "$INPUT_DIR" \
    --output-dir "$RUN_DIR" \
    --devices 0 \
    --frame-step "$FRAME_STEP" \
    --batch-size "$BATCH" || {
      echo "Benchmark profile failed: $profile" >&2
      exit 1
    }

done

echo "Benchmark matrix complete: $OUTPUT_ROOT"
