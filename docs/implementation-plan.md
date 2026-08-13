# Implementation Plan

## 1. Delivery strategy

The implementation should be organized in staged milestones. The first milestone is an end-to-end offline intelligence pipeline. The second milestone transitions toward live autonomy on a PX4 platform. This keeps the project aligned with real-world risk, hardware limitations, and learning cycles.

## 2. Phase 0: foundation and validation

### Goals

- confirm telemetry extraction path from DJI flight records
- establish reproducible dataset capture workflow
- validate candidate vision stack and OCR strategy

### Work packages

- set up Python environment and Rust toolchain
- install and validate `dji-log-parser`
- test extraction on representative flight logs
- create frame extraction and synchronization scripts
- build initial license plate detection harness using YOLO
- validate OCR output quality on cropped plates

### Output

- test dataset and parsing benchmark
- geotagged image set
- reproducible baseline pipeline

## 3. Phase 1: offline geospatial intelligence pipeline

### Goals

- convert raw drone data into a geospatial evidence dataset
- track where detections happen and when
- map detections to contextual geofences

### Work packages

- implement telemetry normalization and mission metadata model
- geotag extracted frames and create event records
- run YOLO-based detection on geotagged datasets
- run OCR and normalize plate text
- build georectification on top of IMU + GPS + camera model
- store detections in PostgreSQL + PostGIS
- expose GeoJSON endpoints and simple dashboard

### Success metrics

- plate detection confidence and precision within validated threshold
- geolocation confidence on a repeatable test route
- complete end-to-end pipeline from flight log to mapped detections

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
5. georectification engine
6. geofence and pattern-of-life analytics
7. dashboard and API layer
8. open-hardware autonomy integration

## 8. Risk management

- Maintain modular boundaries between telemetry parsing, perception, geospatial logic, and mission control.
- Validate every component with field data and reproducible tests.
- Avoid introducing live autonomy until the offline pipeline is stable.
- Keep system behavior understandable and observable for operators.
