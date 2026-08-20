from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import folium
import pandas as pd
from pandas.errors import EmptyDataError
from folium.plugins import MarkerCluster


REQUIRED_COLUMNS: dict[str, Any] = {
    "video": "",
    "timestamp": "",
    "plate_text": "",
    "fused_confidence": 0.0,
    "vehicle_type": "unknown",
    "vehicle_color": "unknown",
    "vehicle_make_model": "unknown",
    "support_frames": 0,
    "latitude": 0.0,
    "longitude": 0.0,
    "rel_alt": 0.0,
    "vehicle_type_conf": 0.0,
    "plate_sharpness_avg": 0.0,
    "geo_spread_m": 0.0,
    "object_scale_ratio": 0.0,
    "track_span_frames": 0,
    "track_span_seconds": 0.0,
    "geolocation_mode": "unknown",
    "plate_resolved": False,
    "vehicle_bbox_area_avg": 0.0,
    "plate_bbox_area_avg": 0.0,
}


def load_fused_observations(input_dir: Path) -> pd.DataFrame:
    files = sorted(input_dir.glob("*.fused.csv"))
    frames = []
    for csv_file in files:
        try:
            df = pd.read_csv(csv_file)
        except EmptyDataError:
            continue
        if not df.empty:
            df["source_file"] = csv_file.name
            frames.append(df)

    if not frames:
        raise RuntimeError("No fused detection csv files found")

    all_df = pd.concat(frames, ignore_index=True)
    for column, default_value in REQUIRED_COLUMNS.items():
        if column not in all_df.columns:
            all_df[column] = default_value

    all_df = all_df.fillna(
        {
            "plate_text": "",
            "vehicle_type": "unknown",
            "vehicle_color": "unknown",
            "vehicle_make_model": "unknown",
            "video": "",
            "timestamp": "",
        }
    )
    return all_df


def review_status(row: pd.Series) -> str:
    confidence = float(row.get("fused_confidence", 0.0))
    sharpness = float(row.get("plate_sharpness_avg", 0.0))
    support_frames = int(row.get("support_frames", 0))
    geo_spread_m = float(row.get("geo_spread_m", 0.0))

    if confidence < 0.65 or sharpness < 80 or geo_spread_m > 30.0:
        return "needs_review"
    if support_frames >= 3 and confidence >= 0.8:
        return "stable"
    return "usable"


def summary_payload(all_df: pd.DataFrame) -> dict[str, Any]:
    annotated = all_df.copy()
    annotated["review_status"] = annotated.apply(review_status, axis=1)

    top_plates = (
        annotated.sort_values(["fused_confidence", "support_frames"], ascending=[False, False])
        .head(10)[
            [
                "plate_text",
                "fused_confidence",
                "support_frames",
                "vehicle_type",
                "vehicle_color",
                "vehicle_make_model",
                "latitude",
                "longitude",
                "timestamp",
                "video",
                "review_status",
                "geo_spread_m",
                "geolocation_mode",
            ]
        ]
        .to_dict(orient="records")
    )

    return {
        "total_observations": int(len(annotated)),
        "unique_plates": int(annotated["plate_text"].replace("", pd.NA).dropna().nunique()),
        "unique_videos": int(annotated["video"].replace("", pd.NA).dropna().nunique()),
        "avg_fused_confidence": round(float(annotated["fused_confidence"].astype(float).mean()), 4),
        "high_confidence_observations": int((annotated["fused_confidence"].astype(float) >= 0.8).sum()),
        "needs_review": int((annotated["review_status"] == "needs_review").sum()),
        "multi_frame_geolocations": int(annotated["geolocation_mode"].astype(str).str.startswith("multi_frame").sum()),
        "top_vehicle_types": annotated["vehicle_type"].value_counts().head(5).to_dict(),
        "top_vehicle_colors": annotated["vehicle_color"].value_counts().head(5).to_dict(),
        "top_plate_observations": top_plates,
    }


def write_geojson(all_df: pd.DataFrame, output_path: Path) -> None:
    features = []
    for _, row in all_df.iterrows():
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row["longitude"]), float(row["latitude"])],
                },
                "properties": {
                    "video": row.get("video", ""),
                    "timestamp": row.get("timestamp", ""),
                    "plate_text": row.get("plate_text", ""),
                    "fused_confidence": round(float(row.get("fused_confidence", 0.0)), 4),
                    "vehicle_type": row.get("vehicle_type", "unknown"),
                    "vehicle_color": row.get("vehicle_color", "unknown"),
                    "vehicle_make_model": row.get("vehicle_make_model", "unknown"),
                    "support_frames": int(row.get("support_frames", 0)),
                    "rel_alt": round(float(row.get("rel_alt", 0.0)), 3),
                    "vehicle_type_conf": round(float(row.get("vehicle_type_conf", 0.0)), 4),
                    "plate_sharpness_avg": round(float(row.get("plate_sharpness_avg", 0.0)), 3),
                    "geo_spread_m": round(float(row.get("geo_spread_m", 0.0)), 2),
                    "object_scale_ratio": round(float(row.get("object_scale_ratio", 0.0)), 4),
                    "track_span_frames": int(row.get("track_span_frames", 0)),
                    "track_span_seconds": round(float(row.get("track_span_seconds", 0.0)), 3),
                    "geolocation_mode": row.get("geolocation_mode", "unknown"),
                    "plate_resolved": bool(row.get("plate_resolved", False)),
                    "vehicle_bbox_area_avg": round(float(row.get("vehicle_bbox_area_avg", 0.0)), 2),
                    "plate_bbox_area_avg": round(float(row.get("plate_bbox_area_avg", 0.0)), 2),
                    "review_status": review_status(row),
                },
            }
        )

    payload = {"type": "FeatureCollection", "features": features}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_report(
    input_dir: Path,
    output_html: Path,
    summary_output: Path | None = None,
    geojson_output: Path | None = None,
) -> None:
    all_df = load_fused_observations(input_dir)
    all_df["review_status"] = all_df.apply(review_status, axis=1)
    center = [float(all_df.iloc[0]["latitude"]), float(all_df.iloc[0]["longitude"])]

    m = folium.Map(location=center, zoom_start=15, tiles="CartoDB positron")
    cluster = MarkerCluster(name="Plate observations").add_to(m)

    for _, row in all_df.iterrows():
        popup = (
            f"<b>Plate</b>: {row.get('plate_text', '')}<br>"
            f"<b>Plate Confidence</b>: {row.get('fused_confidence', 0):.3f}<br>"
            f"<b>Vehicle Type</b>: {row.get('vehicle_type', 'unknown')}<br>"
            f"<b>Vehicle Type Confidence</b>: {row.get('vehicle_type_conf', 0):.3f}<br>"
            f"<b>Vehicle Color</b>: {row.get('vehicle_color', 'unknown')}<br>"
            f"<b>Make/Model</b>: {row.get('vehicle_make_model', 'unknown')}<br>"
            f"<b>Support Frames</b>: {row.get('support_frames', 0)}<br>"
            f"<b>Geo Mode</b>: {row.get('geolocation_mode', 'unknown')}<br>"
            f"<b>Geo Spread</b>: {row.get('geo_spread_m', 0):.2f} m<br>"
            f"<b>Plate Sharpness Avg</b>: {row.get('plate_sharpness_avg', 0):.1f}<br>"
            f"<b>Review Status</b>: {row.get('review_status', 'usable')}<br>"
            f"<b>Timestamp</b>: {row.get('timestamp', '')}<br>"
            f"<b>Video</b>: {row.get('video', '')}<br>"
            f"<b>Location</b>: {float(row['latitude']):.6f}, {float(row['longitude']):.6f}"
        )

        status = row.get("review_status", "usable")
        color = {"stable": "green", "usable": "orange", "needs_review": "red"}.get(status, "blue")
        folium.CircleMarker(
            location=[float(row["latitude"]), float(row["longitude"])],
            radius=5,
            color=color,
            fill=True,
            fill_opacity=0.85,
            popup=folium.Popup(popup, max_width=400),
        ).add_to(cluster)

    cols = [
        "video",
        "timestamp",
        "plate_text",
        "fused_confidence",
        "review_status",
        "geolocation_mode",
        "geo_spread_m",
        "vehicle_type",
        "vehicle_color",
        "vehicle_make_model",
        "support_frames",
        "plate_sharpness_avg",
        "latitude",
        "longitude",
    ]
    table_df = all_df[cols].copy().sort_values(["fused_confidence", "timestamp"], ascending=[False, True])
    table_html = table_df.to_html(index=False, classes="det-table")

    summary = summary_payload(all_df)
    summary_html = "".join(
        f"<li><b>{label}</b>: {value}</li>"
        for label, value in [
            ("Observations", summary["total_observations"]),
            ("Unique Plates", summary["unique_plates"]),
            ("Unique Videos", summary["unique_videos"]),
            ("Avg Confidence", summary["avg_fused_confidence"]),
            ("High Confidence", summary["high_confidence_observations"]),
            ("Needs Review", summary["needs_review"]),
        ]
    )

    panel_html = f"""
    <div style='position: fixed; top: 10px; right: 10px; z-index:9999; background: white; padding: 10px; border: 1px solid #ccc; max-height: 70vh; overflow:auto; width: 46vw;'>
      <h4 style='margin:0 0 6px 0;'>License Plate & Vehicle Summary</h4>
      <ul style='margin-top:0; padding-left: 18px;'>{summary_html}</ul>
      <input id='report-filter' type='text' placeholder='Filter plate, type, color, make/model, video' style='width:100%; margin: 0 0 8px 0; padding: 6px;' />
      {table_html}
    </div>
    <script>
    const input = document.getElementById('report-filter');
    const table = document.querySelector('.det-table');
    const rows = table ? Array.from(table.querySelectorAll('tbody tr')) : [];
    if (input) {{
      input.addEventListener('input', () => {{
        const needle = input.value.toLowerCase().trim();
        rows.forEach((row) => {{
          const text = row.innerText.toLowerCase();
          row.style.display = !needle || text.includes(needle) ? '' : 'none';
        }});
      }});
    }}
    </script>
    """

    m.get_root().html.add_child(folium.Element(panel_html))
    folium.LayerControl().add_to(m)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_html))

    if summary_output is not None:
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if geojson_output is not None:
        write_geojson(all_df, geojson_output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build interactive detection map+listing report")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--geojson-output", type=Path)
    args = parser.parse_args()

    build_report(args.input_dir, args.output, args.summary_output, args.geojson_output)
    print(f"report={args.output}")


if __name__ == "__main__":
    main()
