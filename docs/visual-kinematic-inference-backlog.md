# Visual-Kinematic Inference Backlog

## 1. Objective

Create a GPU-first visual-kinematic inference stack that estimates scene motion and object kinematics from drone video with enough fidelity to support a downstream 6-DoF motion estimate, object tracking, and geospatial event reasoning.

The current optical-flow logic is useful as a motion proxy but it does not yet recover true rigid-body 6-DoF state. This backlog defines a path from the current two-frame motion summaries to a production-ready, optimized inference pipeline that is much faster and more physically interpretable.

## 2. Problem statement

Current behavior:

- optical flow is computed on full frame or ROI windows
- the motion estimate is scene-level and approximate
- runs are too slow for a streaming or near-real-time pipeline
- frame-to-frame runtime is dominated by repeated decode, CPU preprocessing, and non-batched processing
- the current pipeline lacks true 3D pose reasoning and sensor fusion

Target outcome:

- process motion windows in near-real time on GPU
- recover a strong motion prior for translation and rotation
- estimate per-object kinematics and scene-level ego motion from video + telemetry
- support future fusion with IMU, GPS, and georeference priors

## 3. Design principles

1. Keep the fast path cheap and ROI-driven.
2. Do not run dense inference on the whole frame when a small ROI is sufficient.
3. Use sparse motion features to gate expensive dense models.
4. Fuse visual motion only where it improves the motion estimate.
5. Keep memory pressure low by streaming frames and reusing tensor buffers.
6. Treat 6-DoF outputs as probabilistic estimates with uncertainty, not as exact ground truth.

## 4. Proposed architecture

### Stage A: fast ROI gating

Purpose:
- detect relevant regions before running dense inference
- reduce compute from whole-frame analysis to candidate motion zones

Components:
- lightweight object detector (YOLOv8/YOLOv9/RT-DETR depending hardware budget)
- motion confidence map from frame differencing and temporal median filtering
- ROI proposal stage that selects vehicle or scene motion patches
- optional vehicle tracking branch to maintain persistent object IDs across frames

Expected impact:
- reduce full-frame optical-flow compute by 5x to 20x in typical mission footage
- reduce GPU memory bandwidth during motion inference

### Stage B: dense motion estimation

Purpose:
- estimate per-pixel or per-patch motion more accurately than classical Farneback

Candidate models:
- RAFT
- PWC-Net
- MobileRAFT for lower-latency inference
- custom lightweight CNN/UNet branch trained for flow + uncertainty estimation

Recommended starting point:
- run a compact flow model on a low-resolution pyramid of the selected ROI
- gradually expand to full-frame inference only when the ROI gate indicates high uncertainty

### Stage C: motion-to-kinematics head

Purpose:
- convert flow fields into kinematic estimates with physical meaning

Outputs:
- X, Y, Z translation priors
- roll, pitch, yaw rotation priors
- motion confidence and uncertainty
- object-level velocity estimates

Recommended formulation:
- estimate 2D motion field and scene flow from dense optical flow
- backproject using camera intrinsics and altitude priors
- infer translation from ego-motion + object motion decomposition
- encode rotation using heading and camera frame decomposition

This stage should output:
- `translation_m` as a world-scaled proxy
- `x_proxy_m`, `y_proxy_m`, `z_proxy_m` as interpretable motion axes
- `roll_deg`, `pitch_deg`, `yaw_deg` as angular priors
- `uncertainty` values for each estimate

### Stage D: sensor fusion layer

Purpose:
- improve physical validity and reduce drift

Inputs:
- IMU data
- GPS / GNSS
- altitude / barometer
- object tracks
- optic flow estimates

Fusion strategy:
- Kalman filter or factor-graph motion tracker
- state vector with position, velocity, angular velocity, and confidence
- update motion estimates with IMU and map priors

This creates the transition from visual motion proxies to a true 6-DoF motion estimate with external constraints.

## 5. OpenCV-native baseline recognition strategy

A deployable baseline should not require a heavy learned matcher before the pipeline is stable. For an operational ROI-first stack, use OpenCV-native feature extraction and a spatially grouped matching scheme that keeps costs low while remaining interpretable.

### 5.1 Feature grouping by spatial neighborhood

1. Extract SIFT or ORB features from the current frame and a short-term object memory.
2. Keep each feature descriptor together with its image-space coordinates `(x, y)`, object ID, and frame timestamp.
3. Sort features by `(y, x)` or by a coarse grid-cell index so all local neighbors are adjacent in memory.
4. Build a lightweight spatial index or grid hash over the feature map, then group features by patch or object ROI.
5. For each incoming object candidate, query only the neighbors inside a radius around its predicted position instead of brute-forcing all features in the frame.

This gives a fast nearest-neighbor search with near-linear behavior in the typical case for vehicle-sized ROIs and a bounded radius search around the expected motion offset.

### 5.2 Motion-aware ROI gating

Use optical flow and the last object centroid to predict where a vehicle should appear in the next frame. Then:

- offset the ROI by the estimated flow vector
- shrink the search area to the motion prior
- apply descriptor matching only inside that local region
- keep a short-term object database keyed by object ID and last-seen centroid

This reduces the search space dramatically and is particularly useful when the scene has many static landmarks but only a few moving vehicles.

### 5.3 Binary-tree or grid-style search baseline

A practical baseline is a coarse spatial index:

- divide the image into fixed cells or blocks
- bucket features by cell
- use the previous centroid plus optical-flow offset to select nearby candidate cells
- run descriptor matching only within those cells
- validate with geometric checks such as homography, RANSAC, or basic distance thresholding

This is easier to debug than a full neural matcher and behaves well for small mission windows where most of the image is irrelevant background. It is also a good way to accelerate re-identification, association, and short-term object continuity before moving to a learned visual-kinematic head.

### 5.4 Expected performance profile

- low overhead in CPU-only settings
- strong improvement over exhaustive matching when the candidate set is constrained by ROI and motion priors
- robust enough as a baseline method for object continuity and short-term ID maintenance
- easy to extend toward a learned embedding later without abandoning the same ROI-first pipeline

This baseline is intentionally compatible with the existing OpenCV toolchain, which keeps the implementation reliable while establishing the memory and search patterns that support a more advanced GPU-optimized matcher later.

## 6. GPU optimization plan

### 6.1 Reduce full-frame work

- run detector on keyframes only
- compute motion only in candidate ROIs
- drop repeated optical-flow work for static regions
- skip background areas with low temporal variation

### 5.2 Use a batched pipeline

- read and preprocess multiple frames into a fixed-size buffer
- batch ROI crops before flow estimation
- avoid Python per-frame overhead in the hot loop
- use pinned memory and async transfer for GPU input

### 5.3 Use mixed precision where possible

- run float16 or bfloat16 on supported GPU hardware
- keep master state in FP32 for numerically stable final outputs
- use TensorRT / ONNX Runtime / TorchScript for inference optimization

### 5.4 Optimize memory

- reuse tensor buffers for frame queues
- downscale large ROIs early
- preallocate output tensors for batched flow estimation
- free temporary arrays immediately after each stage
- use grayscale or single-channel tensors for flow precompute when possible

### 5.5 Parallelize the pipeline

- decode video on CPU asynchronously from a queue
- run object detection and motion estimation in separate workers
- maintain a predictor queue to overlap compute and memory transfer
- use GPU streams where possible

## 6. Recommended implementation sequence

### Milestone 1: ROI-first motion inference

Deliverables:
- ROI proposal from object detector + motion map
- farneback or CUDA flow restricted to candidate patches
- summary metrics for object kinematics and scene motion
- per-frame uncertainty reporting

Goal:
- reduce runtime to 5-10 fps on a consumer GPU while maintaining sensible motion estimates

### Milestone 2: compact learned flow model

Deliverables:
- train a small optical-flow or scene-flow network on mission data
- use a UNet-style backbone on concatenated pre-frame and current-frame inputs
- output flow field + per-pixel confidence

Goal:
- improve robustness to static background and partial occlusion
- increase motion discrimination over classical CV methods

### Milestone 3: 6-DoF motion head

Deliverables:
- translation and rotation head from dense flow and tracked features
- world-scale estimation from altitude and camera intrinsics
- uncertainty model

Goal:
- estimate a physically meaningful motion prior for ego-motion and object kinematics

### Milestone 4: sensor fusion and memory pruning

Deliverables:
- IMU + GNSS + optical flow fusion through a Kalman filter
- adaptive frame skipping for low-motion periods
- memory-efficient event windowing

Goal:
- robust long-horizon motion estimates and reduced compute in low-activity scenes

## 7. Model candidates and tradeoffs

### Option A: classical + learned hybrid

Best for:
- faster development and simpler debugging

Pipeline:
- ROI selection
- classical flow / KLT features
- learned confidence scorer
- kinematic head

Pros:
- reliable baseline
- easy to inspect and explain
- lower training burden

Cons:
- less accurate than dense learned flow models

### Option B: CNN/UNet flow predictor

Best for:
- scene motion estimation and ROI motion segmentation

Pipeline:
- pre_frame + curr_frame -> UNet -> flow + confidence
- flow -> translation + rotation head

Pros:
- strong model for local motion patterns
- good candidate for downstream prediction tasks

Cons:
- training data burden
- more GPU memory requirements

### Option C: full RAFT/PWC-style stack

Best for:
- best motion fidelity and stronger research-grade results

Pros:
- accurate flow and tracking behavior
- strong baseline for dense motion tasks

Cons:
- slower than compact models
- may be too heavy for real-time edge compute without optimization

## 8. Realistic performance targets

For a mission pipeline, target the following progression:

- current state: ~2 frames/s on heavy CPU-heavy processing
- target after ROI gating + batching: 5-10 fps on a desktop GPU
- target after learned compact flow: 15-30 fps on a midrange GPU, depending on resolution and ROI size
- target for optimized edge deployment: near real-time or event-triggered processing with burst inference on candidate windows

These numbers are realistic if the pipeline avoids whole-frame dense flow on every frame and instead operates on sparse, tracked, motion-prone regions.

## 9. Research directions

- learn a motion-conditioned encoder on `pre_frame + curr_frame + imu` pairs
- train uncertainty-aware motion heads
- estimate object-centric kinematics in addition to scene-level ego motion
- infer dynamic scene geometry from multi-frame motion rather than single pair assumptions
- explore self-supervised training with frame reconstruction and future-frame prediction

## 10. Backlog summary

Priority order:

1. Remove stale notebook flow references and restore notebook correctness.
2. Replace full-frame flow with ROI-first motion estimation.
3. Add batching and GPU-optimized preprocessing.
4. Add compact learned flow model trained on mission data.
5. Add translation/rotation head and uncertainty output.
6. Add IMU/GPS fusion with state estimation.
7. Integrate event windows into the downstream geospatial pipeline.

## 11. Immediate next action

The next engineering move should be:

- build a GPU-optimized motion runner around ROI-first inference
- keep the old optical flow path as a fallback
- add a compact learned flow model as a second stage
- output normalized X/Y/Z and roll/pitch/yaw priors with confidence
- fuse those priors with telemetry before exporting geospatial evidence

This will keep the system computationally viable while moving toward true 6-DoF motion estimation rather than just a scene-level motion proxy.
