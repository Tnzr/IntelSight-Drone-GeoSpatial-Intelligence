# IntelSight: Audit and Implementation Path

Date: 2026-08-20 · Status: implementation-ready
Owner of execution: implementation-capable agent (planning agent makes no source changes)

---

## Context

IntelSight is a phased drone intelligence platform. This plan sequences work from the audited current state to the next milestone: an end-to-end offline pipeline with real (non-proxy) geolocation, a dedicated plate detector, a desktop playback UX, and a PostGIS data layer.

### Audited current state (verified)

- Rust TXT parser works (`modules/flightrecord-parser/`): `frames.csv`, `trajectory.geojson`, `metrics.json` in `output/flightrecords/`.
- Batch CV pipeline works end-to-end on `demo_0120` (`modules/cv-pipeline/`); FlagerPublix is only partially processed (detections exist; `synced/` and `fused/` are empty).
- Tests: 33/33 pass via `/home/tnzr/.local/share/mamba/envs/intelsight/bin/python`.
- Broken: `make dashboard` and all `scripts/run_*.sh` env resolution. Root cause: `/home/tnzr/.local/bin/{mamba,conda}` are dangling symlinks to a removed `/tmp/micromamba-bin/bin/micromamba`; the runner chain falls through to `/home/tnzr/anaconda3/bin/conda`, whose env root lacks `intelsight`.
- Git: only 2 docs-only commits; all code untracked. Stray files: 44MB PostScript `os` at root, orphan root `package-lock.json`, unignored `yolov8n*.pt` weights.
- Docs: stale cross-references (engineering/, business-economics/, root README `src/`), duplicated "Phase 1.5" and duplicate `## 8.` headings in `docs/implementation-plan.md`.
- Telemetry facts: SRT CSVs have `focal_len` + drone pose, no camera attitude. Rust parser exports aircraft pitch/roll/yaw, no gimbal fields.
- Media: raw footage is NOT in the workspace. Verified at `/media/tnzr/AuxVolume/datasets/FlightTests/flightrecords/flight_mission_drone/` — `FlagerPublix/` (4 MP4s, 0.5–1.3GB, + SRT/LRF/TXT) and `7thStreet/` (3 MP4s).

---

## Resolved decisions

1. **Geolocation path**: streaming tracker + SfM is the primary Phase C work (per `docs/high-performance-concurrency-plan.md`), built as a NEW module; the batch cv-pipeline stays untouched as the validated reference until the tracker beats its proxy geolocation on a measured benchmark.
2. **Module boundary**: new `modules/streaming-tracker/`. No in-place refactor of `modules/cv-pipeline/`. No Rust port of the tracker at this stage.
3. **SfM depth**: sliding-window (5–20 frames) two-view triangulation with IMU/GPS pose anchors and per-track landmark store. No global bundle adjustment in the first iteration.
4. **Plate detector**: adopt `license_plate_detector.pt` from github.com/Muhammad-Zeerak-Khan/Automatic-License-Plate-Recognition-using-YOLOv8 (MIT, trained on Roboflow LPR v4, ground-level imagery) behind a model registry entry, with a mandatory precision/recall eval gate on aerial FlagerPublix frames; existing vehicle lower-band plate heuristic remains as fallback. Fine-tune only if the gate fails.
5. **Vehicle attributes**: carparts-seg (Ultralytics, 23 part classes, NO plate class) integrated for vehicle footprint masks + occlusion handling and color voting now; make/model classification deferred to Sprint 6 with an explicit gate.
6. **Database**: Docker Compose postgis image + FastAPI service; schema per `docs/engineering-requirements.md` section 5.
7. **Media**: source is the AuxVolume path above; restore (copy or symlink) into gitignored `data/flightrecords/flight_mission_drone/`. Validation/preview runs default to a 10–20s launch-skip offset (beginnings are uneventful launch footage).
8. **Desktop UX**: Tauri app un-deferred as the primary interactive surface (filesystem access, no 1–2GB uploads). Playback UX (offset, trim, resolution, overlay toggle) built there. Electron + Effect TS considered and rejected for this cycle; revisit only if a server-hosted online service becomes a requirement.
9. **Web-dashboard**: stays as the server-side reviewer (files local to operator server). Its unchecked interactive items (overlay-render trigger, thumbnail strip, mission tags) move to Tauri.
10. **OCR engine**: keep EasyOCR now; PaddleOCR-style candidates deferred to the ONNX migration step (Phase F).

---

## Phases and ordered tasks

### Phase A — Repo stabilization (first, unblocks everything)

1. Remove `os` and root `package-lock.json`; relocate `yolov8n.pt`/`yolov8n-seg.pt` into an ignored `models/` dir (or add `*.pt` to `.gitignore`).
2. Fix env resolution in all `scripts/run_*.sh` and `Makefile`: check the env python (`/home/tnzr/.local/share/mamba/envs/intelsight/bin/python`) FIRST and run `python -m streamlit`, before any mamba/conda candidates. Verify `make dashboard` launches and the app serves.
3. Commit the codebase in logical chunks (modules, tests, scripts, config, docs) with a clean `.gitignore`; never commit `data/`, `output/`, `.secrets/`, `.venv/`, `.conda/`, `models/`.
4. Doc fixes: stale refs in `engineering/README.md`, `business-economics/README.md`, root README (`src/`); dedup `docs/implementation-plan.md` (duplicate Phase 1.5, duplicate `## 8.`); declare `engineering/sprint-backlog.md` the canonical sequencing doc and add a pointer to this plan.

### Phase B — Sprint 2/3 closure + media restore

1. Restore FlagerPublix media from `/media/tnzr/AuxVolume/datasets/FlightTests/flightrecords/flight_mission_drone/FlagerPublix/` into `data/flightrecords/flight_mission_drone/FlagerPublix/` (copy; keep the archive intact).
2. Add CLI trim controls to `modules/cv-pipeline/run_cv_pipeline.py`: `--start-offset-sec` (default 10) and `--duration-sec` (optional), applied to frame sampling and SRT sync windows.
3. Model registry (new file in `modules/cv-pipeline/`, e.g. `model_registry.py`): entries for vehicle model, plate model (Zeerak `license_plate_detector.pt`, source URL, MIT license note, input resolution, class `license_plate`, confidence threshold), carparts-seg (AGPL-3.0 dataset license — flag for legal review before any production use), OCR model. Log model IDs and backend in every output artifact for provenance (per `docs/ml-runtime-technical-baseline.md`).
4. Wire the plate model into `LazyModels.plate_model()`; write an eval-gate script that compares it against the vehicle lower-band heuristic on sampled FlagerPublix frames (precision/recall + timing) and writes results to `output/`. Keep the heuristic fallback path.
5. Integrate carparts-seg masks: per-vehicle footprint polygon (mask center-of-mass/contact line) exported into detections and used as the geolocation anchor candidate; occlusion flag when parts overlap neighboring vehicles.
6. Color voting: padded-crop multi-sample color voting in `fuse_plate_observations.py`; emit `color`, `color_votes`, `footprint_mode` in fused CSV + `lp_vehicle_report.geojson` + summary JSON.
7. Re-run the full `scripts/run_lp_geospatial_pipeline.sh` on FlagerPublix with the offset controls; produce synced, fused, overlay, report artifacts and record metrics in `output/`.
8. Unit tests for registry, trim logic, color voting, footprint extraction.

### Phase G — Tauri desktop UX (parallel track, independent of C)

1. Video tab playback controls: launch-skip offset (default 10–20s), trim duration, resolution (original / 1080p / 720p cached previews), overlay-preferred toggle.
2. Local mission directory import via Rust command (scan user-chosen or `data/` dirs; no upload path). Prefer overlay video when available (existing behavior).
3. Move unchecked web-dashboard items: one-click overlay render trigger, frame thumbnail strip by object ID, mission tags/notes in digest DB.
4. Validate `scripts/run_desktop_app.sh` builds and launches on this host; keep Streamlit working in parallel (server reviewer role).

### Phase C — Streaming tracker + SfM (new module; validation depends on Phase B step 1)

1. Extend the Rust parser to export gimbal attitude (check dji-log-parser API for Mini 4 Pro TXT fields; if unavailable, document and use aircraft attitude + nadir assumption as fallback).
2. New `modules/streaming-tracker/`: chronological sweep state machine — frame ingest → telemetry sync → motion-prior ROI prediction → detection only in active ROIs → OCR only on active plate candidates → export. Bounded queues (2–4 frames motion, 8–16 tracks, 32–64 landmarks), bounded track memory.
3. Device resolver (`auto`/`cpu`/`cuda:N`) + per-GPU worker grouping, built in from the start (port the resolver logic from `run_cv_pipeline.py:88-107`).
4. Sparse feature layer: SIFT/ORB on keyframes/ROIs keyed by frame/track with temporal links; sliding-window (5–20 frames) two-view triangulation anchored by IMU/GPS from TXT; landmark store with observation count + uncertainty.
5. Camera-ground projection: `focal_len` from SRT (35mm-equivalent → pixel conversion with documented sensor size for Mini 4 Pro), fused pose (IMU/GPS/gimbal), ground-plane intersection at `rel_alt`; per-observation uncertainty (`geolocation_mode`, `geo_spread_m`, method label, confidence class) in the SAME fused CSV/GeoJSON schema the dashboard already consumes.
6. Validation gate: run the tracker on FlagerPublix offset segments; compare object geolocation error against known landmark points (e.g. parking lot line corners / surveyed features) AND against the batch proxy mode; record deltas and throughput (target reference: research-grade 5–15 fps from the concurrency plan) in `output/`. The tracker only graduates to default path when it measurably beats the proxy on this benchmark.

### Phase D — Sprint 5: PostGIS + API

1. `docker-compose.yml` with a postgis image + healthcheck; documented env config in `.secrets/` pattern.
2. SQL migration files for `missions`, `detections`, `geofences`, `evidence` per engineering-requirements section 5 field list (including `vehicle_attributes_json`, `metadata_json`, geofence geometry/type/owner).
3. New `modules/api-service/` (FastAPI): ingestion from fused CSV / `lp_vehicle_report.geojson`; geofence CRUD + point-in-polygon tagging; time/location/plate-history/venue-category queries; GeoJSON endpoints; basic auth + validation patterns.
4. Integration tests against the dockerized PostGIS (CI-friendly; skip gracefully if Docker unavailable locally).

### Phase E — Sprint 6: pattern-of-life analytics

1. Plate association across missions (with color/make-model-gated scoring; make/model work starts here).
2. Geofence-based timelines and history queries; heuristic anomaly scoring.
3. Aggregate-only outputs for sensitive site categories (privacy rule from AGENTS.md and requirements).

### Phase F — Residual performance items (interleaves with C/D)

1. GPU optical flow path with CPU fallback in `render_overlay_video.py`.
2. Benchmark matrix 4K24 / 1080p60 / 4K60 on restored media (offset segments); publish results in `output/`.
3. ONNX backend abstraction side-by-side with Ultralytics (adapter interface per `docs/ml-runtime-technical-baseline.md`); PaddleOCR-style OCR evaluation after that.

---

## Data flow (target end state)

```
data/flightrecords/** (gitignored media)
  └─ TXT  → Rust parser → frames.csv / trajectory.geojson
  └─ SRT  → parse_dji_srt → srt.csv
  └─ MP4  → [batch cv-pipeline (reference) | streaming-tracker (new)] → detections.jsonl
                     → sync → fused.csv (uncertainty, color, footprint)
                     → lp_vehicle_report.geojson/summary.json
                     → PostGIS ingestion → FastAPI → Tauri app (maps, playback, review)
```

## Validation plan

- Phase A: `make dashboard` launches; test suite still 33/33; git status clean and intentional.
- Phase B: FlagerPublix produces fused/report artifacts end-to-end; plate eval gate results recorded; new unit tests pass.
- Phase G: Tauri app builds and opens a FlagerPublix mission with offset playback and cached previews.
- Phase C: geolocation error deltas vs proxy + landmark ground truth recorded; tracker runs bounded-memory on a full clip.
- Phase D: ingestion of a fused CSV → spatial query round-trip → GeoJSON endpoint returns tagged detections.
- Phase E: repeated-plate clustering demo on two missions (7thStreet + FlagerPublix as available).

## Risks and failure modes

- **Plate model domain gap**: Zeerak detector trained on ground-level imagery may underperform aerially → eval gate decides; fallback heuristic + fine-tuning plan ready.
- **Licensing**: carparts-seg dataset is Ultralytics AGPL-3.0; MIT for the Zeerak repo code. Research use fine; production use needs license review (add to legal checklist).
- **Gimbal attitude availability**: if dji-log-parser cannot expose gimbal fields for these TXT files, projection accuracy degrades at oblique angles → documented nadir/aircraft-attitude assumption with inflated uncertainty, revisit later.
- **Disk**: media copies are multi-GB → prefer copy-once policy; keep AuxVolume archive as source of truth.
- **Tracker scope creep**: keep DoD narrow (beat proxy on benchmark, bounded memory, same output schema); defer BA, global maps, ONNX to later gates.
- **Privacy**: no facial recognition, aggregate-only sensitive-category analytics, data stays out of git.

## Open follow-ups (non-blocking)

- Fine-tune plate detector on drone footage if the eval gate fails.
- Legal review of AGPL assets before any non-research distribution.
- Revisit Electron + Effect TS only if a hosted online service becomes a product requirement.

---

## Progress log

### 2026-08-20 — Phase A complete + Workshop Lab delivered

- Phase A done: removed stray `os` + root `package-lock.json`; weights moved to gitignored `models/`; `.gitignore` extended (`models/`, `*.pt`, `*.onnx`, `.venv/`, `.conda/`); all `scripts/run_*.sh` + `Makefile` now resolve the intelsight env python directly; `make dashboard` verified (HTTP 200); doc dedup + stale reference fixes applied (implementation-plan, engineering/, business-economics/, root README).
- Media restored via symlink: `data/flightrecords/flight_mission_drone` -> AuxVolume `FlightTests/flightrecords/flight_mission_drone` (FlagerPublix + 7thStreet).
- Workshop Lab delivered: `cv_pipeline_lab.ipynb` rebuilt as per-module workshop (builder: `scripts/build_workshop_lab.py`); `modules/cv-pipeline/export_lab_artifacts.py` generates 7 demo PNGs + manifest into `output/lab-artifacts/`; web-dashboard gained a "Workshop Lab" tab + `make lab` mode (AppTest-verified, no exceptions); Tauri app gained a Workshop Lab tab via new `list_lab_artifacts` Rust command (tsc + cargo check pass with fresh target dir; corrupted `desktop-app/src-tauri/target` removed).
- Tests: 33/33 pass. Git commit left to the user (not committed; per commit policy).
- Not yet done: Phase B CLI trim controls, plate model eval gate, carparts-seg footprint/color voting, FlagerPublix end-to-end rerun, Phase C tracker, Phase D PostGIS.
