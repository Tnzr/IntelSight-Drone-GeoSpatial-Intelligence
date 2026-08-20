# Web Dashboard Feature Addition Log

Date: 2026-08-14

## Goal

Implement desktop-style mission visualization without redundant loading of large raw videos, while keeping interactive 2D/3D views and a digested database-backed workflow.

## Added features

1. Mission digest database layer
- Added local SQLite store for mission selections.
- Stores mission metadata, trajectory rows, and detection rows.
- Supports listing cached missions and restoring full mission payloads.
- File: modules/web-dashboard/store.py

2. Cached mission load mode
- Added a third dashboard source mode: Cached mission.
- Users can filter and select prior mission digests.
- Selected digest restores trajectory, detections, summary, and video hint.
- File: modules/web-dashboard/app.py

3. Linked object interactions
- Added stable object IDs to normalized detections.
- Added focused object selector in sidebar.
- 2D and 3D charts expose object IDs in custom data.
- Table supports row selection callback.
- Selected object propagates across table, maps, and video details.
- File: modules/web-dashboard/app.py

4. Frame-targeted raw video preview
- Video remains optional and is loaded only when selected.
- Added FPS input and frame-to-second conversion.
- Focused object drives start time in video panel using frame or frame_start.
- File: modules/web-dashboard/app.py

5. Dashboard documentation refresh
- Added notes on SQLite digest and on-demand video behavior.
- File: modules/web-dashboard/README.md

6. Mission history and focus improvements
- Added filterable cached mission picker and restore path.
- Added object focus selector and table/map/video contextual drill-down.
- Added frame-based video targeting from selected object.
- File: modules/web-dashboard/app.py

## Data flow

1. User picks Workspace files, Upload files, or Cached mission.
2. App loads trajectory and detection frames.
3. App assigns object IDs and applies filters.
4. If enabled, app persists selected mission to SQLite digest.
5. UI renders:
- 2D map
- 3D map
- Objects table
- Optional raw video at selected frame
- Database tab with mission history

## Validation executed

1. Python syntax and diagnostics
- Verified no editor errors in:
  - modules/web-dashboard/app.py
  - modules/web-dashboard/store.py

2. Real artifact ingest round-trip
- Loaded trajectory and detection artifacts from:
  - output/flightrecords/FlightRecord_2026-08-13_[18-17-18].trajectory.geojson
  - output/cv/demo_0120/lp_vehicle_report.geojson
  - output/cv/demo_0120/lp_vehicle_report.summary.json
- Ingested to SQLite and reloaded rows.
- Result:
  - trajectory rows cached: 54
  - detection rows cached: 213
  - mission rows cached: 1

3. Environment/API checks
- Confirmed Streamlit version 1.61.1 supports selection callbacks on plotly and dataframe widgets used by the linked selection behavior.

4. Demo run
- Regenerated demo artifacts for synchronized, fused, and report outputs:
  - output/cv/demo_0120/synced/DJI_20260813183811_0120_D.detections.geotagged.csv
  - output/cv/demo_0120/fused/DJI_20260813183811_0120_D.detections.geotagged.fused.csv
  - output/cv/demo_0120/lp_vehicle_report.html
  - output/cv/demo_0120/lp_vehicle_report.summary.json
  - output/cv/demo_0120/lp_vehicle_report.geojson
- Ran headless dashboard startup check on port 8512 and confirmed server boot.

## Notes and constraints

- SQLite WAL mode caused disk I/O failures on this workspace mount and was removed for portability.
- The database path is output/web-dashboard/mission_digest.sqlite3.
- Video frame targeting assumes FPS input (default 30) when explicit source FPS metadata is unavailable.

## Next improvements

1. Add direct click-to-object synchronization from map selection into table scroll position.
2. Add mission tags and notes fields in SQLite for analyst workflow.
3. Add optional precomputed frame thumbnail strips keyed by object ID for faster review.

## 2026-08-14 geolocation and 3D corrections

1. Detection geolocation refinement
- Added normalized detection center and frame-size fields to synced records in `modules/cv-pipeline/sync_detections_with_srt.py`.
- Added proxy pixel-offset geolocation fusion in `modules/cv-pipeline/fuse_plate_observations.py`.
- New fused fields include `proxy_ground_offset_m` and updated `geolocation_mode` values (`single_frame_pixel_proxy`, `multi_frame_pixel_proxy`).

2. 3D map stabilization
- Fixed detection altitude normalization precedence in `modules/web-dashboard/app.py` so existing `altitude_m` values are preserved.
- Added a local ENU 3D mode (`East, North, Up` in meters) for robust trajectory + object rendering.
- Added 3D coordinate space selector in the sidebar (`local_meters`, `geodetic`).

3. Validation snapshot
- Regenerated demo artifacts and measured fused coordinate diversity:
  - rows: 213
  - unique lat/lon pairs: 210
  - geolocation mode mix: 125 single-frame pixel proxy, 88 multi-frame pixel proxy
- Verified 3D figure generation creates scatter3d traces with local meter axes.

## 2026-08-14 video overlay and playback performance updates

1. Overlay-first video workflow
- Added overlay video discovery patterns in `modules/web-dashboard/app.py`.
- Added source mode selector (`overlay_preferred`, `overlay_only`, `raw_only`).
- Dashboard now prioritizes overlay assets in the Video tab when available.

2. On-demand downscale playback caching
- Added playback resolution options in Video tab: `original`, `1080p`, `720p`.
- Added on-demand preview generation with cache under `output/web-dashboard/video-previews/`.
- Uses `ffmpeg` when available and falls back to OpenCV resize/transcode path.

3. Documentation baseline for model/runtime stack
- Added `docs/ml-runtime-technical-baseline.md`.
- Documents current model/runtime, geolocation stages, benchmark matrix, and ONNX/HuggingFace migration path.

4. Demo launch verification result
- `make dashboard` was executed as smoke test.
- Launch currently fails in this shell because no `mamba`, `conda`, `micromamba`, or `streamlit` command is available on PATH.
- `scripts/run_web_dashboard.sh` was hardened with multi-runner fallback and explicit error reporting.
