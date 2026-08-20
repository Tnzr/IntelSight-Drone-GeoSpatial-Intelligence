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

## UI engineering requirements: Mission Explorer

Detailed implementation checklist: [docs/mission-dashboard-implementation-checklist.md](docs/mission-dashboard-implementation-checklist.md)

### Product-facing baseline copy

INTELSIGHT

# Mission Explorer

DATA SOURCE

Browse folder

Scan mission folder

OPERATIONS

## Desktop mission review

Ready to inspect a mission folder.

### No mission data loaded yet

Choose a mission folder, then scan it to surface any geojson/csv annotation files.

### UI intent

- The desktop app is a mission browser first, not a generic file manager.
- The primary task flow is: choose folder, scan mission, inspect artifacts, review results.
- The interface must feel operational, calm, and explicit about state so the user never wonders whether the app is idle, scanning, or failed.
- The UI should support future mission data types without forcing a redesign of the main layout.

### Core layout requirements

- Keep a stable three-part mental model: source selection, operation controls, and mission review surface.
- Use a clear hierarchy for the mission title, data source actions, and operational status.
- Keep the empty-state screen useful, not decorative, so first-run users can immediately understand the next action.
- Preserve the same layout skeleton when data loads so the screen does not jump or reflow unexpectedly.

### Interaction requirements

- Browse folder must open a folder picker and return a root mission path.
- Scan mission folder must operate only on the selected mission root and must not silently scan unrelated locations.
- The scan action must be disabled, de-emphasized, or clearly constrained until a valid folder exists.
- The UI must show progress, completion, and failure states for each scan request.
- The UI must allow repeated scans of the same mission root without requiring an app restart.
- The UI must support switching mission roots quickly when the operator moves between datasets.

### Data presentation requirements

- Surface geojson, csv, and other reviewable annotations as distinct artifact types.
- Show count, path, size, and last-known classification for each surfaced artifact.
- Distinguish telemetry-derived data from extracted annotations and derived outputs.
- Make it clear when results are raw, normalized, fused, or map-ready.
- Present mission artifacts in a way that can later accommodate imagery, overlays, reports, and exports without changing the control model.

### State model requirements

- The empty state must explicitly represent “no mission selected” and “mission selected but not scanned” as different states.
- The loading state must preserve the current mission root and indicate the active operation.
- The success state must summarize the scan result in a compact, reviewable form.
- The error state must preserve the user’s folder selection so recovery is immediate.
- State transitions must be predictable and reversible where possible, especially after failed scans or folder changes.

### Flexibility and foresight requirements

- The UI architecture must be extensible for future panels such as map view, timeline view, detection review, OCR review, and export review.
- The source selector and scan control must be reusable for future mission data types, not hard-coded to one exact dataset shape.
- The review surface should be able to host multiple tabs or panes without reworking the top-level flow.
- The app should tolerate additional artifact classes such as images, videos, PDFs, JSON reports, and database exports.
- The design should support future automation, including saved missions, recent missions, and rescan history.

### Reliability requirements

- Every backend call must fail visibly and recoverably.
- The UI must not clear the current mission selection when a scan fails.
- Errors should include enough context to debug the folder, backend call, or artifact type that failed.
- The app should remain usable when one artifact type fails to parse.
- Long-running operations should be cancelable or at least visibly interruptible in a future iteration.

### Accessibility and operator ergonomics

- Use readable contrast and clear focus states.
- Ensure the folder picker, scan action, and mission review surface are keyboard reachable.
- Keep the interface legible at laptop-scale and workstation-scale windows.
- Use plain action labels and explicit status text instead of relying on color alone.
- Avoid dense control clusters that hide the primary scan workflow.

### Implementation guardrails

- Treat mission scan output as structured state, not ad hoc component-local data.
- Keep the UI state shape aligned with backend mission scan results so future panels can reuse it.
- Keep empty, loading, success, and error UI states as first-class variants in the implementation.
- Prefer deterministic presentation order for scan results so repeated scans are visually stable.
- Keep the mission explorer shell coherent even as additional tools and views are added later.
