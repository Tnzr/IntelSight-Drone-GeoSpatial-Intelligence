# Sprint Backlog

## Product direction

This backlog is designed around a disciplined progression from offline intelligence to autonomous operations, while preserving the future expansion into agriculture, forestry, environmental inspection, and infrastructure monitoring.

The program follows this order:

1. DJI Mini 4 Pro validation pipeline
2. geospatial intelligence and analytics engine
3. enterprise upgrade to Mavic 3M for field scale and multispectral workflows
4. PX4 autonomous perception platform
5. SIGINT payload and telecom data products
6. wider vertical expansion into agriculture, forestry, and public service missions

---

## Sprint 0 — project setup and environment foundation

### Objective

Establish the technical baseline and reproducible development environment.

### Tasks

- [ ] create Python environment and dependency lock file
- [ ] create Rust toolchain and verification setup
- [ ] initialize project folders and module boundaries
- [ ] define data conventions for flight logs, telemetry, video, and detections
- [ ] register current `data/flightpath` DJI TXT logs as seed parsing fixtures
- [ ] create sample dataset directory with test log fixtures and synchronized-video placeholders
- [ ] define the initial schema for missions, detections, geofence records, and observations
- [ ] create baseline CI workflow and test harness

### Definition of done

- project can run in a clean environment
- sample data can be loaded and parsed
- repo has clear module boundaries
- CI checks exist for basic validation

### Dependencies

- repo structure complete
- sample DJI logs available

---

## Sprint 1 — DJI telemetry parsing

### Objective

Build a reliable parser that converts raw DJI flight records into normalized telemetry data.

### Tasks

- [ ] validate DJI TXT and SRT log formats for DJI Mini 4 Pro
- [ ] parse the two current `data/flightpath` TXT records and document field availability gaps before synchronized video arrives
- [ ] implement parser for metadata extraction: GPS, altitude, timestamp, heading, speed
- [ ] normalize telemetry records into a shared schema
- [ ] create parser tests using sample flight logs
- [ ] export telemetry to CSV and GeoJSON for review
- [ ] verify timestamp synchronization with video frames
- [ ] create a failure and missing-data reporting layer

### Definition of done

- telemetry can be parsed consistently from sample records
- output is stable and queryable
- parser handles missing or partial records without crashing

### Dependencies

- sample DJI flight logs
- environment setup complete

---

## Sprint 2 — geotagged frame extraction and dataset preparation

### Objective

Create a robust geotagging pipeline for raw footage and mission data.

### Tasks

- [ ] extract frames from DJI footage at fixed intervals
- [ ] attach nearest telemetry to each frame
- [ ] generate frame metadata with GPS, timestamp, heading, and altitude
- [ ] export geotagged image set for analysis
- [ ] validate mapping between video time and flight telemetry
- [ ] build dataset labeling structure for detections and OCR samples
- [ ] create basic local dashboard for frame review

### Definition of done

- every extracted frame has geospatial metadata
- detections can be tied back to an exact frame and mission
- dataset is ready for model training and validation

### Dependencies

- Sprint 1 complete

---

## Sprint 3 — license plate detection and OCR pipeline

### Objective

Detect plates and extract normalized plate text from geotagged frames.

### Tasks

- [ ] evaluate YOLO model candidates for plate detection on drone footage
- [ ] evaluate vehicle make/model/color extraction strategy for crowded-scene association
- [ ] create data labeling workflow for plate crops and negative samples
- [ ] build detection inference pipeline
- [ ] crop detected plate regions and normalize orientation
- [ ] run OCR pipeline and text normalization
- [ ] score accuracy on validation set
- [ ] build confidence thresholding and false-positive handling
- [ ] store detection event records with confidence and source frame

### Definition of done

- plate detections are generated in a repeatable workflow
- OCR is normalized and stored as a clean plate value
- confidence thresholds are documented and tested

### Dependencies

- Sprint 2 complete

---

## Sprint 4 — georectification and spatial grounding

### Objective

Turn detected objects into geospatially grounded observations.

### Tasks

- [ ] implement camera projection model for object-to-ground mapping
- [ ] fuse IMU, GPS, heading, and altitude into pose estimates
- [ ] estimate ground-plane or terrain-corrected point for each detection
- [ ] calculate positional uncertainty and confidence values
- [ ] validate geolocation on known landmarks and surveyed test points
- [ ] store spatial event records in a machine-readable format
- [ ] produce a basic map overlay for detections

### Definition of done

- each detection includes a geospatial point and confidence estimate
- position error is measured against test references
- map output displays detections in correct spatial context

### Dependencies

- Sprint 3 complete

---

## Sprint 5 — PostGIS and geospatial API layer

### Objective

Create the first production data layer for storing event history and enabling spatial queries.

### Tasks

- [ ] configure PostGIS and a local database environment
- [ ] design core tables for missions, detections, geofences, and evidence
- [ ] create ingestion API for detection records
- [ ] implement geofence definitions for parking lots, neighborhoods, hotels, casinos, dealerships, infrastructure sites, agricultural fields, forestry zones, and waste-reporting zones
- [ ] build queries for time, location, plate history, and geofence association
- [ ] build aggregate venue-category queries for vehicle, site, and land-use analytics
- [ ] expose GeoJSON endpoints for map and dashboard integration
- [ ] add API auth and validation patterns for operational use

### Definition of done

- events are stored in a queryable geospatial database
- geofences can be used to tag detections by location context
- API endpoints support map and event queries

### Dependencies

- Sprint 4 complete

---

## Sprint 6 — pattern-of-life and anomaly analytics

### Objective

Turn detections into meaningful temporal and contextual intelligence.

### Tasks

- [ ] implement repeated plate and vehicle association analysis
- [ ] create geofence-based contextual tagging
- [ ] build anomaly detection for unusual routes and repeated patterns
- [ ] create location history timeline for a plate, vehicle, or site
- [ ] integrate make/model/color attributes into association scoring for dense parking and crowd scenes
- [ ] prototype route clustering and recurring event detection
- [ ] develop a ranking model for location relevance and event importance
- [ ] build a basic dashboard for pattern review
- [ ] constrain sensitive-location analytics to aggregate and policy-approved outputs

### Definition of done

- repeated detections are clustered and explained
- unusual or high-risk patterns are identified by heuristic scoring
- dashboard can present event history by geofence and time window

### Dependencies

- Sprint 5 complete

---

## Sprint 7 — enterprise upgrade path: Mavic 3M and multi-sensor field platform

### Objective

Prepare the product for enterprise demand and broader inspection use by upgrading from the Mini 4 Pro to a more capable enterprise platform.

### Tasks

- [ ] evaluate Mavic 3M for mapping, inspection, and enterprise missions
- [ ] compare Mini 4 Pro vs Mavic 3M for mission quality and scale
- [ ] define upgrade path for agricultural and forestry inspection
- [ ] assess multispectral and RGB payload value for vegetation, land health, and inspection workflows
- [ ] define hybrid fleet approach: Mini 4 Pro for validation, Mavic 3M for broader enterprise operations
- [ ] document enterprise integration requirements for clients and field teams
- [ ] create a pilot plan for infrastructure and agriculture use cases

### Definition of done

- upgrade path is documented and justified by business case
- Mavic 3M mission use cases are validated for enterprise applications
- agricultural and forestry use-case expansion is mapped to technical requirements

### Dependencies

- Sprint 6 complete
- business case and partner interest validated

---

## Sprint 8 — PX4 autonomous prototype

### Objective

Build the first autonomous perception platform using a custom PX4 stack.

### Tasks

- [ ] select frame, motors, ESCs, and payload architecture
- [ ] configure PX4 flight controller and flight tuning baseline
- [ ] integrate Jetson companion compute
- [ ] mount and calibrate a 4-camera lateral configuration
- [ ] implement ROS2 nodes for sensor ingest and mission state
- [ ] test autonomous waypoint operation and route following
- [ ] integrate live detection triggers and geofence-based response logic
- [ ] validate flight stability under payload and camera load

### Definition of done

- PX4 drone performs stable mission flight with onboard compute
- multi-camera payload is synchronized and working in field conditions
- autonomous flight logic responds to mission triggers

### Dependencies

- core offline stack ready
- validation flights complete on DJI

---

## Sprint 9 — SIGINT payload and telecom data product

### Objective

Add RF, Wi-Fi, and Bluetooth sensing to create higher-value data products for telecom and network quality use cases.

### Tasks

- [ ] select SIGINT payload modules for Wi-Fi, Bluetooth, and RF scanning
- [ ] design geotagged signal schema and data ingestion pipeline
- [ ] implement discovery and logging for SSID, BSSID, Bluetooth signatures, and signal strength
- [ ] create coverage-quality and interference mapping workflows
- [ ] validate fox-hunting and geolocation workflow for signal sources
- [ ] define partner-facing telecom product offers and service bundles
- [ ] document legal retention and customer data boundary policies

### Definition of done

- SIGINT data is captured and geotagged in a structured format
- RF heatmaps and coverage reports can be generated
- telecom partner offering is defined and validated

### Dependencies

- Sprint 8 complete or in advanced stage

---

## Sprint 10 — agriculture, forestry, and public service expansion

### Objective

Scale the platform into adjacent sectors with strong operational value.

### Tasks

- [ ] define agricultural inspection use cases: crop health, field boundaries, irrigation, drainage
- [ ] define forestry inspection use cases: canopy health, tree density, access paths, fire edge monitoring
- [ ] define environmental cleanup use cases: recyclable accumulation, illegal dumping, trash hotspot scoring, and waterway-adjacent waste reporting
- [ ] map required sensors and mission patterns for each vertical
- [ ] create domain-specific geo-analytics models for vegetation, land condition, waste density, and agro-engineering anomaly detection
- [ ] assess rates, budgets, and service offerings for each vertical
- [ ] create pilot programs with agricultural and forestry partners
- [ ] create pilot programs with environmental services, municipalities, or conservation groups
- [ ] document cross-domain platform reuse from core geospatial stack

### Definition of done

- agricultural and forestry use cases are validated as extension opportunities
- mission templates exist for each vertical
- platform adaptation strategy is documented for broader operations

### Dependencies

- Sprint 7 and Sprint 9 complete enough to support expansion

---

## Cross-cutting workstreams

### Data and platform quality

- [ ] dataset hygiene and annotation review
- [ ] model versioning and experiment tracking
- [ ] sensor calibration and field validation
- [ ] incident and failure logging

### Product and legal governance

- [ ] retention policies
- [ ] lawful-use review for sensitive data
- [ ] customer contract and service-level definitions
- [ ] approval process for data-sharing and telecom partnerships

### Mission marketplace foundation

- [ ] operator onboarding and role management
- [ ] mission request workflow
- [ ] pricing and payout model
- [ ] mission review and reputation layer

---

## Prioritized implementation order

1. Sprint 0 — setup and environment baseline
2. Sprint 1 — telemetry parsing
3. Sprint 2 — geotagging and dataset prep
4. Sprint 3 — detection and OCR
5. Sprint 4 — georectification and spatial grounding
6. Sprint 5 — PostGIS and API
7. Sprint 6 — pattern-of-life and anomaly engine
8. Sprint 7 — Mavic 3M enterprise upgrade evaluation
9. Sprint 8 — PX4 autonomous prototype
10. Sprint 9 — SIGINT and telecom data products
11. Sprint 10 — agriculture and forestry expansion

---

## Recommended milestone checkpoints

### Milestone A — core offline intelligence prototype

Target outcome: a working DJI-based geospatial intelligence pipeline that can process mission data end-to-end.

### Milestone B — enterprise validation and multi-sensor upgrade

Target outcome: Mavic 3M and enterprise workflow pilot showing expanded value and operational scale.

### Milestone C — autonomous perception prototype

Target outcome: custom PX4 platform with live perception and mission adaptation.

### Milestone D — dual-use intelligence platform

Target outcome: integrated SIGINT + geospatial intelligence product ready for telecom and infrastructure partnerships.

### Milestone E — sector expansion

Target outcome: vertical adoption in agriculture, forestry, and infrastructure across multiple deployment models.

---

## Notes for future expansion

The long-term platform should remain modular so new sensing and mission types can be added without rewriting the core stack. The same geospatial intelligence engine can support:

- public safety monitoring
- infrastructure inspection
- agriculture and forestry health mapping
- telecom and RF signal validation
- mission marketplace operations for local operators and field contractors

This ensures the core architecture remains strategic while the product expands into adjacent high-value domains.
