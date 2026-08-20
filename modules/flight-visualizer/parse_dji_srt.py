from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd
from geojson import Feature, FeatureCollection, LineString, Point, dump

FRAME_RE = re.compile(r"FrameCnt:\s*(\d+),\s*DiffTime:\s*(\d+)ms")
TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})")
KV_RE = re.compile(r"\[(\w+):\s*([^\]]+)\]")
REL_ALT_RE = re.compile(r"rel_alt:\s*([\-\d\.]+)")
ABS_ALT_RE = re.compile(r"abs_alt:\s*([\-\d\.]+)")


def parse_srt_file(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]

    rows = []
    for block in blocks:
        frame_m = FRAME_RE.search(block)
        ts_m = TS_RE.search(block)
        kv_pairs = dict(KV_RE.findall(block))

        if not frame_m or not ts_m:
            continue
        if "latitude" not in kv_pairs or "longitude" not in kv_pairs:
            continue

        rel_alt_m = REL_ALT_RE.search(block)
        abs_alt_m = ABS_ALT_RE.search(block)

        row = {
            "frame": int(frame_m.group(1)),
            "diff_ms": int(frame_m.group(2)),
            "timestamp": ts_m.group(1),
            "latitude": float(kv_pairs["latitude"]),
            "longitude": float(kv_pairs["longitude"]),
            "rel_alt": float(rel_alt_m.group(1)) if rel_alt_m else 0.0,
            "abs_alt": float(abs_alt_m.group(1)) if abs_alt_m else 0.0,
            "iso": kv_pairs.get("iso", ""),
            "shutter": kv_pairs.get("shutter", ""),
            "fnum": kv_pairs.get("fnum", ""),
            "ev": kv_pairs.get("ev", ""),
            "focal_len": kv_pairs.get("focal_len", ""),
            "ct": kv_pairs.get("ct", ""),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df


def to_geojson(df: pd.DataFrame, flight_name: str, out_path: Path) -> None:
    coords = [
        [float(lon), float(lat), float(alt)]
        for lon, lat, alt in zip(df["longitude"], df["latitude"], df["rel_alt"])
    ]

    line_feature = Feature(
        geometry=LineString(coords),
        properties={
            "type": "trajectory",
            "flight": flight_name,
            "frame_count": int(len(df)),
            "start_time": str(df["timestamp"].iloc[0]),
            "end_time": str(df["timestamp"].iloc[-1]),
        },
    )

    sample_step = max(len(df) // 80, 1)
    features = [line_feature]
    for idx, row in df.iloc[::sample_step].iterrows():
        features.append(
            Feature(
                geometry=Point((float(row["longitude"]), float(row["latitude"]), float(row["rel_alt"]))),
                properties={
                    "type": "sample",
                    "index": int(idx),
                    "frame": int(row["frame"]),
                    "timestamp": str(row["timestamp"]),
                    "rel_alt": float(row["rel_alt"]),
                    "abs_alt": float(row["abs_alt"]),
                    "shutter": str(row["shutter"]),
                    "iso": str(row["iso"]),
                    "focal_len": str(row["focal_len"]),
                },
            )
        )

    fc = FeatureCollection(features)
    with out_path.open("w", encoding="utf-8") as f:
        dump(fc, f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse DJI SRT telemetry to CSV and GeoJSON")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    for srt_file in sorted(args.input_dir.glob("*.SRT")):
        flight_name = srt_file.stem
        df = parse_srt_file(srt_file)
        if df.empty:
            continue

        csv_out = args.output_dir / f"{flight_name}.srt.csv"
        geojson_out = args.output_dir / f"{flight_name}.srt.geojson"

        df.to_csv(csv_out, index=False)
        to_geojson(df, flight_name, geojson_out)

        summaries.append(
            {
                "flight": flight_name,
                "frames": int(len(df)),
                "start": str(df["timestamp"].iloc[0]),
                "end": str(df["timestamp"].iloc[-1]),
                "csv": str(csv_out),
                "geojson": str(geojson_out),
            }
        )

    summary_path = args.output_dir / "srt-summary.json"
    summary_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(json.dumps({"flights": len(summaries), "summary": str(summary_path)}, indent=2))


if __name__ == "__main__":
    main()
