# CV Pipeline (Vehicle + Plate)

This module is the first implementation scaffold for offline computer-vision processing on mission videos.

## Goals

- detect vehicles in aerial footage
- detect license plates
- run OCR on plate crops
- support multi-GPU batch throughput
- record computational bottlenecks per stage

## Pipeline stages

1. frame sampling from MP4
2. vehicle detection (YOLO)
3. plate detection (YOLO)
4. OCR (EasyOCR) with blur-aware enhancement pass
5. frame-to-SRT synchronization for geotagging
6. multi-frame plate confidence fusion and de-duplication
7. interactive map + listing report export
8. overlay-video rendering for step-by-step visual inspection
9. performance metrics export

## Multi-GPU strategy

- split input videos across workers
- assign each worker to a GPU device id
- batch frames per worker
- no frame-to-frame dependency by default for detection stage

## Run (example)

```bash
conda run -n intelsight python modules/cv-pipeline/run_cv_pipeline.py \
  --input-dir data/flightrecords/flight_mission_drone \
  --output-dir output/cv/flight_mission_drone \
  --devices 0,1 \
  --frame-step 2 \
  --batch-size 16
```

## End-to-end LP geospatial report

Use the orchestrator script to run detection, telemetry sync, fusion, map report, and overlays:

```bash
scripts/run_lp_geospatial_pipeline.sh \
  data/flightrecords/flight_mission_drone \
  output/srt/flight_mission_drone \
  output/cv/flight_mission_drone
```

Key outputs:

- `output/cv/.../detections/*.detections.jsonl` raw frame-level detections
- `output/cv/.../synced/*.geotagged.csv` SRT-synced per-detection geotags
- `output/cv/.../fused/*.fused.csv` multi-frame fused LP observations
- `output/cv/.../lp_vehicle_report.html` interactive map and sortable listing
- `output/cv/.../lp_vehicle_report.summary.json` automated summary for downstream dashboards or review queues
- `output/cv/.../lp_vehicle_report.geojson` map-ready LP and vehicle observations with review status
- `output/cv/.../overlay/*.overlay.mp4` annotated step-by-step visual overlays with telemetry HUD, localized-object coordinates, and inset map relay

## Educational lab notebook

For step-by-step visual inspection of the current algorithm, use [modules/cv-pipeline/cv_pipeline_lab.ipynb](/media/tnzr/HDD11/PCC/PioneerInnovationsCollective/Ventures/PioneerInnovationsCollective_ventures/IntelSight-Drone-GeoSpatial-Intelligence/modules/cv-pipeline/cv_pipeline_lab.ipynb).

The notebook walks through:

- frame difference scoring between adjacent sampled frames
- vehicle detection on a representative mission frame
- vehicle-derived lower-band plate proposal generation
- OCR gating and reuse decisions for stable tracks
- fused geospatial observation review using current pipeline outputs

## Notes

- Start with 1080p/60 for better motion handling and throughput.
- Keep 4K originals archived, but run first-pass analytics on downsampled/selected frames.
- Add optical-flow stabilization later for difficult blur scenes.

## Current implementation status

- Multi-frame fusion already improves low-confidence plate reads by selecting the best normalized OCR result across supporting frames.
- The report now emits a review-oriented summary and GeoJSON export so detections can feed both the HTML map and downstream geospatial tooling.
- The overlay renderer now consumes SRT and synced localization CSV outputs so demo footage can show in-frame geo annotations and a map relay view alongside detections.
- Vehicle make/model is still a placeholder field in the current detector output, so richer vehicle-property classification remains a next implementation target.
