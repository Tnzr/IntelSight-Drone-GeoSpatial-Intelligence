from __future__ import annotations

import argparse
from pathlib import Path

import folium
import pandas as pd

COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
]


def add_flight_layer(m: folium.Map, csv_path: Path, color: str) -> dict:
    df = pd.read_csv(csv_path)
    if df.empty:
        return {"flight": csv_path.stem, "frames": 0}

    lat_col = "latitude"
    lon_col = "longitude"
    alt_col = "rel_alt" if "rel_alt" in df.columns else "altitude"

    df = df.dropna(subset=[lat_col, lon_col])
    coords = [[float(r[lat_col]), float(r[lon_col])] for _, r in df.iterrows()]

    layer = folium.FeatureGroup(name=csv_path.stem, show=True)
    folium.PolyLine(coords, color=color, weight=3, opacity=0.9).add_to(layer)

    step = max(len(df) // 40, 1)
    for i in range(0, len(df), step):
        row = df.iloc[i]
        popup = (
            f"<b>Flight</b>: {csv_path.stem}<br>"
            f"<b>Frame</b>: {row.get('frame', i)}<br>"
            f"<b>Time</b>: {row.get('timestamp', '')}<br>"
            f"<b>Rel Alt</b>: {row.get(alt_col, '')}<br>"
            f"<b>ISO</b>: {row.get('iso', '')}<br>"
            f"<b>Shutter</b>: {row.get('shutter', '')}<br>"
            f"<b>Focal</b>: {row.get('focal_len', '')}"
        )
        folium.CircleMarker(
            location=[float(row[lat_col]), float(row[lon_col])],
            radius=2,
            color=color,
            fill=True,
            fill_opacity=0.8,
            popup=folium.Popup(popup, max_width=320),
        ).add_to(layer)

    folium.Marker(coords[0], tooltip=f"{csv_path.stem} start", icon=folium.Icon(color="green")).add_to(layer)
    folium.Marker(coords[-1], tooltip=f"{csv_path.stem} end", icon=folium.Icon(color="red")).add_to(layer)

    layer.add_to(m)

    return {
        "flight": csv_path.stem,
        "frames": int(len(df)),
        "start": str(df.iloc[0].get("timestamp", "")),
        "end": str(df.iloc[-1].get("timestamp", "")),
        "min_rel_alt": float(df[alt_col].min()) if alt_col in df.columns else None,
        "max_rel_alt": float(df[alt_col].max()) if alt_col in df.columns else None,
    }


def build_dashboard(input_dir: Path, output_html: Path) -> None:
    csv_files = sorted(input_dir.glob("*.srt.csv"))
    if not csv_files:
        raise RuntimeError("No *.srt.csv files found. Run parse_dji_srt.py first.")

    first = pd.read_csv(csv_files[0]).dropna(subset=["latitude", "longitude"])
    center = [float(first.iloc[0]["latitude"]), float(first.iloc[0]["longitude"])]

    m = folium.Map(location=center, zoom_start=16, tiles="CartoDB positron")

    summary_rows = []
    for idx, csv_file in enumerate(csv_files):
        summary_rows.append(add_flight_layer(m, csv_file, COLORS[idx % len(COLORS)]))

    folium.LayerControl(collapsed=False).add_to(m)

    summary_table = pd.DataFrame(summary_rows).to_html(index=False, classes="summary-table")
    html = f"""
    <div style='position: fixed; top: 10px; left: 10px; z-index:9999; background: white; padding: 10px; border: 1px solid #ddd; max-height: 40vh; overflow:auto;'>
      <h4 style='margin:0 0 6px 0;'>IntelSight Flight Dashboard</h4>
      {summary_table}
    </div>
    """
    m.get_root().html.add_child(folium.Element(html))

    output_html.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_html))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build lightweight multi-flight trajectory dashboard")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    build_dashboard(args.input_dir, args.output)
    print(f"dashboard={args.output}")


if __name__ == "__main__":
    main()
