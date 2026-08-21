# ML Runtime Technical Baseline

Date: 2026-08-14

## Current pipeline model stack

### Detector and OCR runtime

- Runtime type: local Python inference (no remote model service)
- Framework: Ultralytics + PyTorch in the `intelsight` mamba environment
- OCR: EasyOCR local reader
- Execution location: on host CPU by default, with optional GPU if available in the selected environment

### Model checkpoints currently referenced

- Vehicle detection model: `yolov8n.pt`
  - Loaded in `LazyModels.vehicle_model()` in `modules/cv-pipeline/run_cv_pipeline.py`
- Plate detection model: `yolov8n.pt` placeholder
  - Loaded in `LazyModels.plate_model()` in `modules/cv-pipeline/run_cv_pipeline.py`
  - This is a temporary placeholder and should be replaced by a dedicated plate detector
- OCR model: EasyOCR built-in text recognition
  - Loaded in `LazyModels.ocr_model()` in `modules/cv-pipeline/run_cv_pipeline.py`

### Geolocation behavior in current stages

- Synced stage (`*.detections.geotagged.csv`): primarily telemetry-stamped latitude/longitude near drone pose for each matched frame
- Fused stage (`*.detections.geotagged.fused.csv`): object-level geolocation via multi-frame proxy fusion using detection center offsets and altitude
- Report stage (`lp_vehicle_report.geojson`): map-ready object points for dashboard use

## Current dashboard playback behavior

- Video tab now supports overlay-preferred video selection.
- Video playback resolution options:
  - `original`
  - `1080p` cached preview
  - `720p` cached preview
- Downscaled previews are generated on demand and cached under:
  - `output/web-dashboard/video-previews/`

## Motion estimation and kinematic proxy baseline

### Current motion stack

- Primary motion estimator: dense optical flow with ROI-constrained overlays in the CV lab and helper module
- Implementation location: `render_optical_flow()` and `render_motion_heatmap_overlay()` in `modules/cv-pipeline/render_overlay_video.py`
- Notebook runtime: `modules/cv-pipeline/cv_pipeline_lab.ipynb`
- Motion proxy semantics: translation and rotation are treated as interpretable scene-level motion estimates, not a true rigid-body 6-DoF solution

### Runtime behavior

- Motion is computed on a selected ROI rather than the full frame when a vehicle-centered ROI is available.
- The ROI chooser prefers a relevant moving object or vehicle region and falls back to a static landmark or full-frame region when no strong vehicle candidate exists.
- The generated summaries include:
  - `translation_px`
  - `translation_vector_px`
  - `translation_vector_m`
  - `translation_m`
  - `rotation_proxy_deg`
  - `mean_speed_px`
  - `active_ratio`

This gives a useful motion proxy for frame-to-frame work, object selection, and trajectory reasoning before higher-fidelity onboard inertial or geometric estimation is available.

### Visual interpretation

The live notebook and overlay helper are designed to show three related motion views in a common row:

1. previous frame and current frame context
2. prev→current dense-flow overlay
3. current→next dense-flow overlay
4. ROI-focused flow context or local motion heatmap

This layout makes it easy to distinguish between scene motion, object motion, and background drift while preserving a single, interpretable ROI emphasis.

### Spatial matching baseline for object continuity

To keep the motion pipeline efficient without a heavy learned matcher, a baseline OpenCV-native search strategy is recommended:

- extract SIFT or ORB descriptors from tracked object crops and recent frame regions
- attach each descriptor to image coordinates `(x, y)` and a timestamp
- sort features by coarse spatial bucket or `(y, x)` ordering
- index features into a lightweight grid or binary-tree-like spatial structure
- query only nearby buckets inside the motion offset ROI instead of brute-forcing the whole frame

This yields a fast short-term re-identification path for vehicle continuity and object linking, especially in scenes where most of the background remains static.

### Physical limitation to keep explicit

The current motion estimate is a strong visual kinematic proxy, not yet a full 6-DoF pose estimate. A true model should eventually fuse:

- IMU orientation and angular rate
- GPS or RTK localization priors
- altitude and camera intrinsics
- long-horizon object track continuity

Keep the existing flow-based metrics as a reliable early baseline while moving toward a calibrated, sensor-fused ego-motion model.

## Benchmark plan for test flights

### Candidate acquisition profiles

1. 4K @ 24 FPS (baseline historical profile)
2. 1080p @ 60 FPS (motion-clarity candidate)
3. 4K @ 60 FPS (high-detail + high-temporal candidate)

### Required benchmark outputs

Per flight profile, capture:

- Throughput
  - end-to-end pipeline wall time
  - frames processed per second
- Detection quality
  - vehicle precision/recall on validation slices
  - plate OCR success rate
- Geolocation quality
  - unique object geolocation count
  - mean geolocation spread (`geo_spread_m`)
  - proxy offset distribution (`proxy_ground_offset_m`)
- Playback performance
  - dashboard startup time
  - median video seek-to-frame latency
  - effective playback smoothness with original and downscaled previews

## ONNX + Hugging Face migration target

### Why migrate

- Better portability across GPU backends
- Lower inference latency with optimized ONNX execution providers
- Access to stronger community plate and vehicle models

### Runtime target

- Primary runtime: `onnxruntime-gpu`
- Fallback runtime: `onnxruntime` CPU
- Optional acceleration layers:
  - TensorRT execution provider where available
  - model quantization for edge deployments

### Candidate model families to evaluate

- Vehicle/object detectors
  - YOLO-family ONNX exports with strong small-object performance
  - RT-DETR style detectors where latency permits
- License plate detectors
  - dedicated plate detectors (not general COCO placeholders)
- OCR models
  - CRNN/SVTR/PaddleOCR-style ONNX exports with robust motion blur handling

### Integration requirements for ONNX path

- Add model registry file with:
  - model source
  - input resolution
  - expected classes
  - confidence thresholds
  - hardware profile compatibility
- Add runtime adapter interface in CV pipeline so backends are swappable:
  - Ultralytics/PyTorch backend
  - ONNXRuntime backend
- Log inference backend and model IDs in every output artifact for provenance

## Immediate engineering action items

1. Replace plate placeholder detector with a dedicated plate model.
2. Add backend abstraction to support ONNXRuntime inference side-by-side with current Ultralytics path.
3. Run the 3-profile benchmark matrix (4K24, 1080p60, 4K60) and publish QA report with quality and latency deltas.
4. Add optical-flow-assisted trajectory refinement to reduce object localization drift in high-motion segments.
