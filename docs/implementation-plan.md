# Implementation Plan

## 1. Delivery strategy

The implementation should be organized in staged milestones. The first milestone is an end-to-end offline intelligence pipeline. The second milestone transitions toward live autonomy on a PX4 platform. This keeps the project aligned with real-world risk, hardware limitations, and learning cycles.

## 2. Phase 0: foundation and validation

### Goals

- confirm telemetry extraction path from DJI flight records
- establish reproducible dataset capture workflow
- validate candidate vision stack and OCR strategy
- prove the selected runtime is the dedicated Mamba `intelsight` env for all mission validation

### Work packages

- set up Python environment and Rust toolchain with Mamba/Conda
- install and validate `dji-log-parser`
- test extraction on representative flight logs
- create frame extraction and synchronization scripts
- build initial license plate detection harness using YOLO
- validate OCR output quality on cropped plates
- run validation against the FlagerPublix dataset in the correct env

### Output

- test dataset and parsing benchmark
- geotagged image set
- reproducible baseline pipeline
- validation report for mission footage processed in the Mamba environment

## 2.5. Phase 0.5: production validation and root-cause repair

### Goals

- fix environment mismatch between repo-local `.venv` and Mamba `intelsight`
- verify that FlagerPublix footage runs under the correct environment
- establish a repeatable mission validation routine for sensitive datasets

### Work packages

- prioritize `/home/tnzr/.local/share/mamba/envs/intelsight` as the authoritative runtime
- fix shell runners to prefer Mamba before Conda in PATH resolution
- validate CV dependencies (`cv2`, `torch`, `ultralytics`, `easyocr`) in the mission env
- test the target dataset without leaking raw footage into the repo

### Validation gate

The pipeline must be proven on the FlagerPublix dataset using `mamba run -n intelsight` before downstream OCR and geolocation improvements are considered complete.

## 3. Phase 1: offline geospatial intelligence pipeline

### Goals

- convert raw drone data into a geospatial evidence dataset
- track where detections happen and when
- map detections to contextual geofences
- improve plate recognition from a generic box pass to a segmentation-first OCR pass
- replace the GPS proxy with a camera-ground projection estimate

### Work packages

- implement telemetry normalization and mission metadata model
- geotag extracted frames and create event records
- run YOLO-based detection on geotagged datasets
- run segmentation-first OCR on plate crops, then normalize and vote across frames
- build georectification on top of IMU + GPS + camera model
- store detections in PostgreSQL + PostGIS
- expose GeoJSON endpoints and simple dashboard

### Success metrics

- plate detection confidence and precision within validated threshold
- geolocation confidence on a repeatable test route
- complete end-to-end pipeline from flight log to mapped detections
- camera-ground projection geolocation outperforms the earlier static GPS proxy

## 3.1. R&D backlog: multimodal video digestion and homemade perception AI

### Goals

- move beyond object-only recognition into a tokenized, multi-scale video intelligence layer
- support behavioral summaries, event-level interpretation, and downstream human prompting or voice-AI interfaces
- incorporate motion understanding into object localization and state estimation

### Architectural direction

- Use YOLO or similar fast detectors as the first-stage sparse perception gate for latency-sensitive detection.
- Add a lightweight deep-feature/embedding pathway for temporal summarization at multiple scales: seconds, minutes, hours, and days.
- Compress video into compact latent tokens or scene descriptors that can be stored and retrieved from a vector or relational database.
- Use temporal tokens to summarize behavior, route patterns, object interactions, and contextual abnormality rather than only frame-level boxes.
- Build a unified scene-reasoning layer that links: object tokens, motion tokens, geospatial tokens, and mission metadata tokens.
- Treat detection, classification, and geospatial grounding as a continuous evidence stack rather than a single final output.

### Proposed components

1. Fast perception front end
   - YOLO/segmentation model for bounding boxes, masks, and nearby object tracking
   - dedicated plate detection and vehicle instance segmentation stage
   - lightweight scene-level prefiltering to reduce unnecessary compute

2. Memory-efficient motion layer
   - SIFT / ORB / KLT feature tracking for object motion and motion-consistency scoring
   - optical flow and motion vectors for object-state tracking across adjacent frames
   - low-cost feature matching to approximate object trajectory without requiring full dense 3D reconstruction at every frame

3. Deep-feature tokenization layer
   - per-frame embeddings or token summaries from a lightweight CNN/ViT backbone
   - temporal pooling into second/minute/hour summaries
   - multi-scale token aggregation similar to latent scene summarization, but operationally aligned to behavior inference rather than only segmentation masks

4. Temporal digest engine
   - encode behavior over windows of time and compute event tokens for suspicious motion, repeated access, loitering, vehicle routing, crowding, and abnormal context
   - store these summaries in a queryable database for prompt-driven retrieval and operator explanation

5. Multimodal reasoning interface
   - connect spatial, motion, and textual summary tokens to downstream prompting systems, voice AI, or operator copilots
   - allow operators to ask for “show violent or high-risk interactions,” “identify aggressor/victim cues,” or “summarize unusual motion in this geofence” using derived tokens rather than raw frame dumps

### Performance and design constraints

- Keep the front end fast enough for real-time or near-real-time use on the available GPU budget.
- Use sparse, compact features and tokenization to control memory pressure.
- Downsample or summarize long-duration footage at the temporal digest layer while retaining evidence frames for operator review.
- Reserve high-cost video reasoning only for candidate event windows flagged by the fast front end.

### Near-term research priorities

- frame-to-frame motion embeddings for object tracking and geolocation refinement
- multi-scale token summarization for event detection and contextual anomaly ranking
- motion-aware object localization using segmentation + optical flow + feature tracking
- event grounding for violence detection, threat cues, and dual-role actor inference when the data supports it
- compatibility with dynamic prompting and retrieval-augmented human review workflows

## 4. Phase 1.5: analytics and pattern-of-life

### Goals

- infer patterns from repeated detections
- link vehicles to facilities, parking lots, and neighborhoods
- produce contextual intelligence for future target selection

### Work packages

- geofence definitions for parking lots, neighborhoods, casinos, nightclubs, hotels, dealerships
- historical association engine for repeated plate observations
- anomaly scoring based on time and place
- reverse geocoding and address-level enrichment where legally justified
- database queries for association graphs and habitual routes

### Success metrics

- repeated detections are clustered correctly
- contextual geofence tagging is consistent
- anomaly engine can rank unusual traffic behavior

## 4. Phase 1.5: analytics and pattern-of-life

### Goals

- infer patterns from repeated detections
- link vehicles to facilities, parking lots, and neighborhoods
- produce contextual intelligence for future target selection

### Work packages

- geofence definitions for parking lots, neighborhoods, casinos, nightclubs, hotels, dealerships
- historical association engine for repeated plate observations
- anomaly scoring based on time and place
- reverse geocoding and address-level enrichment where legally justified
- database queries for association graphs and habitual routes

### Success metrics

- repeated detections are clustered correctly
- contextual geofence tagging is consistent
- anomaly engine can rank unusual traffic behavior

## 5. Phase 2: open hardware autonomy stack

### Goals

- move from offline to live autonomous perception
- preserve the same geospatial intelligence logic in a real-time control loop

### Work packages

- prototype a PX4-based drone with companion compute
- integrate ROS2 nodes for flight state, perception, and mission planning
- add multi-camera processing for front/down/side views
- implement onboard event detection and geospatial tagging
- add mission adaptation logic based on fences and observations

### Success metrics

- autonomous flight with mission objectives and perception triggers
- onboard processing of detections without ground-station dependence
- safe behavior under degraded GPS and low-visibility conditions

## 6. Phase 3: fleet coordination and future RF intelligence

### Goals

- coordinate multiple drones around a map and mission objective
- extend the platform with additional sensing modes

### Work packages

- central mission planner with queueing and assignment logic
- vehicle and target tracking across swarm units
- RF / Wi-Fi / SDR sensing for geospatial signal mapping
- operator dashboard for fleet supervision and evidence review

## 7. Delivery order for coding agent

1. parser and telemetry normalization
2. geotagged frame extraction
3. YOLO detection and OCR harness
4. geospatial database and event schema

## 8. Performance optimization and concurrency workstream

### Goals

- remove CPU bottlenecks from dense optical flow and per-clip rendering
- add explicit device and worker controls for local GPU/CPU deployments
- preserve deterministic render output while maximizing frame throughput

### Work packages

- add runtime device selection for `auto`, `cpu`, and GPU IDs
- add multi-video worker partitioning and bounded queue management
- adopt GPU optical flow where CUDA is available with CPU fallback
- benchmark throughput on the FlagerPublix clips and record the results
- summarize throughput gains and remaining bottlenecks in engineering docs

### Immediate next steps

1. implement a device resolver helper and CLI flags in the CV pipeline
2. add per-run worker-count tuning and multi-video partition defaults
3. refactor the overlay motion path to try CUDA optical flow first, then fall back cleanly
4. validate on the real mission clips and record timing metrics
5. georectification engine
6. geofence and pattern-of-life analytics
7. dashboard and API layer
8. open-hardware autonomy integration

## 8. Risk management

- Maintain modular boundaries between telemetry parsing, perception, geospatial logic, and mission control.
- Validate every component with field data and reproducible tests.
- Avoid introducing live autonomy until the offline pipeline is stable.
- Keep system behavior understandable and observable for operators.
