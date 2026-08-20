# Feature Request and Debugging Checklist

Date created: 2026-08-14
Owner: IntelSight dashboard + CV pipeline

## Feature Requests

- [x] Add desktop-style interactive dashboard with mission-level data review
- [x] Add linked 2D and 3D mapping views
- [x] Add SQLite mission digest for cached session restore
- [x] Add object focus synchronization (table, map, video context)
- [x] Prefer overlay video in Video tab when available
- [x] Add playback downscale options (1080p, 720p) with cache
- [ ] Add one-click overlay render trigger from dashboard
- [ ] Add frame thumbnail strip by object ID for rapid review
- [ ] Add mission tags/notes in digest database

## Debugging and Reliability

- [x] Fix Makefile dashboard launcher permission flow (run with bash)
- [x] Remove SQLite WAL dependency that caused workspace mount I/O issues
- [x] Add multi-runner startup fallback (mamba, conda, micromamba, streamlit)
- [x] Add PATH augmentation for common mamba/conda install locations
- [x] Add explicit launcher error when no environment runner is found
- [ ] Validate dashboard launch in target shell after mamba PATH confirmation
- [ ] Validate overlay-first playback on at least one generated overlay clip
- [ ] Validate 1080p and 720p preview cache generation on 4K source

## Geolocation and 3D Integrity

- [x] Add proxy object geolocation derivation from detection center + altitude
- [x] Add display coordinate fields and diagnostics in Objects table
- [x] Add local ENU 3D mode for stable visual alignment
- [ ] Add confidence/uncertainty rendering in 3D markers
- [ ] Add trajectory smoothing/optical flow refinement for high-motion segments

## Model and Runtime Baseline

- [x] Document current model/runtime stack
- [x] Document benchmark matrix for 4K24, 1080p60, 4K60
- [x] Document ONNX/Hugging Face migration target and requirements
- [x] Replace placeholder plate detector with a dedicated model flow via the functional LPR service
- [x] Add backend abstraction for Ultralytics and ONNXRuntime side-by-side in the service interface
- [ ] Add explicit runtime device resolver (`auto`, `cpu`, `cuda:N`) and CPU fallback validation
- [ ] Add worker partitioning controls for multi-video and multi-GPU processing
- [ ] Add GPU-aware optical flow path with CPU fallback for motion overlays
- [ ] Benchmark throughput on 1080p and 4K mission clips and record results in output/

## Validation Log

- [x] App and launcher files pass editor diagnostics after updates
- [ ] Run end-to-end demo pipeline with refreshed artifacts after latest updates
- [ ] Capture performance metrics for preview generation time and file size
- [ ] Record before/after playback smoothness with original vs cached previews
- [ ] Run the 4K24 / 1080p60 / 4K60 benchmark matrix once the external benchmark dataset is acquired

## Notes

- Update this file at the end of every feature cycle.
- Keep unchecked items specific and verifiable.
