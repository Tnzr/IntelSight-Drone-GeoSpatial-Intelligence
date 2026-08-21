# Repo Audit and Implementation Path

Date: 2026-08-20
Scope: full-repo audit of IntelSight code, docs, environment, and outputs, followed by a sequenced implementation path.

---

## Part 1: Audit findings

### 1.1 What exists and is verified working

| Component | Location | Status |
|---|---|---|
| Rust DJI TXT parser | `modules/flightrecord-parser/` | Works. Produces `frames.csv`, `trajectory.geojson`, `metrics.json` for 2024-05 TXT logs and 2026-08-13 flight records (`output/flightrecords/`) |
| CV pipeline (detect -> sync -> fuse -> report) | `modules/cv-pipeline/` | Works end-to-end on `demo_0120` (detections.jsonl, geotagged.csv, fused.csv, GeoJSON/HTML report present) |
| License plate service (OCR, fusion) | `modules/cv-pipeline/license_plate_service.py` | Covered by tests |
| Web dashboard (Streamlit) | `modules/web-dashboard/` | Functional; mission digest SQLite exists at `output/web-dashboard/mission_digest.sqlite3` |
| Test suite | `tests/` | 33/33 pass under `/home/tnzr/.local/share/mamba/envs/intelsight/bin/python` (1.2s) |
| Desktop app (Tauri + React + Leaflet) | `desktop-app/` | Scaffold with a real 874-line mission explorer; early stage, unverified build |
| Legacy flight visualizer | `modules/flight-visualizer/` | Superseded by web-dashboard; candidate for removal or archival |
| Device resolver | `modules/cv-pipeline/run_cv_pipeline.py:88-107` | `resolve_devices` exists with cpu/cuda:N handling |

### 1.2 Environment and runtime findings

- The `intelsight` env lives at `/home/tnzr/.local/share/mamba/envs/intelsight`, but no `mamba`/`micromamba` binary exists at `/home/tnzr/.local/share/mamba/bin/`.
- `resolve_mamba_bin` in `scripts/run_*.sh` falls through to `/home/tnzr/anaconda3/bin/conda`, whose env root does NOT contain `intelsight`. Running via that conda fails with `The given prefix does not exist`. **`make dashboard` is currently broken.**
- Fix: resolve the env python directly (`.../envs/intelsight/bin/python -m streamlit`) as the primary path, or add the correct mamba root to the candidate list. This is the unchecked item "Validate dashboard launch in target shell after mamba PATH confirmation" in `docs/feature-debug-checklist.md`.
- The repo-local `.venv` and `.conda` are stale and correctly documented as non-authoritative.

### 1.3 Repo hygiene findings

- Only 2 commits exist (docs only). All implementation code is untracked: `modules/`, `tests/`, `scripts/`, `desktop-app/`, `Makefile`, `environment.yml`, `.gitignore`.
- `os` — a 44 MB stray PostScript file at repo root (likely an accidental shell redirect). Remove.
- Root `package-lock.json` exists with no root `package.json` (orphan; real manifests are in `desktop-app/`). Remove.
- `yolov8n.pt` / `yolov8n-seg.pt` model weights at repo root are not gitignored. Move to `models/` (ignored) or add `*.pt` to `.gitignore`.
- `.secrets/dji.env` is correctly ignored (`.secrets/*` rule). Good.
- `data/` is empty and correctly ignored; `output/` is ignored and not committed.

### 1.4 Documentation findings

- `engineering/README.md` references files that do not exist there (`engineering-requirements.md`, `implementation-plan.md`, `px4-multicamera-platform.md`, `sigint-payload-roadmap.md`, `technical-architecture.md`); the real files are in `docs/`. Stale.
- `business-economics/README.md` references `financial-projections.md`, `market-positioning.md` which do not exist. Stale.
- Root `README.md` references a `src/` directory that does not exist.
- `docs/implementation-plan.md` contains a duplicated "Phase 1.5" section (lines ~136-179) and duplicate heading numbering (two `## 8.` sections). Needs dedup.
- Overlapping planning docs create ambiguity about what is "the plan": `docs/implementation-plan.md`, `engineering/sprint-backlog.md`, `docs/high-performance-concurrency-plan.md`, `docs/performance-optimization-plan.md`, `docs/ml-runtime-technical-baseline.md`, `docs/perception-ai-rd-backlog.md`, `docs/visual-kinematic-inference-backlog.md`. The sprint backlog should be the canonical sequencing source; the others should be referenced from it, not parallel plans.

### 1.5 Gap analysis vs sprint backlog

| Backlog area | State |
|---|---|
| Sprint 0 (env, module boundaries, schema) | Mostly done; runtime resolution bug remains |
| Sprint 1 (telemetry parsing) | Done for TXT + SRT; parser tested on real logs |
| Sprint 2 (geotagged frame extraction) | Done via SRT sync on `demo_0120`; **`output/cv/FlagerPublix/synced` and `fused` are empty — that mission is not fully processed end-to-end** |
| Sprint 3 (plate detection + OCR) | Working, but plate detector is still the `yolov8n.pt` placeholder and vehicle make/model is a placeholder field |
| Sprint 4 (georectification) | Only proxy geolocation (detection center + altitude). No camera-projection model, no terrain correction, no per-observation uncertainty yet |
| Sprint 5 (PostGIS + API) | Not started |
| Sprint 6 (pattern-of-life) | Not started |
| Sprints 7-10 | Planning only |

---

## Part 2: Implementation path forward

Sequencing rule: complete the offline evidence chain (Sprints 2-5) before the streaming/perf rebuild, and keep the concurrency workstream parallel but non-blocking.

### Phase A — repo stabilization (small, do first)

1. Remove stray artifacts: `os`, root `package-lock.json`; move `*.pt` weights to an ignored `models/` dir.
2. Fix runner scripts (`scripts/run_*.sh`) and `Makefile` to resolve the `intelsight` env correctly; verify `make dashboard` launches.
3. Commit the codebase in logical chunks (modules, tests, scripts, config) with a clean `.gitignore`.
4. Fix stale doc references (engineering/, business-economics/ READMEs, root README `src/`); dedup `docs/implementation-plan.md`.

### Phase B — finish Sprints 2-3 definition of done

1. Re-run the full `run_lp_geospatial_pipeline.sh` on FlagerPublix and produce synced + fused + overlay + report artifacts; record metrics in `output/`.
2. Replace the placeholder plate detector with a dedicated plate model (registry entry: source, input resolution, classes, thresholds).
3. Add vehicle make/model/color placeholder -> real attribute model path or explicitly defer with a documented gate.
4. Unchecked dashboard items: overlay-render trigger, thumbnail strip by object ID, mission tags/notes; validate overlay playback + 1080p/720p previews on 4K source.

### Phase C — Sprint 4: real georectification

1. Implement camera projection model (ray from pixel, IMU pose rotation, GPS translation, ground-plane intersection) behind the existing geolocation interface.
2. Emit per-observation uncertainty (horizontal spread, method label, confidence class) — schema already sketched in `docs/engineering-requirements.md` sections 3.2/5.
3. Validate against known landmarks/surveyed points; compare against current proxy mode and record the delta.

### Phase D — Sprint 5: geospatial database + API

1. Stand up PostGIS; create schema for missions, detections, geofences, evidence (fields already listed in engineering requirements).
2. Ingestion path from `lp_vehicle_report.geojson` / fused CSV; geofence tagging; GeoJSON query endpoints with auth.

### Phase E — Sprint 6: pattern-of-life analytics

1. Plate association across missions; geofence-based timelines; heuristic anomaly scoring; aggregate-only outputs for sensitive categories.

### Phase F — performance and concurrency workstream (parallel to C/D)

Follow `docs/high-performance-concurrency-plan.md` in order, but scope each step to measurable change:
1. Device resolver validation (`auto`/`cpu`/`cuda:N`) + CPU fallback (resolver code exists; needs CLI wiring + tests).
2. Worker partitioning for multi-video/multi-GPU.
3. GPU optical flow path with CPU fallback in the overlay renderer.
4. Run the 4K24/1080p60/4K60 benchmark matrix from `docs/ml-runtime-technical-baseline.md`; publish results to `output/`.
5. Only after C/D stabilize: begin the stateful ROI-first streaming tracker rebuild and the ONNX backend abstraction.

### Deferred / gated

- Desktop app parity with web-dashboard (defer until web-dashboard feature set is frozen).
- PX4 autonomy, SIGINT, and vertical expansion remain planning-gated per sprint backlog.

---

## Part 3: Immediate next actions (this cycle)

- [ ] Remove `os` and root `package-lock.json`; relocate model weights; fix `.gitignore`
- [ ] Fix mamba env resolution in `scripts/run_*.sh` + `Makefile`; verify `make dashboard`
- [ ] Commit current codebase
- [ ] Re-run FlagerPublix end-to-end pipeline and record outputs
- [ ] Dedup/stale-fix docs (implementation-plan duplicate sections, README cross-refs)
- [ ] Replace plate placeholder model or document the gated deferral
