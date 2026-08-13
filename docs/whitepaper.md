# IntelSight White Paper

## 1. Abstract

IntelSight proposes a phased architecture for drone intelligence that begins with offline geospatial perception on consumer drones and extends toward live autonomous flight on open hardware. The platform is designed to transform aerial video, flight telemetry, and contextual geospatial observations into actionable intelligence for monitoring, correlation, and anomaly detection.

The central idea is not simply to detect objects in an image, but to ground those detections in space, time, and place. Geospatially anchored detections become a history of movement, behavior, and activity patterns. That ability creates economic and operational value far beyond raw plate recognition.

## 2. Problem statement

Existing drone use cases often end at collection or simple fleet coverage. They rarely convert video into a repeatable intelligence layer. The challenge is to tie perception outputs to position, context, and historical behavior. Without this grounding, a vehicle detection is just an isolated image event; with it, the system becomes a moving intelligence engine.

The system must solve several technical problems:

- noisy or partial telemetry from consumer drones
- geospatial alignment of video frames to real-world coordinates
- low-light, angle, and occlusion issues in detection
- time-series pattern analysis across many missions
- legal and privacy concerns around identity-linked data

## 3. System concept

IntelSight follows a layered model:

1. Collect telemetry and aerial footage.
2. Geo-reference frames and detections.
3. Use detectors and OCR to identify vehicles, infrastructure, and plates.
4. Map detections into geofences and historical event graphs.
5. Infer patterns, anomalies, and routes.
6. Later, transition to real-time autonomous behavior on PX4 flight stacks.

## 4. Why a phased strategy is necessary

The closed ecosystem of DJI consumer drones makes live on-board autonomy difficult. Their telemetry and video are accessible through logs or SDK pathways, but full autonomous control is not the same as an open-source flight stack. For this reason, the program should begin with the DJI Mini 4 Pro as a reliable field collection and validation platform, then migrate the same perception logic to a PX4-based platform.

This allows a de-risked route to product value while building the core intelligence engine.

## 5. Key technical architecture

### Data ingestion

The platform ingests:

- video clips
- flight logs and telemetry
- geofence definitions
- map or terrain context

### Telemetry normalization

Telemetry records are transformed into a canonical event model that includes:

- timestamp
- GPS position
- altitude
- heading
- IMU pose
- speed
- mission metadata

### Geotagging and georectification

GPS and IMU data are fused with the camera geometry to project image-plane points into world coordinates. Where necessary, the system uses terrain correction and local plane estimation to improve accuracy for oblique views.

### Perception

The perception layer uses object detection and OCR tuned for drone imagery. This generates plate text, vehicle type, and contextual object metadata. The system intentionally avoids unrestricted identity resolution and focuses on lawful operational evidence workflows.

### Geospatial analytics

Each detection is tied to a location and time. Over repeated missions, the platform builds a history of vehicle presence, parking-lot patterns, route recurrence, and geofenced behavior. This evolves from simple detection into association analysis and situational intelligence.

## 6. Business and operational value

The product value comes from converting raw footage into decision support. Some examples include:

- recurring vehicle-to-location history
- geofence-based relevance scoring for commercial or residential areas
- anomaly detection for repeated or unusual movement patterns
- cross-domain association between place and observed vehicle behavior

This intelligence can be useful in public safety, business intelligence, incident investigation, infrastructure monitoring, and environmental or operational analysis.

## 7. Regulatory and ethical framework

The platform should be designed with legal and ethical boundaries from the start:

- no facial recognition unless explicitly authorized by lawful governance
- clear retention and access controls
- minimization of data collection to mission scope
- audit trails for evidence and operational use
- compliance review before any identity-linked enrichment work

## 8. Long-term strategic arc

The long-term strategic objective is not just a better drone camera. It is a geospatial intelligence platform that can autonomously collect, reason, and act on live observations. This extends to future fleet coordination, autonomous search workflows, and context-aware mission planning.

## 9. Conclusion

IntelSight begins with a practical and valuable near-term problem: convert drone-collected data into usable geospatial intelligence. The project grows into a full intelligence platform by combining telemetry parsing, perception, geospatial context, and analytics. The phased model reduces risk while keeping a clear path to live autonomy and future multi-drone coordination.
