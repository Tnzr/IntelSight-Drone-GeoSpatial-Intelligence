from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import folium
import pandas as pd


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def build_map(csv_path: Path, output_html: Path, title: str) -> dict:
    t0 = time.perf_counter()
    df = pd.read_csv(csv_path)
    t_read = time.perf_counter()

    required = {"latitude", "longitude"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    df = df.dropna(subset=["latitude", "longitude"])
    if df.empty:
        raise ValueError("No valid latitude/longitude rows found")

    lat0 = _safe_float(df.iloc[0]["latitude"])
    lon0 = _safe_float(df.iloc[0]["longitude"])
    m = folium.Map(location=[lat0, lon0], zoom_start=16, tiles="CartoDB positron")

    coords = [
        [_safe_float(r.latitude), _safe_float(r.longitude)]
        for r in df.itertuples(index=False)
    ]
    t_coords = time.perf_counter()

    folium.PolyLine(coords, color="#1273de", weight=4, opacity=0.85).add_to(m)

    step = max(len(coords) // 60, 1)
    for idx, row in enumerate(df.itertuples(index=False)):
        if idx % step != 0:
            continue

        popup_html = (
            f"<b>Frame</b>: {idx}<br>"
            f"<b>Time</b>: {getattr(row, 'customDateTime', '')}<br>"
            f"<b>Fly Time</b>: {getattr(row, 'flyTime', '')}<br>"
            f"<b>Alt</b>: {getattr(row, 'altitude', '')}<br>"
            f"<b>Height</b>: {getattr(row, 'height', '')}<br>"
            f"<b>Speed XYZ</b>: {getattr(row, 'xSpeed', '')}, {getattr(row, 'ySpeed', '')}, {getattr(row, 'zSpeed', '')}<br>"
            f"<b>Attitude PRY</b>: {getattr(row, 'pitch', '')}, {getattr(row, 'roll', '')}, {getattr(row, 'yaw', '')}<br>"
            f"<b>GPS</b>: sats={getattr(row, 'gpsNum', '')}, level={getattr(row, 'gpsLevel', '')}, used={getattr(row, 'isGPSUsed', '')}"
        )
        folium.CircleMarker(
            location=[_safe_float(row.latitude), _safe_float(row.longitude)],
            radius=3,
            color="#f39c12",
            fill=True,
            fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=420),
        ).add_to(m)

    folium.Marker(coords[0], tooltip="Start", icon=folium.Icon(color="green")).add_to(m)
    folium.Marker(coords[-1], tooltip="End", icon=folium.Icon(color="red")).add_to(m)

    m.get_root().html.add_child(folium.Element(f"<h3 style='margin:10px'>{title}</h3>"))
    m.save(str(output_html))
    t_end = time.perf_counter()

    metrics = {
        "csv": str(csv_path),
        "output_html": str(output_html),
        "rows": int(len(df)),
        "read_ms": round((t_read - t0) * 1000, 2),
        "coords_ms": round((t_coords - t_read) * 1000, 2),
        "render_ms": round((t_end - t_coords) * 1000, 2),
        "total_ms": round((t_end - t0) * 1000, 2),
    }
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a flight trajectory and sensor map")
    parser.add_argument("--csv", required=True, type=Path, help="CSV exported by Rust parser")
    parser.add_argument("--html", required=True, type=Path, help="Output HTML map path")
    parser.add_argument(
        "--metrics",
        type=Path,
        default=None,
        help="Optional JSON file for visualization timing metrics",
    )
    parser.add_argument("--title", type=str, default="IntelSight Flight Trajectory")
    args = parser.parse_args()

    args.html.parent.mkdir(parents=True, exist_ok=True)
    metrics = build_map(args.csv, args.html, args.title)

    if args.metrics is not None:
        args.metrics.parent.mkdir(parents=True, exist_ok=True)
        args.metrics.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
