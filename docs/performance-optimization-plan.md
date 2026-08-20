# Performance Optimization and Concurrency Plan

## Objective

Maximize throughput for the IntelSight CV and geospatial pipeline without sacrificing reproducibility, accurate motion overlays, or field-ready validation.

## Current baseline

- Dense optical flow in the overlay renderer runs in OpenCV on the CPU via `cv2.calcOpticalFlowFarneback`.
- Detection and OCR are already structured to accept a device target and can use GPU-backed inference when available.
- The CV pipeline already has worker-level multiprocessing for multiple videos, but the overlay render step is still fundamentally serial per clip.

## Improvement goals

1. Reduce frame-level render latency for 1080p/4K mission clips.
2. Keep CUDA paths optional and safe when no GPU is available.
3. Add explicit worker and device tuning controls without breaking the CLI.
4. Preserve deterministic output for mission evidence and render validation.

## Implementation plan

### Phase 1: explicit runtime device selection

- Add a device resolver for `auto`, `cpu`, `cuda:N`, and integer GPU IDs.
- Prefer CUDA when available and present a clean fallback to CPU.
- Log the resolved device at startup so render runs are reproducible.

### Phase 2: work partitioning and batch control

- Add frame-batching and queueing for mission clips.
- Keep one process per GPU or CPU worker group when processing multiple videos.
- Add a configurable `--max-workers` or equivalent worker count guard.

### Phase 3: GPU-accelerated motion path

- Use OpenCV CUDA optical flow when CUDA is available, falling back to Farneback CPU flow otherwise.
- Keep the heatmap and vector overlay logic equivalent between CPU and GPU paths.
- Minimize host-to-device transfers by computing ROI-only motion estimates.

### Phase 4: render-stage concurrency

- Parallelize independent clips or clip chunks when exporting demo reels.
- Separate decode, inference, and composition into distinct stages where possible.
- Use a bounded queue for frame processing to avoid memory spikes.

### Phase 5: tuning and benchmark validation

- Benchmark CPU vs GPU for 1080p and 4K clips.
- Record output duration, memory use, and throughput for the same footage.
- Keep a reproducible benchmark report in `output/` for downstream engineering decisions.

## Recommended execution order

1. Add runtime device selection helper and CLI validation.
2. Add worker-count controls and process partitioning.
3. Add GPU-aware motion-flow path with CPU fallback.
4. Benchmark throughput on the FlagerPublix dataset.
5. Add final render-performance report to the engineering docs.

## Milestone checklist

- [ ] runtime device resolution
- [ ] worker partitioning and queue discipline
- [ ] GPU motion path with CPU fallback
- [ ] benchmark validation on 1080p/4K clips
- [ ] engineering report and handoff summary
