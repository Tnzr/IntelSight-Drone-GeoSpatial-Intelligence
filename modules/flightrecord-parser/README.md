# FlightRecord Parser Module

Rust parser module for DJI flight records using `dji-log-parser`.

## Purpose

- parse DJI TXT flight records
- export normalized sensor frames to CSV
- export trajectory and sampled sensor points to GeoJSON
- record parsing bottleneck metrics (timings and throughput)

## Run

```bash
conda run -n intelsight cargo run --release --manifest-path modules/flightrecord-parser/Cargo.toml -- \
  --input "data/flightpath/DJIFlightRecord_2024-05-23_[20-16-18] (1).txt" \
  --out-dir output/flightpath
```

## Outputs per input file

- `*.frames.csv`
- `*.trajectory.geojson`
- `*.metrics.json`

## Notes

- For encrypted log versions (13+), pass `--api-key`.
- For older logs (such as your current dataset), no API key is required.
