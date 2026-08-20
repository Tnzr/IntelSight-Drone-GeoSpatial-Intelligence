# IntelSight: Drone GeoSpatial Intelligence Platform

## Executive summary

IntelSight is a phased drone intelligence platform that converts aerial footage, telemetry, and RF signals into searchable geospatial intelligence. The near-term objective is to produce a reliable offline pipeline that works with the DJI Mini 4 Pro and other consumer drones; the longer-term objective is to build a live autonomy stack on an open PX4-based platform with companion compute, multi-camera sensing, and fleet coordination.

This project intentionally separates two values:

1. Immediate operational value from geotagged aerial datasets, detection pipelines, and pattern-of-life analytics.
2. Strategic long-term value from live autonomous perception, autonomous missioning, and geospatial decision support.

The system is designed to support:

- vehicle and infrastructure detection
- georeferenced evidence capture
- license plate and parking-lot correlation
- pattern-of-life and anomaly detection
- geofence-based intelligence mapping
- future RF/SIGINT sensing and swarm coordination

## Mission philosophy

The project should be framed as an intelligence platform, not a single algorithm. The product stack combines:

- flight telemetry parsing
- georectification and map alignment
- computer vision and OCR
- geospatial indexing
- contextual analytics
- autonomy and swarm control in later phases

## Sensitive data and GitHub policy

The raw mission footage and flight records under `data/` are not intended for GitHub tracking. This repository keeps only a minimal public documentation footprint and intentionally excludes sensitive video, telemetry, geospatial evidence, or test footage from version control.

Use this pattern for local-only datasets:

```bash
mkdir -p data/flightrecords/flight_mission_drone
# place local footage and mission records here
```

The repository intentionally ignores all `data/**` content except a small README placeholder. This prevents accidental leakage of surveillance footage, customer location data, or operational records.

## Development environment

This project is designed to run in a dedicated Conda/Mamba environment for reproducibility and multi-GPU utilization. The authoritative environment is `intelsight` in the Mamba root at `/home/tnzr/.local/share/mamba/envs/intelsight`.

```bash
mamba run -n intelsight python -m unittest tests.test_license_plate_service -q
mamba run -n intelsight python modules/cv-pipeline/run_cv_pipeline.py \
  --input-dir data/flightrecords/flight_mission_drone/FlagerPublix \
  --output-dir output/cv/FlagerPublix \
  --devices 0 \
  --frame-step 2 \
  --batch-size 16
```

The older repo-local `.venv` is not the authoritative runtime for mission processing and should not be used for validation or final outputs.

## Strategic direction

### Phase I: offline intelligence with consumer drones

Use the DJI Mini 4 Pro as the primary field collection platform for:

- pre-planned waypoint missions
- video and telemetry collection
- extraction of flight metadata and geotagged frames
- detection and OCR of license plates, vehicles, and infrastructure
- database population for geospatial correlation and anomaly analysis

This phase produces the highest immediate value with the lowest technical risk.

### Phase II: live autonomy with open hardware

Transition to a custom PX4 stack with companion compute and multi-camera sensing for:

- real-time perception
- mission adaptation in flight
- object following and area search
- autonomous geospatial event capture
- fleet-level mission orchestration

This phase is the strategic forward path for autonomous search, rescue, and surveillance applications.

## Core principles

- Start with data quality before autonomy.
- Prioritize geospatial grounding over raw detection counts.
- Keep the platform modular and hardware-agnostic.
- Treat compliance and privacy as first-class engineering requirements.
- Use a phased delivery model: offline pipeline first, live autonomy second.

## Repository structure

- `DevDocs/` — original background research notes and concept docs
- `docs/` — engineering, implementation, business, and research documentation
- `src/` — implementation code for future modules
- `tests/` — validation and benchmark harnesses

## Handoff guidance

This repository is intentionally staged as a planning and architecture foundation. The goal is to preserve the strategic decisions and constraints before implementation begins. The coding agent should follow the detailed requirements in the docs and implement the first working pipeline in a disciplined, test-driven order.

## Top-level goals

- Build a working telemetry-to-geospatial pipeline
- Create a reliable geotagged image processing workflow
- Establish a geospatial intelligence database
- Add contextual pattern-of-life analytics
- Prepare for onboard autonomy on an open drone platform

## Mission Explorer

Run the browser-based mission explorer to select trajectory and detection files, then review the mission in 2D and 3D:

```bash
make dashboard
```

The dashboard can load workspace artifacts from `output/` or accept uploaded files for browser-first use.

## Legal and ethics note

This project touches sensitive location, identity, and surveillance data. Any future production use should include clear compliance review, lawful purpose statements, retention policies, and privacy safeguards. The project should avoid facial recognition and overreach into restricted personally identifying data unless properly governed.
