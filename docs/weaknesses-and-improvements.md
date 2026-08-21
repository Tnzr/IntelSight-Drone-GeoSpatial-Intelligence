# IntelSight Weaknesses and Improvement Opportunities

Date: 2026-08-20

## 1. CV Pipeline Performance & Architecture

- **Pre-computed overlays only**: The interactive frame inspector shows detection boxes (pre-computed) but not optical flow, feature correspondences, or segmentation masks. These are baked into the overlay video during the batch run, not available for live inspection.
- **Batch-only processing**: The entire pipeline (detect → track → geolocate → fuse) runs as a single batch pass. No streaming, no pause/resume, no mid-run parameter adjustment.
- **No live FPS visualization**: FPS is tracked per-frame and charted post-run, but there's no real-time FPS display during processing.
- **Single-GPU only**: No multi-GPU worker partitioning; no CPU fallback when CUDA is unavailable (the resolver exists but isn't wired into the preview runner).
- **Model loading overhead**: YOLO model is loaded fresh for every preview run; no model caching across runs.

## 2. Geolocation Accuracy

- **Nadir camera assumption**: Ground-ray projection assumes the camera points straight down. DJI SRT carries no gimbal pitch/yaw — only aircraft attitude from the TXT log. Oblique footage produces systematic positional errors.
- **No terrain/DEM correction**: All rays intersect a flat ground plane at relative altitude. Real terrain elevation changes are ignored.
- **Single-source geolocation**: Only the ground-ray method exists. No camera-projection refinement, no SfM triangulation, no multi-frame bundle adjustment.
- **GPS noise**: Heading is derived from GPS deltas over ~0.5s windows. GPS jitter at low speeds produces noisy heading estimates.

## 3. 3D View

- **No coordinate reference labels**: The 3D scene has RGB axes (X=east, Y=up, Z=-north) but no text labels, scale markers, or compass indicator.
- **No 2D map as ground plane**: The ground is a flat grid. No satellite imagery, no OSM tiles projected onto the 3D ground plane.
- **No Visual SLAM**: No structure-from-motion, no visual odometry, no point cloud reconstruction. The 3D view only shows trajectory + objects + rays.
- **No depth perception aids**: No shadows, no altitude markers, no distance indicators between objects.

## 4. Charts

- **No time axis labels**: The line charts show "Time bucket" as the X label but don't map bucket index to actual seconds or frame numbers.
- **No interactive tooltips**: Hovering over chart points doesn't show the exact value or timestamp.
- **No multi-run comparison**: Charts only show the current run's data. No overlay of previous runs for performance comparison.

## 5. Interactive Frame Inspector

- **No live parameter adjustment**: Optical flow, segmentation, and geolocation algorithm parameters are fixed at run time. No on-the-fly toggling.
- **Video glitches**: The ffmpeg proxy (Blob URL) sometimes shows decoding artifacts or missing frames, especially with long clips.
- **No frame-by-frame stepping**: No single-frame advance/rewind controls.
- **No side-by-side comparison**: Can't compare two parameter sets on the same frame.

## 6. Database & Identity

- **No cross-run identity matching**: Track IDs are run-local. The same vehicle appearing in two different clips gets different IDs.
- **No plate OCR integration**: The plate detection/OCR pipeline exists in the web-dashboard but is not wired into the desktop app's CV preview.
- **No temporal queries**: Can't query "show me all detections between 10:00 and 10:30" or "show me identity #5's full timeline."

## 7. Mission View

- **Fixed 4-panel layout**: The Map + 3D + Database + Profile layout is hardcoded. No resizable panels, no collapsible panels, no custom layouts.
- **No synchronization**: The 3D view camera doesn't follow the map selection, and the map doesn't pan to the 3D selection.

## 8. Infrastructure

- **Two checkouts**: The workspace (HDD11) and home clone (`~/IntelSight-Drone-GeoSpatial-Intelligence`) drift apart. Sync is manual via rsync.
- **No CI/CD**: No automated tests on push, no linting, no type checking in CI.
- **No Docker**: PostGIS, API service, and the app itself have no containerized deployment path.
- **Hardcoded paths**: Python env path (`/home/tnzr/.local/share/mamba/envs/intelsight/bin/python`) and repo root fallback are machine-specific.

## 9. Priority Recommendations

1. **Visual SLAM / 2D map ground plane** — highest user interest; would dramatically improve 3D situational awareness.
2. **Live parameter toggling** — optical flow, segmentation, geolocation algorithm selection during inspection.
3. **Cross-run identity matching** — essential for multi-mission analysis.
4. **Plate OCR integration into desktop app** — closes the gap between web-dashboard and Tauri app.
5. **Terrain-aware geolocation** — DEM integration for accurate ground intersection.
6. **Unified single checkout** — eliminate the workspace/home-clone drift.
