# IntelSight Mission Explorer

This module provides a browser-based, cross-platform dashboard for selecting telemetry and detection files, reviewing mission data in 2D and 3D, and persisting the selected mission into a local SQLite digest for fast re-use.

## Features

- file selection from the workspace or browser uploads
- 2D map of trajectory and detected objects
- 3D plot of trajectory and detections with selectable coordinate space:
	- local ENU meters (East, North, Up) for field review
	- geodetic coordinates (longitude, latitude, altitude)
- filters for confidence, vehicle type, and review status
- linked object focus across map, table, and video context
- overlay-first video preview with source mode (`overlay_preferred`, `overlay_only`, `raw_only`)
- optional downscaled playback proxies (`1080p`, `720p`) generated on demand for smoother review
- SQLite mission digest that stores the selected telemetry and detection rows locally
- cached mission mode to reopen prior digest sessions without reloading raw sources
- geolocation diagnostics in Objects tab (`geolocation_mode`, `geo_spread_m`, `proxy_ground_offset_m`)
- table export for filtered detections

## Supported inputs

- trajectory GeoJSON from `output/flightrecords/**/*.trajectory.geojson`
- SRT CSV telemetry from `output/flightrecords/**/*.srt.csv`
- detection GeoJSON from `output/cv/**/lp_vehicle_report.geojson`
- fused detection CSV from `output/cv/**/*.fused.csv`
- summary JSON from `output/cv/**/lp_vehicle_report.summary.json`
- mission videos from `data/flightrecords/**/*.MP4`

The dashboard writes a local cache database to `output/web-dashboard/mission_digest.sqlite3`.
Downscaled video proxies are cached at `output/web-dashboard/video-previews/`.

## Run

Install the dependencies:

```bash
mamba run -n intelsight pip install -r modules/web-dashboard/requirements.txt
```

Start the dashboard:

```bash
make dashboard
```

The app opens in the browser and can also accept uploaded files for online use.

Choose a video in the sidebar only if you want to preview the clip. Overlay video is preferred when available, and the maps/database digest work without loading video.

Feature implementation and validation log: ../docs/web-dashboard-feature-addition-log.md

Feature and debugging checklist: ../docs/feature-debug-checklist.md