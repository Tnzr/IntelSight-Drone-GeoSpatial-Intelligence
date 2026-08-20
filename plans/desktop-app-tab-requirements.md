# Desktop App Tab Functional Requirements

Scope: `desktop-app/` (Tauri + React + Leaflet). This document is the functional
specification for the mission explorer tabs and the backlog for improvements.
Settings are persisted locally (localStorage); no account or server required.

Status legend: [x] implemented · [~] partial · [ ] planned

## Tabs

### Overview — mission intake and session summary [x]
- [x] Mission root directory picker with scan (walkdir classification: trajectory / detections / summary / media).
- [x] Scan progress reporting via channel.
- [x] Recent missions list (localStorage) with re-open.
- [x] Session stat cards: trajectory files, detection files, summary files, media files.
- [x] File candidate lists with names and sizes.
- [ ] One-click "open recent mission and auto-scan" when the directory still exists (currently re-opens but requires manual scan).

### Video — CV workbench [x]
- [x] Media selection restricted to video files from the scan.
- [x] SRT telemetry auto-match by stem.
- [x] Cached 10s H.264 proxy preview (ffmpeg, app cache dir).
- [x] CV preview layers: detections, ROI optical flow, Re-ID matches; confidence, frame stride, clip duration, ROI padding, device.
- [x] Start offset trim control (launch-footage skip, default 10s).
- [x] Run manifest: rendered layers, detections JSONL path, SQLite database path.
- [ ] Playback resolution presets (original / 1080p / 720p cached) — parity with web-dashboard.
- [ ] One-click rerun with same configuration (persist last run config).
- [ ] Plate/OCR pass trigger: feed geotagged detections (rear views included) into the plate detection + OCR batch path and merge results into the identity database.

### Map — identity map [x]
- [x] Leaflet map over SRT trajectory polyline; identities as markers from ground-ray geolocation.
- [x] maxZoom 22 for meter-level identity separation.
- [x] Display modes: "Latest positions" vs "Entire observation history".
- [x] Selecting an identity draws its observation path (dashed) + history points and opens the profile panel.
- [x] Identity profile: representative ROI crop, sightings, frame span, confidence, Re-ID score, ORB matches, position, position spread, position model, plate status, observation history list.
- [ ] Geofence overlay layer (parking lots, points of interest) loaded from the future PostGIS layer.
- [ ] Spatial query: "identities within X m of point" box/radius selection.

### Database — persisted objects [x]
- [x] Session object table from the current CV run (SQLite-backed payload).
- [x] Database path disclosure for provenance.
- [ ] Multi-run aggregation view: merge identities across runs/videos (same mission, different clips).
- [ ] Plate history lookup by plate text across missions (depends on plate/OCR pass and PostGIS ingestion).

### Charts — altitude profile [x]
- [x] Relative altitude buckets across the selected SRT trajectory; peak + sample stats.
- [ ] Motion/kinematics chart (translation proxy, rotation proxy from the lab) as a second chart.

### Workshop Lab [x]
- [x] Renders per-module demo PNGs from `output/lab-artifacts/manifest.json` (Rust `list_lab_artifacts` command).
- [x] Refresh button; empty-state instructions.
- [ ] Regenerate artifacts from the app (invoke `export_lab_artifacts.py` through the Python env).

### Settings — preferences [ ] (implementing now)
- [ ] CV defaults: device, confidence, frame stride, clip duration, start offset, ROI padding — applied to the workbench on startup.
- [ ] Remember last mission root and prefill the directory field on startup.
- [ ] Default map display mode (latest / history).
- [ ] Clear recent missions list.
- [ ] Reset to defaults.

## Persistence model

- localStorage keys: `intelsight.recentMissions` (string[]), `intelsight.settings` (JSON object).
- Per-run artifacts (overlay mp4, detections JSONL, objects JSON, SQLite `object-recognition.sqlite3`, identity crops) live under the Tauri app data dir `cv-runs/<video-stem>/`.
- Mission media stays read-only; the app never modifies source footage.

## Non-goals for the desktop app

- No facial recognition, no owner lookup (project rules).
- No cloud uploads; the app is a local operator tool with direct filesystem access.
- PostGIS-backed features land after the geospatial database phase (Phase D); the app consumes them via the API service, not by embedding PostGIS.
