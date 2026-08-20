from __future__ import annotations

import io
import json
import hashlib
import math
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from store import build_cache_key, get_cached_mission, ingest_mission_digest, list_cached_missions, load_mission_digest, source_label


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
VIDEO_PREVIEW_DIR = WORKSPACE_ROOT / "output" / "web-dashboard" / "video-previews"
LAB_ARTIFACTS_DIR = WORKSPACE_ROOT / "output" / "lab-artifacts"
LAB_EXPORTER = WORKSPACE_ROOT / "modules" / "cv-pipeline" / "export_lab_artifacts.py"
LAB_MODULE_NAMES = {
    "pipeline": "Integration · module map",
    "module1": "Module 1 · flightrecord-parser (Rust)",
    "module2": "Module 2 · flight-visualizer (SRT)",
    "module3": "Module 3 · cv-pipeline (detection + plates)",
    "module4": "Module 4 · sync + fused report",
    "module5": "Module 5 · overlay motion",
}
LAB_MODULE_ORDER = ["pipeline", "module1", "module2", "module3", "module4", "module5"]
LOCAL_COLOR_PALETTE = [
    "#2563eb",
    "#f97316",
    "#10b981",
    "#ef4444",
    "#8b5cf6",
    "#06b6d4",
    "#84cc16",
    "#f59e0b",
]


@dataclass(frozen=True)
class TrajectoryBundle:
    points: pd.DataFrame
    line: pd.DataFrame
    source_name: str


@dataclass(frozen=True)
class DetectionBundle:
    rows: pd.DataFrame
    source_name: str


def _source_name(source: Any) -> str:
    if isinstance(source, Path):
        return source.name
    return str(getattr(source, "name", "uploaded"))


def _source_bytes(source: Any) -> bytes:
    if isinstance(source, Path):
        return source.read_bytes()
    if hasattr(source, "getvalue"):
        return source.getvalue()
    if hasattr(source, "read"):
        data = source.read()
        return data if isinstance(data, bytes) else str(data).encode("utf-8")
    raise TypeError(f"Unsupported source type: {type(source)!r}")


def _source_text(source: Any) -> str:
    return _source_bytes(source).decode("utf-8", errors="ignore")


def _load_json(source: Any) -> dict[str, Any]:
    payload = json.loads(_source_text(source))
    return payload if isinstance(payload, dict) else {"value": payload}


def _load_csv(source: Any) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(_source_bytes(source)))


def _coerce_numeric(df: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in df.columns:
        return pd.Series([default] * len(df), index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce").fillna(default)


def derive_proxy_geolocation(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    required = {"bbox_center_x_norm", "bbox_center_y_norm", "rel_alt", "latitude", "longitude"}
    if not required.issubset(set(frame.columns)):
        return frame

    df = frame.copy()
    x_norm = pd.to_numeric(df["bbox_center_x_norm"], errors="coerce").fillna(0.5)
    y_norm = pd.to_numeric(df["bbox_center_y_norm"], errors="coerce").fillna(0.5)
    rel_alt = pd.to_numeric(df["rel_alt"], errors="coerce").fillna(0.0)
    lat = pd.to_numeric(df["latitude"], errors="coerce").fillna(0.0)
    lon = pd.to_numeric(df["longitude"], errors="coerce").fillna(0.0)

    hfov_rad = math.radians(78.0)
    vfov_rad = math.radians(60.0)
    half_width_m = rel_alt * math.tan(hfov_rad / 2.0)
    half_height_m = rel_alt * math.tan(vfov_rad / 2.0)

    east_m = (x_norm - 0.5) * 2.0 * half_width_m
    north_m = (0.5 - y_norm) * 2.0 * half_height_m
    meters_per_deg_lat = 111_320.0
    lat_offset = north_m / meters_per_deg_lat
    cos_lat = lat.map(lambda v: max(0.2, abs(math.cos(math.radians(float(v))))))
    lon_offset = east_m / (meters_per_deg_lat * cos_lat)

    df["proxy_object_latitude"] = lat + lat_offset
    df["proxy_object_longitude"] = lon + lon_offset
    df["proxy_ground_offset_m"] = (east_m**2 + north_m**2).pow(0.5)
    return df


def _normalize_trajectory_frame(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()

    normalized["latitude"] = _coerce_numeric(normalized, "latitude")
    normalized["longitude"] = _coerce_numeric(normalized, "longitude")

    altitude_candidates = ["rel_alt", "altitude", "altitude_m", "height", "abs_alt"]
    altitude_column = next((column for column in altitude_candidates if column in normalized.columns), None)
    if altitude_column is None:
        normalized["altitude_m"] = 0.0
    else:
        normalized["altitude_m"] = _coerce_numeric(normalized, altitude_column)

    if "frame" not in normalized.columns:
        normalized["frame"] = range(len(normalized))

    if "timestamp" not in normalized.columns:
        normalized["timestamp"] = ""

    return normalized.dropna(subset=["latitude", "longitude"])


def _normalize_detection_frame(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()

    normalized["latitude"] = _coerce_numeric(normalized, "latitude")
    normalized["longitude"] = _coerce_numeric(normalized, "longitude")
    if "rel_alt" in normalized.columns:
        normalized["altitude_m"] = _coerce_numeric(normalized, "rel_alt", 0.0)
    elif "altitude_m" in normalized.columns:
        normalized["altitude_m"] = _coerce_numeric(normalized, "altitude_m", 0.0)
    elif "altitude" in normalized.columns:
        normalized["altitude_m"] = _coerce_numeric(normalized, "altitude", 0.0)
    else:
        normalized["altitude_m"] = 0.0

    normalized["fused_confidence"] = _coerce_numeric(normalized, "fused_confidence", 0.0)
    normalized["vehicle_type_conf"] = _coerce_numeric(normalized, "vehicle_type_conf", 0.0)
    normalized["support_frames"] = _coerce_numeric(normalized, "support_frames", 0).astype(int)

    normalized = derive_proxy_geolocation(normalized)
    if {"proxy_object_latitude", "proxy_object_longitude"}.issubset(set(normalized.columns)) and not normalized.empty:
        unique_raw_geo = int(normalized[["latitude", "longitude"]].drop_duplicates().shape[0])
        # Sync CSVs are drone-anchored and often repeat one GPS over many detections.
        if unique_raw_geo <= max(3, len(normalized) // 25):
            normalized["drone_latitude"] = normalized["latitude"]
            normalized["drone_longitude"] = normalized["longitude"]
            normalized["latitude"] = pd.to_numeric(normalized["proxy_object_latitude"], errors="coerce").fillna(normalized["latitude"])
            normalized["longitude"] = pd.to_numeric(normalized["proxy_object_longitude"], errors="coerce").fillna(normalized["longitude"])
            if "geolocation_mode" not in normalized.columns:
                normalized["geolocation_mode"] = "single_frame_pixel_proxy_from_sync"
            else:
                normalized["geolocation_mode"] = normalized["geolocation_mode"].fillna("single_frame_pixel_proxy_from_sync")

    if {"proxy_object_latitude", "proxy_object_longitude"}.issubset(set(normalized.columns)):
        normalized["display_latitude"] = pd.to_numeric(normalized["proxy_object_latitude"], errors="coerce").fillna(normalized["latitude"])
        normalized["display_longitude"] = pd.to_numeric(normalized["proxy_object_longitude"], errors="coerce").fillna(normalized["longitude"])
    else:
        normalized["display_latitude"] = normalized["latitude"]
        normalized["display_longitude"] = normalized["longitude"]
    normalized["display_altitude_m"] = normalized["altitude_m"]

    for column in ["vehicle_type", "vehicle_color", "vehicle_make_model", "plate_text", "video", "timestamp"]:
        if column not in normalized.columns:
            normalized[column] = ""
        normalized[column] = normalized[column].fillna("").astype(str)

    if "plate_resolved" not in normalized.columns:
        normalized["plate_resolved"] = normalized["plate_text"].str.len() > 0
    else:
        normalized["plate_resolved"] = normalized["plate_resolved"].fillna(False).astype(bool)

    if "review_status" not in normalized.columns:
        normalized["review_status"] = normalized.apply(
            lambda row: "stable"
            if float(row.get("fused_confidence", 0.0)) >= 0.8 and int(row.get("support_frames", 0)) >= 3
            else ("needs_review" if float(row.get("fused_confidence", 0.0)) < 0.65 else "usable"),
            axis=1,
        )

    normalized = normalized.dropna(subset=["latitude", "longitude"])
    normalized["object_label"] = normalized.apply(
        lambda row: row["plate_text"]
        if row.get("plate_resolved") and row.get("plate_text")
        else f"{row.get('vehicle_type', 'object')}",
        axis=1,
    )
    return normalized


def with_object_ids(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    normalized = df.reset_index(drop=True).copy()
    normalized["object_id"] = normalized.index.astype(int)
    return normalized


def object_display_name(row: pd.Series) -> str:
    label = str(row.get("plate_text") or row.get("object_label") or "object").strip() or "object"
    vehicle_type = str(row.get("vehicle_type") or "unknown")
    confidence = float(row.get("fused_confidence", 0.0))
    return f"#{int(row.get('object_id', 0)):04d} | {label} | {vehicle_type} | conf {confidence:.2f}"


def _extract_selected_object_ids(selection_state: Any) -> set[int]:
    if selection_state is None:
        return set()
    if isinstance(selection_state, dict):
        points = selection_state.get("selection", {}).get("points", [])
    else:
        selection_attr = getattr(selection_state, "selection", None)
        if isinstance(selection_attr, dict):
            points = selection_attr.get("points", [])
        else:
            points = getattr(selection_attr, "points", []) if selection_attr is not None else []
    selected: set[int] = set()
    for point in points:
        customdata = point.get("customdata") if isinstance(point, dict) else None
        if isinstance(customdata, list) and customdata:
            try:
                selected.add(int(customdata[0]))
            except (TypeError, ValueError):
                continue
        elif customdata is not None:
            try:
                selected.add(int(customdata))
            except (TypeError, ValueError):
                continue
    return selected


def _selected_rows_from_table_state(table_state: Any) -> list[int]:
    if isinstance(table_state, dict):
        rows = table_state.get("selection", {}).get("rows", [])
        return [int(row) for row in rows]
    selection_attr = getattr(table_state, "selection", None)
    if selection_attr is None:
        return []
    rows = selection_attr.get("rows", []) if isinstance(selection_attr, dict) else getattr(selection_attr, "rows", [])
    return [int(row) for row in rows]


def _load_geojson(source: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    payload = _load_json(source)
    point_rows = []
    line_rows = []

    for feature in payload.get("features", []):
        geometry = feature.get("geometry") or {}
        properties = dict(feature.get("properties") or {})
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates") or []

        if geometry_type == "Point" and len(coordinates) >= 2:
            lon = float(coordinates[0])
            lat = float(coordinates[1])
            alt = float(coordinates[2]) if len(coordinates) >= 3 else float(properties.get("rel_alt", properties.get("altitude", 0.0)))
            point_rows.append({**properties, "longitude": lon, "latitude": lat, "altitude_m": alt})
        elif geometry_type == "LineString":
            for idx, coord in enumerate(coordinates):
                if len(coord) < 2:
                    continue
                lon = float(coord[0])
                lat = float(coord[1])
                alt = float(coord[2]) if len(coord) >= 3 else float(properties.get("rel_alt", properties.get("altitude", 0.0)))
                line_rows.append({"sequence": idx, "longitude": lon, "latitude": lat, "altitude_m": alt})

    return pd.DataFrame(point_rows), pd.DataFrame(line_rows)


def load_trajectory_bundle(source: Any) -> TrajectoryBundle:
    source_name = _source_name(source)
    suffix = Path(source_name).suffix.lower()

    if suffix in {".geojson", ".json"}:
        points_df, line_df = _load_geojson(source)
        if points_df.empty and line_df.empty:
            return TrajectoryBundle(points=pd.DataFrame(), line=pd.DataFrame(), source_name=source_name)
        if points_df.empty:
            points_df = line_df.copy()
        return TrajectoryBundle(points=_normalize_trajectory_frame(points_df), line=line_df, source_name=source_name)

    if suffix == ".csv":
        df = _load_csv(source)
        return TrajectoryBundle(points=_normalize_trajectory_frame(df), line=pd.DataFrame(), source_name=source_name)

    raise ValueError(f"Unsupported trajectory file type: {source_name}")


def load_detection_bundle(source: Any) -> DetectionBundle:
    source_name = _source_name(source)
    suffix = Path(source_name).suffix.lower()

    if suffix in {".geojson", ".json"}:
        points_df, _ = _load_geojson(source)
        if points_df.empty:
            return DetectionBundle(rows=pd.DataFrame(), source_name=source_name)
        return DetectionBundle(rows=_normalize_detection_frame(points_df), source_name=source_name)

    if suffix == ".csv":
        df = _load_csv(source)
        return DetectionBundle(rows=_normalize_detection_frame(df), source_name=source_name)

    raise ValueError(f"Unsupported detection file type: {source_name}")


def load_summary_payload(source: Any | None) -> dict[str, Any]:
    if source is None:
        return {}
    suffix = Path(_source_name(source)).suffix.lower()
    if suffix != ".json":
        return {}
    payload = _load_json(source)
    return payload if isinstance(payload, dict) else {}


def discover_files_in_root(root: Path) -> dict[str, list[Path]]:
    patterns = {
        "trajectory": [
            "**/*.trajectory.geojson",
            "**/*.srt.csv",
            "**/*.flightpath.geojson",
            "**/*.trajectory.csv",
            "**/*.geojson",
            "**/*.csv",
        ],
        "detections": [
            "**/lp_vehicle_report.geojson",
            "**/*.fused.csv",
            "**/*.detections.jsonl",
            "**/*.detection.geojson",
            "**/*.detection.csv",
            "**/*.geojson",
            "**/*.csv",
        ],
        "summary": [
            "**/*.summary.json",
            "**/*summary*.json",
            "**/*.report.json",
        ],
    }

    files: dict[str, list[Path]] = {}
    for key, glob_patterns in patterns.items():
        discovered: set[Path] = set()
        for pattern in glob_patterns:
            for match in root.glob(pattern):
                if match.is_file():
                    discovered.add(match)
        files[key] = sorted(discovered, key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def discover_workspace_files() -> dict[str, list[Path]]:
    return discover_files_in_root(WORKSPACE_ROOT)


def discover_uploaded_archive_files(uploaded_archive: Any | None) -> dict[str, list[Path]]:
    if uploaded_archive is None:
        return {"trajectory": [], "detections": [], "summary": []}

    try:
        source_bytes = _source_bytes(uploaded_archive)
    except TypeError:
        return {"trajectory": [], "detections": [], "summary": []}

    if not zipfile.is_zipfile(io.BytesIO(source_bytes)):
        return {"trajectory": [], "detections": [], "summary": []}

    with tempfile.TemporaryDirectory(prefix="intelsight-upload-") as temp_dir:
        extract_root = Path(temp_dir)
        with zipfile.ZipFile(io.BytesIO(source_bytes), "r") as archive:
            archive.extractall(extract_root)
        return discover_files_in_root(extract_root)


def discover_workspace_videos() -> list[Path]:
    patterns = [
        "data/flightrecords/**/*.MP4",
        "data/flightrecords/**/*.mp4",
        "output/cv/**/*.MP4",
        "output/cv/**/*.mp4",
    ]
    discovered: list[Path] = []
    for pattern in patterns:
        discovered.extend(WORKSPACE_ROOT.glob(pattern))
    return sorted({path for path in discovered if path.is_file()}, key=lambda path: path.stat().st_mtime, reverse=True)


def discover_overlay_videos() -> list[Path]:
    patterns = [
        "output/cv/**/overlay/*.mp4",
        "output/cv/**/*.overlay.mp4",
    ]
    discovered: list[Path] = []
    for pattern in patterns:
        discovered.extend(WORKSPACE_ROOT.glob(pattern))
    return sorted({path for path in discovered if path.is_file()}, key=lambda path: path.stat().st_mtime, reverse=True)


def resolve_overlay_candidates(detections: pd.DataFrame, overlays: list[Path]) -> list[Path]:
    if detections.empty or "video" not in detections.columns:
        return overlays
    stems = {
        Path(str(value)).stem
        for value in detections["video"].dropna().astype(str).tolist()
        if str(value).strip()
    }
    matched = [overlay for overlay in overlays if any(stem in overlay.stem for stem in stems)]
    return matched or overlays


def _variant_suffix(variant: str) -> str:
    return {
        "original": "orig",
        "1080p": "h1080",
        "720p": "h720",
    }.get(variant, "orig")


def _preview_output_path(video_path: Path, variant: str) -> Path:
    VIDEO_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{video_path.resolve()}|{int(video_path.stat().st_mtime)}|{variant}"
    digest = hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:12]
    return VIDEO_PREVIEW_DIR / f"{video_path.stem}.{_variant_suffix(variant)}.{digest}.mp4"


def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def _cv2_downscale_video(source_path: Path, output_path: Path, target_height: int) -> None:
    import cv2

    cap = cv2.VideoCapture(str(source_path))
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video for downscale: {source_path}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
    if width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError(f"Invalid input dimensions for video: {source_path}")

    out_height = min(target_height, height)
    out_width = int(round((width * out_height) / height))
    out_width = max(2, (out_width // 2) * 2)
    out_height = max(2, (out_height // 2) * 2)

    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (out_width, out_height))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Unable to open output writer for: {output_path}")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        resized = cv2.resize(frame, (out_width, out_height), interpolation=cv2.INTER_AREA)
        writer.write(resized)

    writer.release()
    cap.release()


def get_video_for_playback(video_path: Path, variant: str) -> tuple[Path, str]:
    if variant == "original":
        return video_path, "original"

    target_height = 1080 if variant == "1080p" else 720
    preview_path = _preview_output_path(video_path, variant)
    if preview_path.exists():
        return preview_path, "cached"

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        vf = f"scale=-2:{target_height}"
        command = [ffmpeg_path, "-y", "-i", str(video_path), "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "24", "-an", str(preview_path)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0 and preview_path.exists():
            return preview_path, "generated_ffmpeg"

    _cv2_downscale_video(video_path, preview_path, target_height)
    return preview_path, "generated_cv2"


def resolve_video_candidates(detections: pd.DataFrame, videos: list[Path]) -> list[Path]:
    if detections.empty or "video" not in detections.columns:
        return videos

    wanted_names = {
        Path(str(value)).name
        for value in detections["video"].dropna().astype(str).tolist()
        if str(value).strip()
    }
    wanted_stems = {Path(name).stem for name in wanted_names}
    matched = [video for video in videos if video.name in wanted_names or video.stem in wanted_stems]
    return matched or videos


def resolve_video_selection(selected_detections: DetectionBundle, videos: list[Path]) -> tuple[Path | None, list[Path]]:
    candidates = resolve_video_candidates(selected_detections.rows, videos)
    return (candidates[0] if candidates else None, candidates)


def figure_extent(points: pd.DataFrame, detections: pd.DataFrame) -> tuple[float, float, float, float] | None:
    coords = []
    if not points.empty:
        coords.extend(list(zip(points["longitude"], points["latitude"])))
    if not detections.empty:
        lon_col = "display_longitude" if "display_longitude" in detections.columns else "longitude"
        lat_col = "display_latitude" if "display_latitude" in detections.columns else "latitude"
        coords.extend(list(zip(detections[lon_col], detections[lat_col])))
    if not coords:
        return None

    longitudes = [float(item[0]) for item in coords]
    latitudes = [float(item[1]) for item in coords]
    return min(longitudes), max(longitudes), min(latitudes), max(latitudes)


def to_local_enu(
    longitudes: pd.Series,
    latitudes: pd.Series,
    altitudes: pd.Series,
    origin_lon: float,
    origin_lat: float,
    origin_alt: float,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    meters_per_deg_lat = 111_320.0
    cos_lat = max(0.2, abs(math.cos(math.radians(origin_lat))))
    meters_per_deg_lon = meters_per_deg_lat * cos_lat
    east = (pd.to_numeric(longitudes, errors="coerce").fillna(origin_lon) - origin_lon) * meters_per_deg_lon
    north = (pd.to_numeric(latitudes, errors="coerce").fillna(origin_lat) - origin_lat) * meters_per_deg_lat
    up = pd.to_numeric(altitudes, errors="coerce").fillna(origin_alt) - origin_alt
    return east, north, up


def _trajectory_line_frame(trajectory: TrajectoryBundle) -> pd.DataFrame:
    if not trajectory.line.empty:
        return trajectory.line
    return trajectory.points


def build_2d_figure(
    trajectory: TrajectoryBundle,
    detections: DetectionBundle,
    selected_ids: set[int] | None = None,
    focus_on_detections: bool = True,
) -> go.Figure:
    fig = go.Figure()
    selected_ids = selected_ids or set()
    line_frame = _trajectory_line_frame(trajectory)

    if not line_frame.empty:
        fig.add_trace(
            go.Scattermapbox(
                lon=line_frame["longitude"],
                lat=line_frame["latitude"],
                mode="lines",
                name="Trajectory line",
                line=dict(color="#2563eb", width=4),
                hoverinfo="skip",
            )
        )

    if not trajectory.points.empty:
        fig.add_trace(
            go.Scattermapbox(
                lon=trajectory.points["longitude"],
                lat=trajectory.points["latitude"],
                mode="markers",
                name="Telemetry samples",
                marker=dict(size=5, color="#64748b", opacity=0.6),
                text=[f"Frame {frame}" for frame in trajectory.points.get("frame", range(len(trajectory.points)))],
                hovertemplate="Telemetry<extra>%{text}</extra>",
            )
        )

    if not detections.rows.empty:
        for idx, (vehicle_type, group) in enumerate(detections.rows.groupby("vehicle_type", dropna=False)):
            hover_text = [
                f"Plate: {row.plate_text or 'unresolved'}<br>"
                f"Vehicle: {row.vehicle_type or 'unknown'}<br>"
                f"Color: {row.vehicle_color or 'unknown'}<br>"
                f"Confidence: {float(row.fused_confidence):.3f}<br>"
                f"Support frames: {int(row.support_frames)}<br>"
                f"Review: {row.review_status}<br>"
                f"Lat/Lon: {float(row.latitude):.6f}, {float(row.longitude):.6f}"
                for row in group.itertuples(index=False)
            ]
            marker_sizes = [max(8, min(16, 8 + float(confidence) * 8)) for confidence in group["fused_confidence"]]
            marker_symbols = ["diamond" if int(object_id) in selected_ids else "circle" for object_id in group["object_id"]]
            fig.add_trace(
                go.Scattermapbox(
                    lon=group["display_longitude"] if "display_longitude" in group.columns else group["longitude"],
                    lat=group["display_latitude"] if "display_latitude" in group.columns else group["latitude"],
                    mode="markers",
                    name=f"{vehicle_type or 'unknown'} ({len(group)})",
                    marker=dict(
                        size=[size + 2 for size in marker_sizes],
                        color=LOCAL_COLOR_PALETTE[idx % len(LOCAL_COLOR_PALETTE)],
                        opacity=0.95,
                        symbol=marker_symbols,
                    ),
                    text=hover_text,
                    hovertemplate="%{text}<extra></extra>",
                    customdata=group[["object_id"]].values,
                )
            )

    center = [0.0, 0.0]
    extent = figure_extent(pd.DataFrame() if (focus_on_detections and not detections.rows.empty) else trajectory.points, detections.rows)
    if extent is not None:
        min_lon, max_lon, min_lat, max_lat = extent
        center = [(min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0]

    fig.update_layout(
        mapbox=dict(style="open-street-map", center=dict(lat=center[0], lon=center[1]), zoom=15),
        margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(orientation="h"),
        height=760,
    )
    return fig


def build_3d_figure(
    trajectory: TrajectoryBundle,
    detections: DetectionBundle,
    selected_ids: set[int] | None = None,
    coordinate_mode: str = "local_meters",
) -> go.Figure:
    fig = go.Figure()
    selected_ids = selected_ids or set()
    line_frame = _trajectory_line_frame(trajectory)

    anchor_frame = trajectory.points if not trajectory.points.empty else detections.rows
    if anchor_frame.empty:
        origin_lon, origin_lat, origin_alt = 0.0, 0.0, 0.0
    else:
        origin_lon = float(anchor_frame["longitude"].iloc[0])
        origin_lat = float(anchor_frame["latitude"].iloc[0])
        origin_alt = float(anchor_frame["altitude_m"].iloc[0]) if "altitude_m" in anchor_frame.columns else 0.0

    if not line_frame.empty:
        if coordinate_mode == "local_meters":
            x_vals, y_vals, z_vals = to_local_enu(
                line_frame["longitude"],
                line_frame["latitude"],
                line_frame["altitude_m"],
                origin_lon,
                origin_lat,
                origin_alt,
            )
            x_title, y_title, z_title = "East (m)", "North (m)", "Up (m)"
        else:
            x_vals = line_frame["longitude"]
            y_vals = line_frame["latitude"]
            z_vals = line_frame["altitude_m"]
            x_title, y_title, z_title = "Longitude", "Latitude", "Altitude / Rel Alt (m)"

        fig.add_trace(
            go.Scatter3d(
                x=x_vals,
                y=y_vals,
                z=z_vals,
                mode="lines",
                name="Trajectory",
                line=dict(color="#2563eb", width=6),
                hoverinfo="skip",
            )
        )
    else:
        x_title, y_title, z_title = "East (m)", "North (m)", "Up (m)"

    if not detections.rows.empty:
        for idx, (vehicle_type, group) in enumerate(detections.rows.groupby("vehicle_type", dropna=False)):
            if coordinate_mode == "local_meters":
                x_group, y_group, z_group = to_local_enu(
                    group["display_longitude"] if "display_longitude" in group.columns else group["longitude"],
                    group["display_latitude"] if "display_latitude" in group.columns else group["latitude"],
                    group["display_altitude_m"] if "display_altitude_m" in group.columns else group["altitude_m"],
                    origin_lon,
                    origin_lat,
                    origin_alt,
                )
            else:
                x_group = group["display_longitude"] if "display_longitude" in group.columns else group["longitude"]
                y_group = group["display_latitude"] if "display_latitude" in group.columns else group["latitude"]
                z_group = group["display_altitude_m"] if "display_altitude_m" in group.columns else group["altitude_m"]

            marker_size = [max(4, min(10, 4 + float(confidence) * 7)) for confidence in group["fused_confidence"]]
            if selected_ids:
                marker_size = [size + 4 if int(object_id) in selected_ids else size for size, object_id in zip(marker_size, group["object_id"])]

            fig.add_trace(
                go.Scatter3d(
                    x=x_group,
                    y=y_group,
                    z=z_group,
                    mode="markers",
                    name=f"{vehicle_type or 'unknown'} points",
                    marker=dict(
                        size=marker_size,
                        color=LOCAL_COLOR_PALETTE[idx % len(LOCAL_COLOR_PALETTE)],
                        opacity=0.92,
                    ),
                    text=[
                        f"Plate: {row.plate_text or 'unresolved'}<br>Vehicle: {row.vehicle_type or 'unknown'}<br>"
                        f"Color: {row.vehicle_color or 'unknown'}<br>Confidence: {float(row.fused_confidence):.3f}<br>"
                        f"Alt: {float(row.altitude_m):.1f}m"
                        for row in group.itertuples(index=False)
                    ],
                    hovertemplate="%{text}<extra></extra>",
                    customdata=group[["object_id"]].values,
                )
            )

    fig.update_layout(
        scene=dict(
            xaxis_title=x_title,
            yaxis_title=y_title,
            zaxis_title=z_title,
            aspectmode="data",
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=760,
        legend=dict(orientation="h"),
    )
    return fig


def make_summary_cards(trajectory: TrajectoryBundle, detections: DetectionBundle, summary: dict[str, Any]) -> None:
    detections_df = detections.rows
    trajectory_df = trajectory.points

    resolved = int(detections_df["plate_resolved"].sum()) if not detections_df.empty and "plate_resolved" in detections_df.columns else 0
    unresolved = int(len(detections_df) - resolved) if not detections_df.empty else 0
    confidence_mean = float(detections_df["fused_confidence"].mean()) if not detections_df.empty else 0.0
    vehicle_types = int(detections_df["vehicle_type"].nunique()) if not detections_df.empty else 0

    cols = st.columns(4)
    cols[0].metric("Detection rows", f"{len(detections_df):,}")
    cols[1].metric("Resolved plates", f"{resolved:,}")
    cols[2].metric("Unresolved / review", f"{unresolved:,}")
    cols[3].metric("Vehicle types", f"{vehicle_types:,}")

    if summary:
        st.caption(
            f"Summary snapshot: {summary.get('total_observations', len(detections_df))} observations, "
            f"{summary.get('needs_review', unresolved)} need review, "
            f"{summary.get('high_confidence_observations', 0)} high-confidence observations."
        )
    elif not detections_df.empty:
        st.caption(f"Average fused confidence: {confidence_mean:.3f}")

    if not trajectory_df.empty:
        st.caption(f"Trajectory points loaded: {len(trajectory_df):,}")


def apply_filters(detections: DetectionBundle, min_confidence: float, vehicle_types: list[str], review_modes: list[str]) -> DetectionBundle:
    df = detections.rows.copy()
    if df.empty:
        return detections

    if min_confidence > 0:
        df = df[df["fused_confidence"] >= min_confidence]

    if vehicle_types:
        df = df[df["vehicle_type"].isin(vehicle_types)]

    if review_modes:
        df = df[df["review_status"].isin(review_modes)]

    return DetectionBundle(rows=df, source_name=detections.source_name)


def cache_mission_selection(
    trajectory_bundle: TrajectoryBundle,
    detection_bundle: DetectionBundle,
    summary_payload: dict[str, Any],
    source_names: dict[str, str],
) -> dict[str, Any]:
    cache_key = build_cache_key(
        source_names.get("trajectory", trajectory_bundle.source_name),
        source_names.get("detections", detection_bundle.source_name),
        source_names.get("summary", ""),
    )
    return ingest_mission_digest(
        trajectory_bundle.points,
        detection_bundle.rows,
        cache_key=cache_key,
        trajectory_source=trajectory_bundle.source_name,
        detection_source=detection_bundle.source_name,
        summary_source=source_names.get("summary"),
        video_source=source_names.get("video"),
        summary_payload=summary_payload,
    )


def load_lab_manifest() -> list[dict[str, str]]:
    manifest_path = LAB_ARTIFACTS_DIR / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))
        return [entry for entry in entries if (LAB_ARTIFACTS_DIR / entry.get("name", "")).exists()]
    except Exception:
        return []


def regenerate_lab_artifacts() -> bool:
    if not LAB_EXPORTER.exists():
        return False
    try:
        result = subprocess.run(
            [sys.executable, str(LAB_EXPORTER)],
            capture_output=True,
            text=True,
            timeout=900,
            cwd=str(WORKSPACE_ROOT),
        )
        return result.returncode == 0
    except Exception:
        return False


def render_workshop_lab() -> None:
    st.subheader("IntelSight Workshop Lab")
    st.caption(
        "Per-module demo visualizations generated from real mission artifacts. "
        "The same cells run inside `modules/cv-pipeline/cv_pipeline_lab.ipynb`."
    )
    manifest = load_lab_manifest()
    if not manifest:
        st.info("No lab artifacts found. Generate them with the button below.")
    else:
        by_module: dict[str, list[dict[str, str]]] = {}
        for entry in manifest:
            by_module.setdefault(entry.get("module", "pipeline"), []).append(entry)

        pipeline_entries = by_module.pop("pipeline", [])
        for entry in pipeline_entries:
            st.image(str(WORKSPACE_ROOT / entry["path"]), width="stretch")

        for module_key in LAB_MODULE_ORDER:
            entries = by_module.get(module_key, [])
            if not entries:
                continue
            st.markdown(f"### {LAB_MODULE_NAMES.get(module_key, module_key)}")
            columns = st.columns(len(entries))
            for column, entry in zip(columns, entries):
                column.image(str(WORKSPACE_ROOT / entry["path"]), width="stretch")

    st.divider()
    refresh_col, info_col = st.columns([1, 2])
    with refresh_col:
        if st.button("Regenerate lab artifacts", help="Runs modules/cv-pipeline/export_lab_artifacts.py on the current mission outputs."):
            with st.spinner("Generating workshop visualizations..."):
                if regenerate_lab_artifacts():
                    st.success("Lab artifacts refreshed.")
                    st.rerun()
                else:
                    st.error("Artifact generation failed. Run `python modules/cv-pipeline/export_lab_artifacts.py` manually.")
    with info_col:
        st.caption("Artifacts live in `output/lab-artifacts/` and are consumed by this dashboard and the Tauri desktop app Lab tab.")


def render_workspace_mode(files: dict[str, list[Path]]) -> tuple[Any, Any, Any]:
    st.sidebar.subheader("Workspace files")
    trajectory_files = files.get("trajectory", [])
    detection_files = files.get("detections", [])
    summary_files = files.get("summary", [])

    if not trajectory_files or not detection_files:
        st.warning("No workspace trajectory or detection files were found yet. Run the parsing/report pipeline first, or switch to upload mode.")
        st.stop()

    trajectory_source = st.sidebar.selectbox(
        "Trajectory file",
        trajectory_files,
        format_func=lambda path: str(path.relative_to(WORKSPACE_ROOT)),
        index=0,
    )
    detection_source = st.sidebar.selectbox(
        "Detection file",
        detection_files,
        format_func=lambda path: str(path.relative_to(WORKSPACE_ROOT)),
        index=0,
    )
    summary_source = st.sidebar.selectbox(
        "Summary file (optional)",
        [None] + summary_files,
        format_func=lambda path: "(none)" if path is None else str(path.relative_to(WORKSPACE_ROOT)),
        index=0,
    )
    return trajectory_source, detection_source, summary_source


def render_upload_mode() -> tuple[Any, Any, Any, dict[str, list[Path]]]:
    st.sidebar.subheader("Upload files")
    st.sidebar.caption("Upload a FlagerPublix mission directory as a ZIP archive, or upload individual trajectory/detection files directly.")

    mission_archive = st.sidebar.file_uploader("Mission folder archive (.zip)", type=["zip"], help="Upload a zipped FlagerPublix mission directory to auto-discover the matching files.")
    archive_candidates = discover_uploaded_archive_files(mission_archive)

    if mission_archive is not None and archive_candidates["trajectory"]:
        st.sidebar.caption(f"Discovered {len(archive_candidates['trajectory'])} trajectory candidate(s) and {len(archive_candidates['detections'])} detection candidate(s).")
        trajectory_source = st.sidebar.selectbox(
            "Trajectory file",
            archive_candidates["trajectory"],
            format_func=lambda path: str(path.relative_to(path.anchor)) if path.is_absolute() else str(path),
            index=0,
        )
        detection_source = st.sidebar.selectbox(
            "Detection file",
            archive_candidates["detections"],
            format_func=lambda path: str(path.relative_to(path.anchor)) if path.is_absolute() else str(path),
            index=0,
        )
        summary_source = st.sidebar.selectbox(
            "Summary JSON (optional)",
            [None] + archive_candidates["summary"],
            format_func=lambda path: "(none)" if path is None else (str(path.relative_to(path.anchor)) if path.is_absolute() else str(path)),
            index=0,
        )
        return trajectory_source, detection_source, summary_source, archive_candidates

    trajectory_source = st.sidebar.file_uploader("Trajectory file", type=["geojson", "json", "csv"])
    detection_source = st.sidebar.file_uploader("Detection file", type=["geojson", "json", "csv"])
    summary_source = st.sidebar.file_uploader("Summary JSON", type=["json"])
    return trajectory_source, detection_source, summary_source, archive_candidates


def main() -> None:
    st.set_page_config(page_title="IntelSight Mission Explorer", page_icon="🗺️", layout="wide")
    if "--lab" in sys.argv:
        st.title("IntelSight Workshop Lab")
        render_workshop_lab()
        st.stop()
    st.title("IntelSight Mission Explorer")
    st.caption("Cross-platform mission review UI for selecting telemetry and detection files, then mapping detected objects in 2D and 3D.")

    workspace_files = discover_workspace_files()
    workspace_videos = discover_workspace_videos()
    overlay_videos = discover_overlay_videos()

    cached_missions_df = list_cached_missions(limit=200)
    source_modes = ["Workspace files", "Upload files", "Cached mission"]
    source_override = st.session_state.pop("source_mode_override", None)
    source_mode_index = source_modes.index(source_override) if source_override in source_modes else 0
    source_mode = st.sidebar.radio("Data source", source_modes, index=source_mode_index)
    trajectory_source: Any = None
    detection_source: Any = None
    summary_source: Any = None

    if source_mode == "Workspace files":
        trajectory_source, detection_source, summary_source = render_workspace_mode(workspace_files)
    elif source_mode == "Upload files":
        trajectory_source, detection_source, summary_source, _ = render_upload_mode()
        if trajectory_source is None or detection_source is None:
            st.info("Upload a trajectory file and a detection file to continue.")
            st.stop()
    else:
        if cached_missions_df.empty:
            st.warning("No cached missions available yet. Load workspace or uploaded files first.")
            st.stop()
        st.sidebar.subheader("Cached mission selector")
        mission_search = st.sidebar.text_input("Filter cached mission", value="")
        filtered_cache = cached_missions_df
        if mission_search.strip():
            token = mission_search.strip().lower()
            filtered_cache = cached_missions_df[
                cached_missions_df["trajectory_source"].astype(str).str.lower().str.contains(token, regex=False)
                | cached_missions_df["detection_source"].astype(str).str.lower().str.contains(token, regex=False)
                | cached_missions_df["cache_key"].astype(str).str.lower().str.contains(token, regex=False)
            ]
        if filtered_cache.empty:
            st.warning("No cached mission matches this filter.")
            st.stop()
        cache_override = st.session_state.pop("cache_key_override", None)
        cache_options = filtered_cache["cache_key"].tolist()
        cache_index = cache_options.index(cache_override) if cache_override in cache_options else 0
        selected_cache_key = st.sidebar.selectbox(
            "Cached mission",
            cache_options,
            format_func=lambda key: f"{key[:12]} | {filtered_cache.loc[filtered_cache['cache_key'] == key, 'trajectory_source'].iloc[0]}",
            index=cache_index,
        )
        cached_payload = get_cached_mission(selected_cache_key)
        try:
            cached_trajectory = _normalize_trajectory_frame(cached_payload.get("trajectory", pd.DataFrame()))
            cached_detections = _normalize_detection_frame(cached_payload.get("detections", pd.DataFrame()))
            trajectory_bundle = TrajectoryBundle(points=cached_trajectory, line=pd.DataFrame(), source_name=str(cached_payload.get("meta", {}).get("trajectory_source", "cached-trajectory")))
            detection_bundle = DetectionBundle(rows=with_object_ids(cached_detections), source_name=str(cached_payload.get("meta", {}).get("detection_source", "cached-detections")))
            summary_payload = cached_payload.get("summary", {})
            selected_video_hint = str(cached_payload.get("meta", {}).get("video_source", ""))
        except Exception as exc:  # pragma: no cover - Streamlit runtime guard
            st.error(f"Unable to restore cached mission: {exc}")
            st.stop()

    if source_mode != "Cached mission":
        try:
            trajectory_bundle = load_trajectory_bundle(trajectory_source)
            detection_bundle = load_detection_bundle(detection_source)
            summary_payload = load_summary_payload(summary_source)
        except Exception as exc:  # pragma: no cover - Streamlit runtime guard
            st.error(f"Unable to load the selected files: {exc}")
            st.stop()
        detection_bundle = DetectionBundle(rows=with_object_ids(detection_bundle.rows), source_name=detection_bundle.source_name)
        selected_video_hint = ""

    video_source_mode = st.sidebar.selectbox("Video source", ["overlay_preferred", "overlay_only", "raw_only"], index=0)
    raw_video_candidates = resolve_video_candidates(detection_bundle.rows, workspace_videos)
    overlay_candidates = resolve_overlay_candidates(detection_bundle.rows, overlay_videos)

    if video_source_mode == "overlay_only":
        video_candidates = overlay_candidates
    elif video_source_mode == "raw_only":
        video_candidates = raw_video_candidates
    else:
        video_candidates = overlay_candidates + [path for path in raw_video_candidates if path not in overlay_candidates]

    if selected_video_hint:
        hinted = [path for path in video_candidates if path.name == selected_video_hint or path.stem == Path(selected_video_hint).stem]
        if hinted:
            video_candidates = hinted + [path for path in video_candidates if path not in hinted]
    selected_video_source = None
    st.sidebar.subheader("Video")
    if video_candidates:
        selected_video_source = st.sidebar.selectbox(
            "Video file (optional)",
            [None] + video_candidates,
            format_func=lambda path: "(none)" if path is None else str(path.relative_to(WORKSPACE_ROOT)),
            index=0,
        )
        st.sidebar.caption("Overlay video is preferred when available. Playback is loaded only when selected.")
    else:
        st.sidebar.caption("No matching video was found for the selected mode.")

    persist_digest = st.sidebar.checkbox("Persist mission in SQLite", value=(source_mode != "Cached mission"))
    cache_result: dict[str, Any] = {}
    if persist_digest and source_mode != "Cached mission":
        try:
            cache_result = cache_mission_selection(
                trajectory_bundle,
                detection_bundle,
                summary_payload,
                {
                    "trajectory": source_label(trajectory_source),
                    "detections": source_label(detection_source),
                    "summary": source_label(summary_source) if summary_source is not None else "",
                    "video": source_label(selected_video_source) if selected_video_source is not None else "",
                },
            )
        except Exception as exc:  # pragma: no cover - Streamlit runtime guard
            st.warning(f"SQLite cache unavailable for this selection: {exc}")

    st.sidebar.subheader("Filters")
    min_confidence = st.sidebar.slider("Minimum fused confidence", min_value=0.0, max_value=1.0, value=0.0, step=0.05)
    vehicle_type_options = sorted([value for value in detection_bundle.rows["vehicle_type"].dropna().astype(str).unique().tolist() if value]) if not detection_bundle.rows.empty else []
    selected_vehicle_types = st.sidebar.multiselect("Vehicle types", vehicle_type_options, default=vehicle_type_options)
    review_options = sorted([value for value in detection_bundle.rows["review_status"].dropna().astype(str).unique().tolist() if value]) if not detection_bundle.rows.empty else []
    selected_review_modes = st.sidebar.multiselect("Review status", review_options, default=review_options)
    coordinate_mode = st.sidebar.selectbox("3D coordinate space", ["local_meters", "geodetic"], index=0)
    focus_on_detections = st.sidebar.checkbox("2D map centered on detections", value=True)

    filtered_detections = apply_filters(detection_bundle, min_confidence, selected_vehicle_types, selected_review_modes)

    selected_object_id: int | None = st.session_state.get("selected_object_id")
    available_ids = set(filtered_detections.rows.get("object_id", pd.Series(dtype="int64")).astype(int).tolist()) if not filtered_detections.rows.empty else set()
    if selected_object_id is not None and selected_object_id not in available_ids:
        selected_object_id = None
        st.session_state["selected_object_id"] = None

    st.sidebar.subheader("Object focus")
    object_options = [None] + sorted(available_ids)
    object_labels = {}
    if not filtered_detections.rows.empty:
        for row in filtered_detections.rows.itertuples(index=False):
            object_labels[int(row.object_id)] = object_display_name(pd.Series(row._asdict()))
    selected_object_id = st.sidebar.selectbox(
        "Focused object",
        object_options,
        index=(object_options.index(selected_object_id) if selected_object_id in object_options else 0),
        format_func=lambda object_id: "(none)" if object_id is None else object_labels.get(int(object_id), f"#{int(object_id)}"),
    )
    st.session_state["selected_object_id"] = selected_object_id
    selected_ids = {int(selected_object_id)} if selected_object_id is not None else set()

    st.subheader("Selected sources")
    cols = st.columns(2)
    cols[0].write(f"Trajectory: {trajectory_bundle.source_name}")
    cols[1].write(f"Detections: {detection_bundle.source_name}")
    if summary_source is not None:
        st.write(f"Summary: {_source_name(summary_source)}")
    if cache_result:
        st.caption(
            f"SQLite cache: {cache_result.get('cache_path', '')} | trajectory rows: {cache_result.get('trajectory_rows', 0):,} | detections: {cache_result.get('detection_rows', 0):,}"
        )

    make_summary_cards(trajectory_bundle, filtered_detections, summary_payload)
    if not filtered_detections.rows.empty:
        unique_geo_pairs = len(filtered_detections.rows[["latitude", "longitude"]].drop_duplicates())
        st.caption(f"Filtered geolocation diversity: {unique_geo_pairs:,} unique lat/lon pairs across {len(filtered_detections.rows):,} detections.")

    tab_2d, tab_3d, tab_table, tab_video, tab_db, tab_raw, tab_lab = st.tabs(["2D Map", "3D Map", "Objects", "Video", "Database", "Raw", "Workshop Lab"])

    with tab_2d:
        map_2d_state = st.plotly_chart(
            build_2d_figure(trajectory_bundle, filtered_detections, selected_ids, focus_on_detections=focus_on_detections),
            width="stretch",
            key="map2d",
            on_select="rerun",
            selection_mode=("points",),
        )
        selected_from_2d = _extract_selected_object_ids(map_2d_state)
        if len(selected_from_2d) == 1:
            st.session_state["selected_object_id"] = list(selected_from_2d)[0]
            selected_ids = set(selected_from_2d)

    with tab_3d:
        map_3d_state = st.plotly_chart(
            build_3d_figure(trajectory_bundle, filtered_detections, selected_ids, coordinate_mode=coordinate_mode),
            width="stretch",
            key="map3d",
            on_select="rerun",
            selection_mode=("points",),
        )
        selected_from_3d = _extract_selected_object_ids(map_3d_state)
        if len(selected_from_3d) == 1:
            st.session_state["selected_object_id"] = list(selected_from_3d)[0]
            selected_ids = set(selected_from_3d)

    with tab_table:
        if filtered_detections.rows.empty:
            st.info("No detections match the current filters.")
        else:
            table_columns = [
                column
                for column in [
                    "timestamp",
                    "plate_text",
                    "object_label",
                    "vehicle_type",
                    "vehicle_color",
                    "plate_resolved",
                    "fused_confidence",
                    "support_frames",
                    "geolocation_mode",
                    "geo_spread_m",
                    "proxy_ground_offset_m",
                    "review_status",
                    "display_latitude",
                    "display_longitude",
                    "drone_latitude",
                    "drone_longitude",
                    "latitude",
                    "longitude",
                    "altitude_m",
                    "source_file",
                ]
                if column in filtered_detections.rows.columns
            ]
            table_state = st.dataframe(
                filtered_detections.rows[table_columns],
                width="stretch",
                height=460,
                key="object_table",
                on_select="rerun",
                selection_mode="single-row",
            )
            selected_rows = _selected_rows_from_table_state(table_state)
            if selected_rows:
                row_pos = int(selected_rows[0])
                if 0 <= row_pos < len(filtered_detections.rows):
                    st.session_state["selected_object_id"] = int(filtered_detections.rows.iloc[row_pos]["object_id"])
                    selected_ids = {int(filtered_detections.rows.iloc[row_pos]["object_id"])}

            csv_bytes = filtered_detections.rows.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download filtered detections CSV",
                data=csv_bytes,
                file_name=f"{Path(filtered_detections.source_name).stem}.filtered.csv",
                mime="text/csv",
            )

    with tab_video:
        if selected_video_source is None:
            st.info("Choose a video in the sidebar to preview the mission clip on demand.")
        else:
            if st.button("Build all previews (1080p + 720p)", key=f"build_all_previews_{selected_video_source.name}"):
                outcomes: list[str] = []
                for variant in ["1080p", "720p"]:
                    started = time.perf_counter()
                    try:
                        built_path, status = get_video_for_playback(selected_video_source, variant)
                        elapsed = time.perf_counter() - started
                        outcomes.append(f"{variant}: {status}, {_human_size(built_path.stat().st_size)}, {elapsed:.1f}s")
                    except Exception as exc:  # pragma: no cover
                        outcomes.append(f"{variant}: failed ({exc})")
                for outcome in outcomes:
                    st.caption(outcome)

            playback_variant = st.selectbox("Playback resolution", ["original", "1080p", "720p"], index=1)
            fps = st.number_input("Video FPS for frame targeting", min_value=1.0, max_value=120.0, value=30.0, step=1.0)
            target_frame = None
            focused = pd.DataFrame()
            if st.session_state.get("selected_object_id") is not None and not filtered_detections.rows.empty:
                focused = filtered_detections.rows[filtered_detections.rows["object_id"] == int(st.session_state["selected_object_id"])]
                if not focused.empty:
                    if "frame_start" in focused.columns:
                        target_frame = int(focused.iloc[0]["frame_start"])
                    elif "frame" in focused.columns:
                        target_frame = int(focused.iloc[0]["frame"])

            playback_path = selected_video_source
            cache_status = "original"
            if playback_variant != "original":
                preview_target = _preview_output_path(selected_video_source, playback_variant)
                if preview_target.exists():
                    playback_path = preview_target
                    cache_status = "cached"
                elif st.button(f"Build {playback_variant} preview", key=f"build_preview_{playback_variant}_{selected_video_source.name}"):
                    started = time.perf_counter()
                    with st.spinner(f"Building {playback_variant} preview..."):
                        try:
                            playback_path, cache_status = get_video_for_playback(selected_video_source, playback_variant)
                            elapsed = time.perf_counter() - started
                            st.caption(f"Built in {elapsed:.1f}s, size {_human_size(playback_path.stat().st_size)}")
                        except Exception as exc:  # pragma: no cover
                            st.error(f"Unable to build preview: {exc}")
                            playback_path = selected_video_source
                            cache_status = "fallback_original"
                else:
                    st.info(f"Build a cached {playback_variant} preview for smoother playback on large files.")

            st.write(f"Video: {selected_video_source.relative_to(WORKSPACE_ROOT)}")
            if playback_path != selected_video_source:
                st.caption(f"Playback file: {playback_path.relative_to(WORKSPACE_ROOT)} ({cache_status})")
            start_time = int(target_frame / fps) if target_frame is not None else 0
            st.video(str(playback_path), start_time=start_time)
            if target_frame is not None and not focused.empty:
                st.caption(f"Focused object #{int(st.session_state['selected_object_id'])} at frame {target_frame} (start second {start_time}).")
                detail_columns = [column for column in ["timestamp", "plate_text", "vehicle_type", "vehicle_color", "fused_confidence", "support_frames", "review_status", "latitude", "longitude"] if column in focused.columns]
                st.dataframe(focused[detail_columns].head(1), width="stretch")
            if not detection_bundle.rows.empty and "video" in detection_bundle.rows.columns:
                matching = detection_bundle.rows[detection_bundle.rows["video"].astype(str).str.contains(selected_video_source.stem, na=False, regex=False)]
                if not matching.empty:
                    st.caption(f"Matching digested detections: {len(matching):,}")
                    preview_columns = [column for column in ["timestamp", "plate_text", "vehicle_type", "vehicle_color", "fused_confidence", "latitude", "longitude", "review_status"] if column in matching.columns]
                    st.dataframe(matching[preview_columns].head(50), width="stretch", height=320)

    with tab_db:
        st.subheader("SQLite mission digest")
        if cache_result:
            st.write(f"Cache key: {cache_result.get('cache_key', '')}")
        cached_missions = list_cached_missions()
        if cached_missions.empty:
            st.info("No cached missions yet. Enable persistence and load a mission selection.")
        else:
            st.dataframe(cached_missions, width="stretch", height=260)

            selected_cache = st.selectbox(
                "Load mission from digest",
                cached_missions["cache_key"].tolist(),
                format_func=lambda key: f"{key[:12]} | {cached_missions.loc[cached_missions['cache_key'] == key, 'trajectory_source'].iloc[0]}",
                index=0,
            )
            if st.button("Use selected cached mission"):
                st.session_state["source_mode_override"] = "Cached mission"
                st.session_state["cache_key_override"] = selected_cache
                st.rerun()

            if cache_result:
                cached_frames = load_mission_digest(cache_result.get("cache_key", ""))
                mission_row = cached_frames.get("mission_digest", pd.DataFrame())
                trajectory_rows = cached_frames.get("trajectory_points", pd.DataFrame())
                detection_rows = cached_frames.get("detection_observations", pd.DataFrame())
                if not mission_row.empty:
                    st.json(mission_row.iloc[0].to_dict())
                cols = st.columns(3)
                cols[0].metric("Cached trajectory rows", f"{len(trajectory_rows):,}")
                cols[1].metric("Cached detection rows", f"{len(detection_rows):,}")
                cols[2].metric("Cached missions", f"{len(cached_missions):,}")

    with tab_raw:
        if summary_payload:
            st.json(summary_payload)
        else:
            st.info("No summary JSON was loaded for this session.")
        if not trajectory_bundle.points.empty:
            st.write("Trajectory preview")
            st.dataframe(trajectory_bundle.points.head(25), width="stretch")
        if not detection_bundle.rows.empty:
            st.write("Detection preview")
            st.dataframe(detection_bundle.rows.head(25), width="stretch")

    with tab_lab:
        render_workshop_lab()


if __name__ == "__main__":
    main()