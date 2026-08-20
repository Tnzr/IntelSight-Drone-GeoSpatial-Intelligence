from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

PLATE_RE = re.compile(r"[^A-Z0-9]")


def normalize_plate(s: str) -> str:
    return PLATE_RE.sub("", (s or "").upper())


def unresolved_cluster_key(row: pd.Series) -> str:
    vehicle_type = str(row.get("vehicle_type") or "unknown").upper()
    vehicle_color = str(row.get("vehicle_color") or "unknown").upper()
    return f"UNRESOLVED::{vehicle_type}::{vehicle_color}"


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    numeric_values = pd.to_numeric(values, errors="coerce").fillna(0.0)
    numeric_weights = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    total_weight = float(numeric_weights.sum())
    if total_weight <= 0.0:
        return float(numeric_values.mean()) if len(numeric_values) else 0.0
    return float((numeric_values * numeric_weights).sum() / total_weight)


def mean_of_json_list(series: pd.Series, index: int) -> float:
    values = []
    for item in series:
        try:
            parsed = json.loads(item) if isinstance(item, str) else item
            if isinstance(parsed, list) and len(parsed) > index:
                values.append(float(parsed[index]))
        except Exception:
            continue
    return float(sum(values) / len(values)) if values else 0.0


def add_proxy_object_geolocation(frame: pd.DataFrame, horizontal_fov_deg: float = 78.0, vertical_fov_deg: float = 60.0) -> pd.DataFrame:
    if frame.empty:
        return frame

    df = frame.copy()
    for required_column, default_value in [
        ("bbox_center_x_norm", 0.5),
        ("bbox_center_y_norm", 0.5),
        ("rel_alt", 0.0),
        ("latitude", 0.0),
        ("longitude", 0.0),
    ]:
        if required_column not in df.columns:
            df[required_column] = default_value

    x_norm = pd.to_numeric(df["bbox_center_x_norm"], errors="coerce").fillna(0.5)
    y_norm = pd.to_numeric(df["bbox_center_y_norm"], errors="coerce").fillna(0.5)
    rel_alt = pd.to_numeric(df["rel_alt"], errors="coerce").fillna(0.0)
    base_lat = pd.to_numeric(df["latitude"], errors="coerce").fillna(0.0)
    base_lon = pd.to_numeric(df["longitude"], errors="coerce").fillna(0.0)

    hfov_rad = math.radians(horizontal_fov_deg)
    vfov_rad = math.radians(vertical_fov_deg)
    max_half_width_m = rel_alt * math.tan(hfov_rad / 2.0)
    max_half_height_m = rel_alt * math.tan(vfov_rad / 2.0)

    east_m = (x_norm - 0.5) * 2.0 * max_half_width_m
    north_m = (0.5 - y_norm) * 2.0 * max_half_height_m

    meters_per_deg_lat = 111_320.0
    lat_offset_deg = north_m / meters_per_deg_lat
    cos_lat = base_lat.map(lambda v: max(0.2, abs(math.cos(math.radians(float(v))))))
    lon_offset_deg = east_m / (meters_per_deg_lat * cos_lat)

    df["proxy_object_latitude"] = base_lat + lat_offset_deg
    df["proxy_object_longitude"] = base_lon + lon_offset_deg
    df["proxy_ground_offset_m"] = (east_m**2 + north_m**2).pow(0.5)
    return df


def fuse_file(csv_path: Path, output_dir: Path, frame_window: int) -> Path:
    df = pd.read_csv(csv_path)
    if df.empty:
        out = output_dir / f"{csv_path.stem}.fused.csv"
        df.to_csv(out, index=False)
        return out

    df = add_proxy_object_geolocation(df)
    df["plate_norm"] = df["plate_text"].fillna("").map(normalize_plate)
    df["cluster_key"] = df.apply(
        lambda row: row["plate_norm"] if len(str(row["plate_norm"])) >= 3 else unresolved_cluster_key(row),
        axis=1,
    )
    df = df.sort_values(["video", "frame"]).reset_index(drop=True)

    if df.empty:
        out = output_dir / f"{csv_path.stem}.fused.csv"
        df.to_csv(out, index=False)
        return out

    clusters = []
    current = []

    def flush_cluster(cluster_rows):
        if not cluster_rows:
            return
        cdf = pd.DataFrame(cluster_rows)

        text_scores = defaultdict(float)
        for _, row in cdf.iterrows():
            cluster_key = str(row["cluster_key"])
            score = float(row["plate_ocr_conf"]) + 0.25 * float(row["plate_det_conf"])
            text_scores[cluster_key] += score
        best_key = max(text_scores.items(), key=lambda kv: kv[1])[0]

        best_rows = cdf[cdf["cluster_key"] == best_key]
        rep_idx = best_rows["plate_ocr_conf"].astype(float).idxmax()
        if float(best_rows.loc[rep_idx, "plate_ocr_conf"]) <= 0.0:
            rep_idx = best_rows["plate_det_conf"].astype(float).idxmax()
        rep = best_rows.loc[rep_idx]

        has_resolved_text = any(best_rows["plate_norm"].str.len() >= 3)
        best_text = rep["plate_norm"] if has_resolved_text else f"UNRESOLVED_{str(rep['vehicle_type']).upper()}"

        fused_conf = min(
            1.0,
            float(best_rows["plate_ocr_conf"].astype(float).mean())
            + 0.25 * float(best_rows["plate_det_conf"].astype(float).mean())
            + 0.10 * min(len(best_rows), 5) / 5.0,
        )

        weight_series = best_rows["plate_det_conf"].astype(float) + 0.5 * best_rows["vehicle_type_conf"].astype(float)
        lat_avg = weighted_mean(best_rows.get("proxy_object_latitude", best_rows["latitude"]), weight_series)
        lon_avg = weighted_mean(best_rows.get("proxy_object_longitude", best_rows["longitude"]), weight_series)
        rel_alt_avg = weighted_mean(best_rows["rel_alt"], weight_series)
        plate_area_avg = weighted_mean(best_rows["plate_bbox_area"], weight_series) if "plate_bbox_area" in best_rows.columns else 0.0
        vehicle_area_avg = weighted_mean(best_rows["vehicle_bbox_area"], weight_series) if "vehicle_bbox_area" in best_rows.columns else 0.0
        track_span_frames = int(cdf["frame"].max()) - int(cdf["frame"].min())
        track_span_seconds = max(0.0, track_span_frames / 30.0)
        geo_spread = float(
            (
                (pd.to_numeric(best_rows.get("proxy_object_latitude", best_rows["latitude"]), errors="coerce") - lat_avg).abs().mean()
                + (pd.to_numeric(best_rows.get("proxy_object_longitude", best_rows["longitude"]), errors="coerce") - lon_avg).abs().mean()
            )
            / 2.0
        )
        geo_spread_m = round(geo_spread * 111_000.0, 2)
        ground_offset_m = weighted_mean(best_rows.get("proxy_ground_offset_m", pd.Series([0.0] * len(best_rows))), weight_series)
        if plate_area_avg > 0.0 and vehicle_area_avg > 0.0:
            object_scale_ratio = plate_area_avg / max(vehicle_area_avg, 1.0)
        else:
            object_scale_ratio = 0.0
        confidence_boost = min(0.2, min(len(best_rows), 6) * 0.03)
        fused_conf = min(1.0, fused_conf + confidence_boost)

        clusters.append(
            {
                "video": rep["video"],
                "frame_start": int(cdf["frame"].min()),
                "frame_end": int(cdf["frame"].max()),
                "support_frames": int(len(cdf)),
                "plate_text": best_text,
                "plate_resolved": bool(has_resolved_text),
                "fused_confidence": round(float(fused_conf), 4),
                "latitude": round(float(lat_avg), 6),
                "longitude": round(float(lon_avg), 6),
                "rel_alt": round(float(rel_alt_avg), 3),
                "geo_spread_m": geo_spread_m,
                "object_scale_ratio": round(float(object_scale_ratio), 4),
                "track_span_frames": track_span_frames,
                "track_span_seconds": round(float(track_span_seconds), 3),
                "timestamp": rep["timestamp"],
                "vehicle_type": rep["vehicle_type"],
                "vehicle_color": rep["vehicle_color"],
                "vehicle_make_model": rep.get("vehicle_make_model", None),
                "vehicle_type_conf": float(rep["vehicle_type_conf"]),
                "plate_sharpness_avg": round(float(cdf["plate_sharpness"].astype(float).mean()), 3),
                "vehicle_bbox_area_avg": round(float(vehicle_area_avg), 2),
                "plate_bbox_area_avg": round(float(plate_area_avg), 2),
                "proxy_ground_offset_m": round(float(ground_offset_m), 2),
                "geolocation_mode": "multi_frame_pixel_proxy" if len(best_rows) > 1 else "single_frame_pixel_proxy",
            }
        )

    prev = None
    for _, row in df.iterrows():
        if prev is None:
            current = [row]
            prev = row
            continue

        same_video = row["video"] == prev["video"]
        close_frame = int(row["frame"]) - int(prev["frame"]) <= frame_window
        same_plate = row["cluster_key"] == prev["cluster_key"]

        if same_video and close_frame and same_plate:
            current.append(row)
        else:
            flush_cluster(current)
            current = [row]
        prev = row

    flush_cluster(current)

    out_df = pd.DataFrame(clusters)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = output_dir / f"{csv_path.stem}.fused.csv"
    out_df.to_csv(out_csv, index=False)
    return out_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse multi-frame plate observations")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--frame-window", type=int, default=12)
    args = parser.parse_args()

    outputs = []
    for csv_path in sorted(args.input_dir.glob("*.geotagged.csv")):
        outputs.append(str(fuse_file(csv_path, args.output_dir, args.frame_window)))

    summary = {"fused_files": len(outputs), "outputs": outputs}
    (args.output_dir / "fusion-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
