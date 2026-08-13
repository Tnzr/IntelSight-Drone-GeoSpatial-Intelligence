# Engineering Requirements

## 1. Product definition

IntelSight is a drone intelligence platform for geospatially grounded perception. The immediate product goal is to convert aerial video and telemetry into structured intelligence: detected vehicles, georeferenced evidence, contextual tagging, and pattern-of-life insights. The long-term goal is to move this pipeline to live autonomous flight and multi-drone fleet coordination.

## 2. Scope definition

### In scope

- DJI Mini 4 Pro flight log ingestion
- telemetry extraction from `.txt` and `.SRT` data
- geotagging of extracted frames
- object detection using vision models
- OCR on vehicle license plates
- georectification with IMU + GPS + camera model
- geospatial storage and query interface
- contextual geofence tagging
- anomaly and pattern-of-life analytics
- PX4 and ROS2 architecture for future live autonomy

### Out of scope for the first release

- full live closed-DJI autonomy
- law-enforcement owner lookup services
- facial recognition and other high-risk biometric systems
- full RF/SIGINT as a first milestone

## 3. System architecture

### 3.1 Reference architecture

- Data collection layer: DJI drones, consumer cameras, future PX4 stack
- Telemetry and media layer: logs, SRT files, video, IMU, GPS
- Perception layer: detection, OCR, segmentation, contextual classification
- Geospatial layer: GeoJSON, PostGIS, geofences, reverse geocoding
- Analytics layer: historical pattern-of-life, anomaly detection, association clustering
- Control layer: PX4 / MAVLink / ROS2 for future autonomous operations

### 3.2 Functional modules

#### Telemetry parser

- Parse DJI flight record metadata from `.txt`, `.SRT`, and related encrypted files when accessible
- Extract timestamps, GPS, altitude, heading, speed, and IMU pose estimates
- Emit normalized telemetry objects for downstream processing

#### Frame geotagging

- Synchronize frame timestamps with the nearest telemetry record
- Attach GPS, altitude, and pose metadata to each frame
- Export geotagged imagery to a structured dataset

#### Detection pipeline

- Detect vehicles, infrastructure, and plates
- Use regulated object classes and confidence thresholds
- Normalize detections to geospatial coordinates on the map

#### Georectification engine

- Estimate camera ray from pixel coordinates
- Rotate from camera frame to world frame using IMU pose
- Translate with GPS and altitude data
- Apply terrain correction using DEM or local plane approximation
- Store estimated ground point and confidence level

#### Geospatial database

- Store detections, mission metadata, geofences, and historical observations
- Support spatial queries by latitude/longitude, geofence, time, and object type
- Support event association analysis and historical lookups

#### Analytics engine

- Link detections to parking-lot, neighborhood, or facility geofences
- Build plate-to-location history
- Detect recurrent vehicles and unusual patterns
- Rank likely relevance based on contextual location and timing

## 4. Non-functional requirements

### Reliability

- Data provenance must be retained at the frame and detection level
- Every detection should store timestamp, sensor context, and confidence
- Failure states and skipped detections must be visible to operators

### Performance

- Offline pipeline must handle a typical flight dataset without blocking
- Real-time prototype should target sub-second latency for event signaling
- Long-running analytics must support large geospatial datasets

### Security and privacy

- Use data retention policies and access controls
- Minimize collection to the necessary scope
- Avoid unrestricted identity resolution without legal basis
- Prevent exposure of raw sensitive data outside approved systems

## 5. Data model requirements

Each detection should include:

- detection_id
- mission_id
- drone_id
- timestamp_utc
- latitude
- longitude
- altitude_m
- heading_deg
- plate_text
- plate_confidence
- source_image_uri
- geofence_id
- object_class
- confidence_score
- metadata_json

A geofence should include:

- geofence_id
- name
- type
- polygon or point geometry
- owner or mission context

## 6. Hardware and software constraints

### Phase I assumptions

- Primary platform: DJI Mini 4 Pro
- Use ground-station processing and optional post-flight geotagging
- Target flexible, open-source toolchain in Python and Rust

### Phase II assumptions

- Flight controller: PX4-compatible autopilot
- Companion computer: Jetson or equivalent
- Multi-camera payload: forward + downward + side views
- Communication: MAVLink, ROS2, and optional HaLow for range extension

## 7. Acceptance criteria

### Phase I acceptance

- The system can ingest DJI telemetry and extract georeferenced frame metadata
- It can detect license plates from field imagery with validated confidence thresholds
- It can geolocate detections and map them to geofences
- It stores this data in a queryable geospatial database
- It produces repeatable outputs for test flights

### Phase II acceptance

- The system can run a real-time perception loop on onboard compute
- A drone can react to geofenced events and mission conditions in flight
- A centralized or semi-centralized controller can coordinate a fleet with roving search and observation tasks

## 8. Risk register

- sensor noise and drift in GPS/IMU
- poor geolocation under oblique camera angles
- unstable license plate recognition under low-light or occlusion
- legal risk around identity and location data
- hardware limitations of consumer drone ecosystems

## 9. Design decisions

- consumer drone first, open hardware second
- geospatial grounding before autonomous behavior
- modular architecture with explicit sensor interfaces
- anti-identity by default; only lawful operational use cases permitted
