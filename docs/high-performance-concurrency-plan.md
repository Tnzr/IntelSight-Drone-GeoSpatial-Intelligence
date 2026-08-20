# High-Performance Concurrency and Memory-Optimal CV Pipeline Plan

## Objective

Design the first performance-first, GPU-oriented, concurrency-aware computational pipeline for IntelSight that can:

- keep detection and object tracking fast enough for short-form and near-real-time processing
- preserve motion-informed re-identification across long temporal gaps without full frame rescans
- minimize peak memory usage and CPU churn
- support geospatial grounding from IMU + GPS + visual landmarks
- create a reusable motion and landmark dataset for 3D mapping and object persistence

This plan is deliberately written to optimize for the real hardware constraint: we have multiple GPUs available, motion-informed tracking is the correct strategy, and OCR/detection should no longer be treated as a naive full-frame scan on every frame.

---

## Core design principle

The pipeline must operate as a chronological sweep with temporal state, not as a batch of independent per-frame jobs.

A frame is not processed in isolation. It is processed in the context of:

- previous frame motion
- prior object tracks
- prior landmark observations
- IMU/GPS state from telemetry
- local optical-flow-informed motion priors
- object state continuity over 5–10+ seconds and possibly hundreds of frames

The runtime should therefore behave like a streaming state machine, where each new frame updates existing tracks and extends persistent object memory rather than re-running exhaustive detection and OCR across the entire scene.

---

## Target architecture

### 1. Streaming perception loop

The primary runtime loop is:

1. read next video frame
2. read synchronized telemetry (IMU, GPS, orientation)
3. update a temporal state object for active tracks
4. perform candidate motion update using prior frame optical flow and local ROI prediction
5. run detection only in active ROIs or changed regions
6. run OCR only for valid tracked plate candidates
7. write outputs to a compact event log for later rendering or map assembly

This replaces the earlier “detect everything every frame” logic with a sweep-driven windowed model.

### 2. Chronological sweep window

For each object or ROI, maintain a short motion window:

- previous 1–3 frames for immediate locally consistent motion
- previous 5–10 seconds for re-ID continuity
- previous 30–120 seconds for landmark persistence and route-level context

This supports the real requirement: the same object may persist for a long time, and the system should not be forced to rescan the entire image every time the object remains observable.

---

## GPU-first execution model

### 1. Device partitioning

Use a GPU-aware runtime with explicit process grouping.

- GPU 0: detection and feature extraction
- GPU 1: OCR and feature matching / SIFT tracking, if needed
- CPU: telemetry ingestion, queueing, geospatial assignment, serialization

This keeps heavy inference on the GPU while leaving CPU work to lighter tasks such as:

- queue management
- geometry bookkeeping
- map updates
- log writes
- Python orchestration

### 2. Model placement

Use model placement with explicit strategy:

- YOLO on CUDA when available, CPU fallback otherwise
- OCR on CUDA when backend supports it; otherwise keep it local to a dedicated worker pool
- SIFT/ORB/KLT feature extraction on GPU when possible, otherwise CPU fallback for small patches

### 3. Mixed precision

Use half precision where available for:

- initial detector inference
- feature extraction
- motion estimation kernels
- candidate embedding generation

Keep full precision for:

- final geolocation math
- telemetry fusion
- camera projection transforms
- map/landmark projection

---

## Concurrency model

### 1. Event-driven worker layout

The runtime should not be a single giant batch job. It should be structured in stages with bounded queues.

Recommended stages:

1. frame ingestion / decode
2. telemetry synchronization
3. motion prior and ROI prediction
4. detector stage for active ROI candidates
5. plate/OCR stage for surviving candidates
6. tracker / re-ID stage
7. landmark and map update stage
8. export stage

Each stage is a bounded queue with backpressure, so memory does not spike unexpectedly when a frame is delayed by OCR or heavy feature matching.

### 2. Bounded memory queue

Each queue should be bounded to a small fixed number of frames, e.g.:

- 2–4 frames for immediate motion queue
- 8–16 frames for active track buffer
- 32–64 frames for landmark / geometry cache

This reduces the common failure mode of “keep everything in memory until the pipeline stalls.”

### 3. Multi-video concurrency

For multiple mission clips or multiple synchronized feeds:

- assign one worker per GPU slice or per clip group
- preserve one worker for CPU telemetry/handoff tasks
- avoid one giant shared numpy array for all frames across all clips

A good default is:

- GPU worker count = number of GPUs or GPU slices in use
- CPU worker count = 1–2 for telemetry and file export tasks
- no more than 2–3 active video streams per worker unless the workload is clearly independent

---

## Motion-informed re-identification strategy

### 1. Use local optical flow first

Motion informed re-ID should be the primary optimization path. The same object should not need to be re-detected from scratch if it remains in the same ROI and continues to move smoothly.

Recommended logic:

- compute optical flow for the last N frames on a local ROI
- estimate object displacement vector for each tracked box
- project the prior object center into the current frame
- only run detection when the track is weak, new, or leaves the ROI

This reduces the expensive detection step from “scan full frame” to “scan likely motion corridor.”

### 2. Re-ID windowing

Each active object should maintain state:

- object id
- last observed box
- motion vector
- feature signature (appearance) from a lightweight embedding or color + shape descriptor
- OCR result history
- plate confidence history
- track age in frames
- last geolocation estimate

When object age > threshold:

- continue to track using motion prior and local feature matching
- use sparse feature matching (SIFT/ORB/KLT) on the ROI instead of scanning the whole image
- only run full detection if the object disappears, changes dramatically, or the confidence drops below a threshold

### 3. Motion continuity rule

When the object passes the motion continuity test, the pipeline should favor:

- track continuity
- ROI propagation
- small local feature search
- low memory re-use

Full re-detection should be treated as a last resort, not as the normal path.

---

## Memory optimization principles

### 1. Frame retention policy

Do not retain raw frames for the entire video.

Instead:

- keep current and previous frame only for immediate motion estimation
- keep only a compact feature descriptor or ROI metadata for longer-term tracks
- store evidence frames and cropped plate images only when a track is confirmed or suspicious

This keeps RAM bounded and avoids huge sliding frame buffers.

### 2. Sparse landmark cache

Landmarks should be tracked as compact metadata keyed by object id / pixel coordinate / world coordinate, not as full frame copies.

Recommended landmark record:

- object id
- frame index
- image-space position
- world-space estimate
- feature descriptor summary
- point cloud / SIFT keypoints (only for active map windows)
- IMU pose state
- GPS / altitude estimate

This is critical for later 3D mapping and object persistence.

### 3. ROIs instead of full-frame arrays

Many operations should be computed on ROI crops rather than the full frame:

- optical flow
- feature matching
- OCR
- SIFT and ORB extraction
- geospatial projection

Full-frame arrays should only be used when absolutely needed for global map registration or fallback detection.

---

## Visual landmark tracking and 3D mapping

### 1. SIFT/ORB dataset generation

The system should build a compact visual feature dataset over time to support 3D map reconstruction and object persistence.

Recommended design:

- every Nth frame, compute sparse features for the scene or active ROI
- store features keyed by frame id and object id
- maintain temporal links between frames with feature overlap
- accumulate a small set of landmarks that survive across multiple frames

The goal is not to store every feature for every frame. The goal is to store a compact, queryable landmark subset that supports:

- feature matching across adjacent frames
- persistence of static scene points
- object motion analysis
- visual map registration to geospatial coordinates

### 2. Multi-frame depth and motion estimation

When there is displacement, multiple frames should be used jointly to estimate depth and motion.

Recommended strategy:

- use a short 5–20 frame window for structure-from-motion-like tracking
- use IMU/GPS orientation as an anchor for camera pose
- estimate 3D scene points using triangulation or pseudo-depth from motion + known camera intrinsics
- fuse to world coordinates when global pose is available

This is how the system can build a map from local motion and landmarks rather than relying solely on direct GPS patches.

### 3. Geospatial grounding from IMU and GPS

The flight log in `data/flightrecords/flight_mission_drone/FlagerPublix/FlightRecord_2026-08-14_[18-37-30]_PublixParking.txt` is highly valuable because it contains the true flight-state data:

- IMU orientation
- GPS position
- velocity and motion state
- sensor timing and frame relationships

This is the correct anchor for map construction.

The overlay path should not be the only geospatial source. The true geolocation pipeline should use:

- GPS as global anchor
- IMU for orientation and motion estimate
- visual landmarks for local correction
- optical flow for object displacement in image space
- projection math for assigning 3D world positions to objects

The result should be a stable camera-ground projection model plus local visual feature constraints.

---

## Geo-registration strategy

### 1. Camera projection model

Use a camera model with:

- known or approximated focal length
- geospatial camera pose from IMU and GPS
- yaw/pitch/roll from flight telemetry
- altitude and velocity constraints

Then estimate world positions for candidate objects based on:

- 2D image-space box center
- optical flow magnitude and direction
- local scene depth proxy
- altitude and camera state

### 2. Landmark registration

Each object or static scene landmark should be assigned:

- image-space observation
- world-space estimate
- uncertainty estimate
- observation count
- time window

As more observations arrive, the landmark becomes more precise and stable.

### 3. Map assembly

A 3D map should be assembled from:

- persistent scene landmarks
- moving object tracks
- georeferenced sensor observations
- repeated sightings over time

This can later feed:

- route-level analytics
- object persistence and geofencing
- lane detection and parking behavior analysis
- driver/object correlation across the scene

---

## Performance targets

### Near-term performance goal

For 1080p mission clips on the available GPU stack, the target should be:

- detection and tracking dominated by ROI-based updates
- OCR only on tracked, valid plate candidates
- no full-frame rescans on stable tracks
- 5–15 fps throughput for research-grade live tracking workloads
- substantially lower latency than a full brute-force re-detection pass

### Memory goal

- bounded queue memory
- no retained full-frame pileup for long-duration clips
- feature cache only for active object tracks and landmarks
- explicit cleanup of stale state older than the configured observation horizon

### Accuracy goal

- maintain track continuity across 5–10+ second intervals
- preserve OCR continuity across a moving object
- continue localized mapping even when the target briefly exits a ROI

---

## Implementation order

### Phase 1: stateful streaming tracker

- build a streaming track state object
- implement motion prior / ROI prediction
- add local ROI-only detection using previous frame motion
- keep a bounded track memory

### Phase 2: GPU-first runtime

- add device selection for CUDA/CPU
- add per-GPU worker grouping
- use bounded queues and explicit memory limits
- keep the pipeline deterministic and logged

### Phase 3: re-ID and OCR throttling

- run OCR only on active track candidates
- reuse prior OCR result when motion is consistent and confidence is high
- avoid OCR if the object is static and unchanged

### Phase 4: landmark and SIFT layer

- build sparse feature extraction for active ROIs and keyframes
- store landmarks with compact metadata
- connect tracks to landmark observations

### Phase 5: IMU/GPS projection and 3D mapping

- fuse flight telemetry with visual landmarks
- generate world-space estimates for static and dynamic objects
- validate against known parking lot and geofence data

### Phase 6: metric and benchmark loop

- record throughput, memory, and track persistence
- compare brute-force vs ROI-first vs motion-first paths
- keep benchmark outputs in `output/` for engineering review

---

## Recommended immediate next step

The next implementation target should be a stateful, ROI-first pipeline with explicit concurrency layers and track memory. The first step is not a broad rewrite of every subsystem. It is the creation of a minimal streaming tracker that:

- uses current + previous frame motion to predict ROI
- updates object boxes without full-frame rescans
- maintains per-track memory for 5–10+ seconds
- runs OCR only on active track candidates
- logs all observations with raw GPS/IMU context

This creates the right foundation before adding a larger SIFT / landmark / 3D mapping layer.

---

## Summary

The correct strategy is not to make the current pipeline “a little faster.” The correct strategy is to rebuild it as a motion-aware, ROI-first, GPU-scheduled, bounded-memory streaming perception system that uses temporal continuity as its primary optimization principle.

This matches the real-world needs of:

- visual tracking through long sequences
- geospatial grounding from IMU/GPS/landmarks
- motion-informed re-ID across long gaps
- memory-efficient concurrent processing
- 3D landmark and map generation from object and scene persistence

The result is a pipeline that is simultaneously faster, more deterministic, and much more suitable for real-world geospatial intelligence than a frame-by-frame brute-force CV approach.
