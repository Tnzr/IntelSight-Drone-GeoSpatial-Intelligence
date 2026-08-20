# Output Artifacts

Generated artifacts from parsing and visualization pipelines are saved under this directory.

Current expected location for flight-record processing:

- `output/flightpath/`

Per flight record, the pipeline emits:

- `*.frames.csv` (sensor and trajectory frame data)
- `*.trajectory.geojson` (trajectory and sampled sensor point features)
- `*.metrics.json` (parser performance timings)
- `*.map.html` (interactive trajectory map)
- `*.viz.metrics.json` (visualization timing metrics)
