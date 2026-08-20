# Flight Trajectory Visualizer

Python visualization module for map rendering from parser CSV output.

## Purpose

- render trajectory polyline
- render sampled sensor markers (speed, altitude, yaw/pitch/roll, gps quality)
- emit rendering bottleneck timings

## Run

```bash
conda run -n intelsight python modules/flight-visualizer/render_map.py \
  --csv output/flightpath/<name>.frames.csv \
  --html output/flightpath/<name>.map.html \
  --metrics output/flightpath/<name>.viz.metrics.json
```

## SRT Trajectory Dashboard

For mission videos with DJI `.SRT` telemetry, parse all flights and build a multi-flight lightweight dashboard:

```bash
conda run -n intelsight python modules/flight-visualizer/parse_dji_srt.py \
  --input-dir data/flightrecords/flight_mission_drone \
  --output-dir output/flightrecords/flight_mission_drone

conda run -n intelsight python modules/flight-visualizer/build_trajectory_dashboard.py \
  --input-dir output/flightrecords/flight_mission_drone \
  --output output/flightrecords/flight_mission_drone/trajectory-dashboard.html
```

This outputs per-flight CSV/GeoJSON plus a single interactive map with layer toggles and summary stats.
