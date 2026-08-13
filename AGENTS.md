# AGENTS.md

## Project intent

IntelSight is a phased drone intelligence platform for geospatial evidence collection, perception, and analytics. The repository is intentionally organized to support a disciplined engineering progression:

1. Build an offline drone telemetry and geospatial intelligence pipeline.
2. Validate georeferencing, OCR, and contextual mapping.
3. Expand to live autonomy on a PX4-based open platform.
4. Extend with fleet coordination and SIGINT later.

## Operating rules

- Do not start broad implementation before reading the planning docs.
- Follow the phased roadmap in order.
- Prefer reproducible, testable modules over one-off scripts.
- Keep geospatial and telemetry data pipelines deterministic.
- Treat precise geolocation and data provenance as core requirements.
- Respect privacy, lawful use, and data minimization principles.

## Priority order

1. telemetry parsing and ingestion
2. geotagging and georectification
3. detection and OCR
4. geospatial database and APIs
5. pattern-of-life analytics
6. open-drone autonomy
7. fleet coordination and RF sensing

## Do not do

- Do not implement facial recognition.
- Do not add owner lookup logic without legal review.
- Do not rely on opaque, non-reproducible data processing.
- Do not attempt to harden a closed DJI live-control path before the offline stack is proven.

## Suggested first implementation target

Build the first working end-to-end offline pipeline using DJI Mini 4 Pro logs and imagery, including:

- parser for DJI SRT/flight logs
- geotagged frame extraction
- YOLO-based plate detection
- OCR normalization
- GeoJSON export and PostGIS-ready record schema

## Documentation hierarchy

- `README.md` — summary and product direction
- `docs/engineering-requirements.md` — technical system requirements
- `docs/implementation-plan.md` — execution roadmap
- `docs/business-economic-plan.md` — market, business, and economic reasoning
- `docs/whitepaper.md` — technical narrative and strategic framing

## Final instruction

The coding agent must produce implementation artifacts that are modular, verifiable, and ready for real-world field test collection with a clear path to live autonomy on a PX4 platform.
