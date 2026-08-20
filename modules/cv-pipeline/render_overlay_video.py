from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import subprocess
from bisect import bisect_left
from pathlib import Path

import cv2
import numpy as np
import torch
from tqdm import tqdm


def resolve_device(device: str | None = None) -> str:
    """Resolve a runtime device string with a safe CPU fallback."""
    value = (device or "auto").strip().lower()
    if value in {"", "auto"}:
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    if value == "cpu":
        return "cpu"
    if value.startswith("cuda:"):
        return value if torch.cuda.is_available() else "cpu"
    try:
        idx = int(value)
    except ValueError:
        return "cpu"
    if torch.cuda.is_available() and idx >= 0 and idx < torch.cuda.device_count():
        return f"cuda:{idx}"
    return "cpu"


def build_video_writer(out_path: Path, width: int, height: int, fps: float):
    """Create a valid MP4 writer with a codec fallback chain to avoid corrupt files."""
    candidates = ["avc1", "H264", "mp4v"]
    for codec in candidates:
        writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*codec), fps, (width, height))
        if writer.isOpened():
            return writer

    if shutil.which("ffmpeg"):
        tmp_path = out_path.with_suffix(".tmp.mp4")
        if tmp_path.exists():
            tmp_path.unlink()
        cmd = [
            shutil.which("ffmpeg"),
            "-y",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "-",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(tmp_path),
        ]
        return {"ffmpeg": cmd, "temp_path": tmp_path}
    return None


def compute_optical_flow(prev_gray, curr_gray, roi=None, motion_scale=30.0, vector_step=12, device: str | None = None):
    """Prefer CUDA optical flow when available, otherwise fall back to the proven CPU Farneback implementation."""
    resolved_device = resolve_device(device)
    if roi is None:
        x1, y1, x2, y2 = 0, 0, prev_gray.shape[1], prev_gray.shape[0]
    else:
        if len(roi) != 4:
            raise ValueError("ROI must contain four values: x1, y1, x2, y2.")
        x1, y1, x2, y2 = [int(v) for v in roi]
        x1 = max(0, min(prev_gray.shape[1] - 1, x1))
        y1 = max(0, min(prev_gray.shape[0] - 1, y1))
        x2 = max(x1 + 1, min(prev_gray.shape[1], x2))
        y2 = max(y1 + 1, min(prev_gray.shape[0], y2))

    prev_roi = prev_gray[y1:y2, x1:x2]
    curr_roi = curr_gray[y1:y2, x1:x2]
    if prev_roi.size == 0 or curr_roi.size == 0:
        raise ValueError("The selected ROI does not contain valid image data.")

    if resolved_device.startswith("cuda") and hasattr(cv2, "cuda") and hasattr(cv2.cuda, "FarnebackOpticalFlow"):
        try:
            gpu_prev = cv2.cuda_GpuMat()
            gpu_curr = cv2.cuda_GpuMat()
            gpu_prev.upload(prev_roi)
            gpu_curr.upload(curr_roi)
            flow_builder = cv2.cuda_FarnebackOpticalFlow.create(5, 0.5, False, 15, 3, 5, 1.2, 0)
            flow_gpu = flow_builder.calc(gpu_prev, gpu_curr, None)
            flow = flow_gpu.download()
            return flow, resolved_device
        except Exception:
            pass

    flow = cv2.calcOpticalFlowFarneback(
        prev_roi,
        curr_roi,
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=15,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=cv2.OPTFLOW_FARNEBACK_GAUSSIAN,
    )
    return flow, resolved_device


def load_records(path: Path):
    records = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            records[int(rec.get("frame", -1))] = rec
    return records


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: object, default: int = -1) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def get_candidate_spatial_cells(center_xy: tuple[int, int] | list[int], radius_px: float, cell_size: int = 32) -> set[tuple[int, int]]:
    """Return the spatial grid cells that intersect a local search radius around a centroid.

    This is a lightweight OpenCV-native search primitive for ROI-first feature matching:
    use the predicted object center and current optical-flow offset to query only nearby
    descriptor buckets instead of brute-forcing the entire frame.
    """
    if cell_size <= 0:
        raise ValueError("cell_size must be positive")

    cx, cy = [int(v) for v in center_xy]
    min_x = max(0, int((cx - radius_px) // cell_size))
    max_x = int((cx + radius_px) // cell_size)
    min_y = max(0, int((cy - radius_px) // cell_size))
    max_y = int((cy + radius_px) // cell_size)
    return {(x, y) for x in range(min_x, max_x + 1) for y in range(min_y, max_y + 1)}


def build_spatial_feature_index(keypoints: list[cv2.KeyPoint], descriptors: np.ndarray | None, cell_size: int = 32) -> dict[tuple[int, int], list[dict[str, object]]]:
    """Group feature descriptors by image-space cell for fast local matching.

    Each cell contains a compact list of entries with the keypoint and descriptor so a
    downstream matcher can query only the nearby cells implied by the current motion ROI.
    """
    if cell_size <= 0:
        raise ValueError("cell_size must be positive")

    spatial_index: dict[tuple[int, int], list[dict[str, object]]] = {}
    if descriptors is None or len(descriptors) == 0:
        return spatial_index

    if len(keypoints) != len(descriptors):
        descriptor_count = len(descriptors)
        keypoint_count = len(keypoints)
        if keypoint_count > 0 and descriptor_count != keypoint_count:
            raise ValueError(f"Descriptor count mismatch: {descriptor_count} descriptors for {keypoint_count} keypoints")

    for idx, keypoint in enumerate(keypoints):
        if idx >= len(descriptors):
            break
        x, y = int(round(keypoint.pt[0])), int(round(keypoint.pt[1]))
        cell = (x // cell_size, y // cell_size)
        spatial_index.setdefault(cell, []).append({
            "index": idx,
            "x": x,
            "y": y,
            "keypoint": keypoint,
            "descriptor": descriptors[idx],
        })

    return spatial_index


def match_features_with_spatial_index(
    prev_keypoints: list[cv2.KeyPoint],
    prev_descriptors: np.ndarray,
    curr_keypoints: list[cv2.KeyPoint],
    curr_descriptors: np.ndarray,
    center_xy: tuple[int, int] | list[int] = (0, 0),
    radius_px: float = 64.0,
    cell_size: int = 32,
    max_matches: int = 40,
    ratio_test: float = 0.75,
) -> list:
    """Match features between previous and current frames using only spatially nearby current cells.

    This is a lightweight OpenCV-native baseline: descriptors in the candidate cells around the
    predicted vehicle centroid are matched, and all other image-space features are ignored.
    """
    if prev_descriptors is None or curr_descriptors is None:
        return []
    if len(prev_keypoints) == 0 or len(curr_keypoints) == 0:
        return []
    if len(prev_descriptors) == 0 or len(curr_descriptors) == 0:
        return []

    if len(prev_keypoints) != len(prev_descriptors) or len(curr_keypoints) != len(curr_descriptors):
        if len(prev_keypoints) > 0 and len(prev_descriptors) > 0 and len(prev_keypoints) != len(prev_descriptors):
            raise ValueError("Previous keypoint and descriptor counts must match.")
        if len(curr_keypoints) > 0 and len(curr_descriptors) > 0 and len(curr_keypoints) != len(curr_descriptors):
            raise ValueError("Current keypoint and descriptor counts must match.")

    curr_index = build_spatial_feature_index(curr_keypoints, curr_descriptors, cell_size=cell_size)
    candidate_cells = get_candidate_spatial_cells(center_xy, radius_px, cell_size=cell_size)
    candidate_entries: list[dict[str, object]] = []
    for cell in candidate_cells:
        candidate_entries.extend(curr_index.get(cell, []))

    if not candidate_entries:
        return []

    candidate_desc = np.stack([entry["descriptor"] for entry in candidate_entries], axis=0)
    if candidate_desc.ndim == 1:
        candidate_desc = candidate_desc.reshape(1, -1)

    if prev_descriptors.dtype.kind in {"f", "i", "u"}:
        norm_type = cv2.NORM_L2 if prev_descriptors.dtype.kind in {"f", "i"} else cv2.NORM_L2
        matcher = cv2.BFMatcher(norm_type)
        raw_matches = matcher.knnMatch(prev_descriptors.astype(np.float32), candidate_desc.astype(np.float32), k=2)
        good = []
        for match_pair in raw_matches:
            if len(match_pair) < 2:
                continue
            m, n = match_pair
            if m.distance < ratio_test * n.distance:
                good.append(m)
    else:
        norm_type = cv2.NORM_HAMMING
        matcher = cv2.BFMatcher(norm_type, crossCheck=False)
        raw_matches = matcher.knnMatch(prev_descriptors.astype(np.uint8), candidate_desc.astype(np.uint8), k=2)
        good = []
        for match_pair in raw_matches:
            if len(match_pair) < 2:
                continue
            m, n = match_pair
            if m.distance < ratio_test * n.distance:
                good.append(m)

    filtered_matches = []
    for match in good[:max_matches]:
        match_idx = match.trainIdx
        if 0 <= match_idx < len(candidate_entries):
            filtered_matches.append({
                "query_idx": match.queryIdx,
                "train_idx": match_idx,
                "distance": float(match.distance),
                "keypoint": candidate_entries[match_idx]["keypoint"],
                "candidate": candidate_entries[match_idx],
            })

    return filtered_matches


def load_frame_rows(path: Path | None) -> dict[int, list[dict[str, object]]]:
    rows_by_frame: dict[int, list[dict[str, object]]] = {}
    if path is None or not path.exists():
        return rows_by_frame

    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            frame = safe_int(row.get("frame"), -1)
            if frame < 0:
                continue
            rows_by_frame.setdefault(frame, []).append(row)
    return rows_by_frame


def load_telemetry(path: Path | None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if path is None or not path.exists():
        return rows

    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            frame = safe_int(row.get("frame"), -1)
            lat = safe_float(row.get("latitude"), 0.0)
            lon = safe_float(row.get("longitude"), 0.0)
            if frame < 0:
                continue
            rows.append(
                {
                    "frame": frame,
                    "latitude": lat,
                    "longitude": lon,
                    "rel_alt": safe_float(row.get("rel_alt"), 0.0),
                    "timestamp": str(row.get("timestamp", "")),
                }
            )

    rows.sort(key=lambda row: int(row["frame"]))
    return rows


def nearest_telemetry(frame_idx: int, telemetry_rows: list[dict[str, object]]) -> dict[str, object] | None:
    if not telemetry_rows:
        return None

    target = frame_idx + 1
    frame_ids = [int(row["frame"]) for row in telemetry_rows]
    pos = bisect_left(frame_ids, target)
    if pos == 0:
        return telemetry_rows[0]
    if pos >= len(telemetry_rows):
        return telemetry_rows[-1]

    before = telemetry_rows[pos - 1]
    after = telemetry_rows[pos]
    if abs(int(before["frame"]) - target) <= abs(int(after["frame"]) - target):
        return before
    return after


def normalize_xyxy(xyxy: object) -> list[int] | None:
    if not isinstance(xyxy, (list, tuple)) or len(xyxy) != 4:
        return None
    try:
        nums = [int(float(x)) for x in xyxy]
    except (TypeError, ValueError):
        return None
    x1, y1, x2, y2 = nums
    if not (x2 > x1 and y2 > y1 and x1 >= 0 and y1 >= 0):
        return None
    return [x1, y1, x2, y2]


def is_valid_xyxy(xyxy: object) -> bool:
    return normalize_xyxy(xyxy) is not None


def is_plate_like_box(xyxy: list[int] | tuple[int, int, int, int] | None, image_width: int, image_height: int) -> bool:
    """Return True only for plate-like boxes, excluding full-body vehicle regions."""
    if xyxy is None:
        return False
    normalized = normalize_xyxy(xyxy)
    if normalized is None:
        return False
    x1, y1, x2, y2 = normalized
    width = x2 - x1
    height = y2 - y1
    if width <= 0 or height <= 0:
        return False
    if width < 20 or height < 8:
        return False
    if x1 < 0 or y1 < 0 or x2 > image_width or y2 > image_height:
        return False
    aspect_ratio = width / max(1, height)
    area = width * height
    image_area = max(1, image_width * image_height)
    if aspect_ratio < 0.7 or aspect_ratio > 10.0:
        return False
    if area > 0.08 * image_area:
        return False
    return True


def suggest_flow_vector_step(image_width: int, image_height: int, target_cells: int = 160) -> int:
    """Use a sparse vector step for full-frame motion overlays so arrows remain readable."""
    longest_edge = max(1, max(image_width, image_height))
    step = max(8, int(round(longest_edge / max(1, int(np.sqrt(target_cells))))))
    return min(24, max(8, step))


def filter_valid_detections(record: dict[str, object] | None) -> dict[str, object]:
    if not record:
        return {"vehicle_boxes": [], "ocr": []}

    accepted = {
        "vehicle_boxes": [],
        "ocr": [],
    }
    image_width = safe_int(record.get("image_width"), 1920)
    image_height = safe_int(record.get("image_height"), 1080)
    for box in record.get("vehicle_boxes", []):
        if not isinstance(box, dict):
            continue
        normalized = normalize_xyxy(box.get("xyxy"))
        if normalized is None:
            continue
        box = dict(box)
        box["xyxy"] = normalized
        accepted["vehicle_boxes"].append(box)
    for ocr in record.get("ocr", []):
        if not isinstance(ocr, dict):
            continue
        normalized = normalize_xyxy(ocr.get("xyxy"))
        if normalized is None:
            continue
        plate_like = is_plate_like_box(normalized, image_width, image_height)
        text = str(ocr.get("ocr_text") or "").strip()
        conf = safe_float(ocr.get("ocr_conf"), 0.0)
        plate_conf = safe_float(ocr.get("plate_conf"), conf)
        if plate_like and (text or conf > 0.08 or plate_conf > 0.15):
            ocr = dict(ocr)
            ocr["xyxy"] = normalized
            accepted["ocr"].append(ocr)
    return accepted


def choose_flow_roi_for_frame(
    frame_shape: tuple[int, int],
    candidate_boxes: list[list[int] | tuple[int, int, int, int]],
    fallback_roi: tuple[int, int, int, int] | None = None,
    padding: int = 32,
    min_edge_margin_ratio: float = 0.12,
) -> tuple[int, int, int, int]:
    height, width = frame_shape[:2]
    min_x_margin = max(0, int(width * min_edge_margin_ratio))
    min_y_margin = max(0, int(height * min_edge_margin_ratio))

    def score(box: tuple[int, int, int, int]) -> tuple[float, float, float]:
        x1, y1, x2, y2 = box
        area = max(1, (x2 - x1) * (y2 - y1))
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        center_distance = abs(cx - width / 2.0) + abs(cy - height / 2.0)
        return (-center_distance, float(area), -abs(x1 - min_x_margin) - abs(y1 - min_y_margin))

    if not candidate_boxes:
        return fallback_roi if fallback_roi is not None else (0, 0, width, height)

    normalized = []
    for box in candidate_boxes:
        xyxy = normalize_xyxy(box)
        if xyxy is None:
            continue
        x1, y1, x2, y2 = xyxy
        x1 = max(min_x_margin, min(width - 1, x1))
        y1 = max(min_y_margin, min(height - 1, y1))
        x2 = max(x1 + 1, min(width, x2))
        y2 = max(y1 + 1, min(height, y2))
        if x1 < min_x_margin or y1 < min_y_margin or x2 > width - min_x_margin or y2 > height - min_y_margin:
            x1 = max(min_x_margin, x1)
            y1 = max(min_y_margin, y1)
            x2 = min(width - min_x_margin, x2)
            y2 = min(height - min_y_margin, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        normalized.append((x1, y1, x2, y2))

    if not normalized:
        return fallback_roi if fallback_roi is not None else (0, 0, width, height)

    chosen = max(normalized, key=score)
    x1, y1, x2, y2 = chosen
    x1 = max(min_x_margin, x1 - padding)
    y1 = max(min_y_margin, y1 - padding)
    x2 = min(width - min_x_margin, x2 + padding)
    y2 = min(height - min_y_margin, y2 + padding)
    return (int(x1), int(y1), int(x2), int(y2))


def resolve_active_detection(frame_idx: int, recs: dict[int, dict[str, object]], fallback: dict[str, object] | None) -> dict[str, object] | None:
    if frame_idx in recs and recs[frame_idx]:
        return recs[frame_idx]
    if fallback is not None:
        return fallback
    return None


def estimate_optical_flow_kinematics(
    previous_frame: np.ndarray,
    current_frame: np.ndarray,
    roi: tuple[int, int, int, int] | list[int] | None = None,
    motion_scale: float = 30.0,
    vector_step: int = 8,
    altitude_m: float = 35.0,
    horizontal_fov_deg: float = 78.0,
    vertical_fov_deg: float = 60.0,
    device: str | None = "auto",
) -> dict[str, float | tuple[float, float] | tuple[float, float, float] | tuple[int, int, int, int] | None]:
    """Derive scene-level displacement and rotational cues from dense optical flow in a 3D-style world proxy."""
    if previous_frame is None or current_frame is None:
        raise ValueError("Both frames must be valid OpenCV arrays.")

    prev_gray = cv2.cvtColor(previous_frame, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)

    if roi is None:
        x1, y1, x2, y2 = 0, 0, prev_gray.shape[1], prev_gray.shape[0]
    else:
        if len(roi) != 4:
            raise ValueError("ROI must contain four values: x1, y1, x2, y2.")
        x1, y1, x2, y2 = [int(v) for v in roi]
        x1 = max(0, min(prev_gray.shape[1] - 1, x1))
        y1 = max(0, min(prev_gray.shape[0] - 1, y1))
        x2 = max(x1 + 1, min(prev_gray.shape[1], x2))
        y2 = max(y1 + 1, min(prev_gray.shape[0], y2))

    prev_roi = prev_gray[y1:y2, x1:x2]
    curr_roi = curr_gray[y1:y2, x1:x2]
    if prev_roi.size == 0 or curr_roi.size == 0:
        raise ValueError("The selected ROI does not contain valid image data.")

    flow, _ = compute_optical_flow(prev_gray, curr_gray, roi=(x1, y1, x2, y2), motion_scale=motion_scale, vector_step=vector_step, device=device)
    flow_x = flow[..., 0]
    flow_y = flow[..., 1]
    motion_mag, _ = cv2.cartToPolar(flow_x, flow_y)

    mean_dx = float(np.mean(flow_x))
    mean_dy = float(np.mean(flow_y))
    translation_vector_px = (mean_dx, mean_dy)
    translation_px = float(np.hypot(mean_dx, mean_dy))
    mean_speed_px = float(np.mean(motion_mag))

    image_w = max(1, x2 - x1)
    image_h = max(1, y2 - y1)
    alt = max(1.0, float(altitude_m))
    hfov_rad = np.deg2rad(float(horizontal_fov_deg))
    vfov_rad = np.deg2rad(float(vertical_fov_deg))
    half_width_m = alt * np.tan(hfov_rad / 2.0)
    half_height_m = alt * np.tan(vfov_rad / 2.0)

    east_m = (mean_dx / max(1.0, image_w)) * (2.0 * half_width_m)
    north_m = (mean_dy / max(1.0, image_h)) * (2.0 * half_height_m)
    vertical_proxy_m = max(0.0, mean_speed_px * 0.08)
    translation_vector_m = (float(east_m), float(north_m), float(vertical_proxy_m))
    translation_m = float(np.hypot(east_m, north_m) + vertical_proxy_m)

    yy, xx = np.indices(flow_x.shape, dtype=np.float32)
    center_y = (flow_x.shape[0] - 1) / 2.0
    center_x = (flow_x.shape[1] - 1) / 2.0
    rel_x = xx - center_x
    rel_y = yy - center_y
    angular_momentum = np.sum(rel_x * flow_y - rel_y * flow_x)
    total_motion = float(np.sum(motion_mag))
    rotation_proxy_deg = float(np.clip(abs(angular_momentum) / max(total_motion, 1e-6) * 120.0, 0.0, 180.0))

    return {
        "translation_vector_px": translation_vector_px,
        "translation_px": translation_px,
        "translation_vector_m": translation_vector_m,
        "translation_m": translation_m,
        "mean_speed_px": mean_speed_px,
        "rotation_proxy_deg": rotation_proxy_deg,
        "active_ratio": float(np.mean(motion_mag > (float(motion_scale) * 0.15))),
        "roi": (x1, y1, x2, y2),
    }


def render_motion_heatmap_overlay(
    previous_frame: np.ndarray,
    current_frame: np.ndarray,
    roi: tuple[int, int, int, int] | list[int] | None = None,
    motion_scale: float = 30.0,
    vector_step: int = 12,
    alpha: float = 0.12,
    arrow_scale: float = 5.5,
    arrow_thickness: int = 3,
    device: str | None = "auto",
) -> tuple[np.ndarray, dict[str, float | tuple[int, int, int, int] | None]]:
    """Render Farneback optical-flow motion as a heatmap overlay within an optional ROI."""
    if previous_frame is None or current_frame is None:
        raise ValueError("Both frames must be valid OpenCV arrays.")

    prev_gray = cv2.cvtColor(previous_frame, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)

    if roi is None:
        x1, y1, x2, y2 = 0, 0, prev_gray.shape[1], prev_gray.shape[0]
    else:
        if len(roi) != 4:
            raise ValueError("ROI must contain four values: x1, y1, x2, y2.")
        x1, y1, x2, y2 = [int(v) for v in roi]
        x1 = max(0, min(prev_gray.shape[1] - 1, x1))
        y1 = max(0, min(prev_gray.shape[0] - 1, y1))
        x2 = max(x1 + 1, min(prev_gray.shape[1], x2))
        y2 = max(y1 + 1, min(prev_gray.shape[0], y2))

    prev_roi = prev_gray[y1:y2, x1:x2]
    curr_roi = curr_gray[y1:y2, x1:x2]
    if prev_roi.size == 0 or curr_roi.size == 0:
        raise ValueError("The selected ROI does not contain valid image data.")

    flow, _ = compute_optical_flow(prev_gray, curr_gray, roi=(x1, y1, x2, y2), motion_scale=motion_scale, vector_step=vector_step, device=device)
    flow_x = flow[..., 0]
    flow_y = flow[..., 1]
    motion_magnitude, _ = cv2.cartToPolar(flow_x, flow_y)

    normalized = np.clip((motion_magnitude / max(1e-6, float(motion_scale))) * 255.0, 0, 255).astype(np.uint8)
    heatmap = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)

    overlay = current_frame.copy()
    if roi is not None:
        roi_patch = overlay[y1:y2, x1:x2]
        overlay[y1:y2, x1:x2] = cv2.addWeighted(roi_patch, 1.0, heatmap, min(alpha, 0.08), 0)
        cv2.rectangle(overlay, (x1, y1), (x2 - 1, y2 - 1), (0, 255, 255), 2)
    else:
        overlay = cv2.addWeighted(overlay, 1.0, heatmap, min(alpha, 0.06), 0)

    step_size = max(1, int(vector_step))
    for yy in range(0, flow_x.shape[0], step_size):
        for xx in range(0, flow_x.shape[1], step_size):
            dx = float(flow_x[yy, xx])
            dy = float(flow_y[yy, xx])
            speed = float(np.hypot(dx, dy))
            if speed < 0.8:
                continue

            start_x = xx + x1
            start_y = yy + y1
            end_x = int(start_x + dx * (arrow_scale * 1.5))
            end_y = int(start_y + dy * (arrow_scale * 1.5))
            end_x = max(0, min(overlay.shape[1] - 1, end_x))
            end_y = max(0, min(overlay.shape[0] - 1, end_y))

            color = (0, 255, 0) if speed > 2.5 else (0, 200, 255)
            cv2.arrowedLine(overlay, (start_x, start_y), (end_x, end_y), color, max(1, arrow_thickness - 1), cv2.LINE_AA, tipLength=0.7)
            cv2.circle(overlay, (start_x, start_y), max(2, arrow_thickness), color, -1)

    kinematics = estimate_optical_flow_kinematics(previous_frame, current_frame, roi=roi, motion_scale=motion_scale, vector_step=vector_step, device=device)
    center_x = (x1 + x2) // 2
    center_y = (y1 + y2) // 2
    mean_dx, mean_dy = kinematics["translation_vector_px"]
    arrow_end_x = int(center_x + mean_dx * arrow_scale)
    arrow_end_y = int(center_y + mean_dy * arrow_scale)
    arrow_end_x = max(0, min(overlay.shape[1] - 1, arrow_end_x))
    arrow_end_y = max(0, min(overlay.shape[0] - 1, arrow_end_y))
    cv2.arrowedLine(overlay, (center_x, center_y), (arrow_end_x, arrow_end_y), (255, 255, 255), arrow_thickness, cv2.LINE_AA, tipLength=0.6)
    cv2.putText(
        overlay,
        f"Δ={kinematics['translation_px']:.1f}px  rot={kinematics['rotation_proxy_deg']:.1f}°",
        (max(10, x1 + 12), max(28, y1 + 28)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )

    summary = {
        "mean_motion_px": float(np.mean(motion_magnitude)),
        "max_motion_px": float(np.max(motion_magnitude)),
        "active_ratio": float(np.mean(motion_magnitude > (float(motion_scale) * 0.15))),
        "translation_px": float(kinematics["translation_px"]),
        "translation_vector_px": tuple(float(v) for v in kinematics["translation_vector_px"]),
        "translation_vector_m": tuple(float(v) for v in kinematics["translation_vector_m"]),
        "translation_m": float(kinematics["translation_m"]),
        "rotation_proxy_deg": float(kinematics["rotation_proxy_deg"]),
        "mean_speed_px": float(kinematics["mean_speed_px"]),
        "roi": (x1, y1, x2, y2),
    }
    return overlay, summary


def render_optical_flow(
    prev_frame: np.ndarray,
    curr_frame: np.ndarray,
    box: list[int] | tuple[int, int, int, int] | None = None,
    motion_scale: float = 30.0,
    alpha: float = 0.55,
    vector_step: int = 12,
) -> tuple[np.ndarray, dict[str, float | list[int] | tuple[int, int, int, int] | None]]:
    """Compatibility wrapper matching the notebook naming used in the CV lab."""
    return render_motion_heatmap_overlay(
        prev_frame,
        curr_frame,
        roi=tuple(box) if box is not None else None,
        motion_scale=motion_scale,
        vector_step=vector_step,
        alpha=alpha,
    )


def draw_panel(frame, x: int, y: int, width: int, height: int, alpha: float = 0.65) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + width, y + height), (14, 14, 18), -1)
    cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
    cv2.rectangle(frame, (x, y), (x + width, y + height), (90, 90, 90), 1)


def draw_text_lines(frame, lines: list[str], x: int, y: int, color=(255, 255, 255), scale: float = 0.5) -> None:
    line_gap = int(22 * max(scale, 0.5))
    for idx, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (x, y + idx * line_gap),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color,
            1,
            cv2.LINE_AA,
        )


def project_point(lon: float, lat: float, bounds: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int]:
    min_lon, max_lon, min_lat, max_lat = bounds
    lon_span = max(max_lon - min_lon, 1e-9)
    lat_span = max(max_lat - min_lat, 1e-9)
    px = int(((lon - min_lon) / lon_span) * max(width - 1, 1))
    py = int((1.0 - ((lat - min_lat) / lat_span)) * max(height - 1, 1))
    return px, py


def compute_bounds(telemetry_rows: list[dict[str, object]], localized_rows: dict[int, list[dict[str, object]]]) -> tuple[float, float, float, float] | None:
    coords: list[tuple[float, float]] = []
    for row in telemetry_rows:
        coords.append((safe_float(row.get("longitude")), safe_float(row.get("latitude"))))
    for rows in localized_rows.values():
        for row in rows:
            coords.append((safe_float(row.get("longitude")), safe_float(row.get("latitude"))))

    if not coords:
        return None

    lons = [lon for lon, _ in coords]
    lats = [lat for _, lat in coords]
    min_lon = min(lons)
    max_lon = max(lons)
    min_lat = min(lats)
    max_lat = max(lats)
    lon_pad = max((max_lon - min_lon) * 0.08, 1e-5)
    lat_pad = max((max_lat - min_lat) * 0.08, 1e-5)
    return (min_lon - lon_pad, max_lon + lon_pad, min_lat - lat_pad, max_lat + lat_pad)


def draw_map_inset(
    frame,
    telemetry_rows: list[dict[str, object]],
    current_telemetry: dict[str, object] | None,
    observation_history: list[dict[str, object]],
    bounds: tuple[float, float, float, float] | None,
) -> None:
    if not telemetry_rows or current_telemetry is None or bounds is None:
        return

    frame_h, frame_w = frame.shape[:2]
    panel_w = min(360, max(240, frame_w // 3))
    panel_h = min(220, max(180, frame_h // 4))
    margin = 14
    x0 = frame_w - panel_w - margin
    y0 = margin
    draw_panel(frame, x0, y0, panel_w, panel_h)

    inner_x = x0 + 12
    inner_y = y0 + 28
    inner_w = panel_w - 24
    inner_h = panel_h - 40
    cv2.rectangle(frame, (inner_x, inner_y), (inner_x + inner_w, inner_y + inner_h), (42, 42, 42), 1)
    cv2.putText(frame, "Map Relay", (x0 + 12, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    path_points = []
    current_frame = safe_int(current_telemetry.get("frame"), -1)
    for row in telemetry_rows:
        pt = project_point(
            safe_float(row.get("longitude")),
            safe_float(row.get("latitude")),
            bounds,
            inner_w,
            inner_h,
        )
        path_points.append((inner_x + pt[0], inner_y + pt[1], safe_int(row.get("frame"), -1)))

    if len(path_points) >= 2:
        all_points = [(px, py) for px, py, _ in path_points]
        all_points_array = np.array([all_points], dtype=np.int32)
        cv2.polylines(frame, [all_points_array], False, (100, 100, 100), 1)

    past_points = [(px, py) for px, py, telem_frame in path_points if telem_frame <= current_frame]
    if len(past_points) >= 2:
        past_array = np.array([past_points], dtype=np.int32)
        cv2.polylines(frame, [past_array], False, (255, 200, 80), 2)

    for obs in observation_history[-20:]:
        ox, oy = project_point(
            safe_float(obs.get("longitude")),
            safe_float(obs.get("latitude")),
            bounds,
            inner_w,
            inner_h,
        )
        color = (60, 220, 80) if safe_float(obs.get("plate_ocr_conf"), 0.0) >= 0.75 else (60, 120, 255)
        cv2.circle(frame, (inner_x + ox, inner_y + oy), 3, color, -1)

    drone_x, drone_y = project_point(
        safe_float(current_telemetry.get("longitude")),
        safe_float(current_telemetry.get("latitude")),
        bounds,
        inner_w,
        inner_h,
    )
    cv2.circle(frame, (inner_x + drone_x, inner_y + drone_y), 6, (0, 140, 255), -1)
    cv2.circle(frame, (inner_x + drone_x, inner_y + drone_y), 9, (255, 255, 255), 1)


def compute_dev_snip_frame_range(
    total_frames: int,
    fps: float,
    start_offset_seconds: float = 20.0,
    duration_seconds: float = 30.0,
) -> tuple[int, int | None]:
    if fps <= 0 or duration_seconds <= 0:
        return 0, None

    start_frame = max(0, int(round(start_offset_seconds * fps)))
    end_frame = start_frame + max(1, int(round(duration_seconds * fps)))
    if total_frames > 0:
        start_frame = min(start_frame, total_frames)
        end_frame = min(end_frame, total_frames)
    return start_frame, end_frame if end_frame > start_frame else None


def render(
    video_path: Path,
    detections_jsonl: Path,
    out_path: Path,
    frame_step: int = 1,
    srt_csv: Path | None = None,
    geotagged_csv: Path | None = None,
    flow_smoothing_window: int = 12,
    flow_roi_padding: int = 48,
    verbose: bool = True,
    dev_clip: bool = False,
    dev_start_offset_seconds: float = 20.0,
    dev_duration_seconds: float = 30.0,
    motion_alpha: float = 0.12,
    motion_arrow_scale: float = 5.5,
    motion_arrow_thickness: int = 3,
    device: str | None = "auto",
    preview: bool = False,
    preview_window_name: str = "IntelSight Overlay Preview",
):
    logger = logging.getLogger("intelsight.overlay")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO if verbose else logging.WARNING)

    recs = load_records(detections_jsonl)
    telemetry_rows = load_telemetry(srt_csv)
    localized_rows = load_frame_rows(geotagged_csv)
    map_bounds = compute_bounds(telemetry_rows, localized_rows)
    logger.info("Rendering overlay for %s", video_path)
    logger.info("Detections: %s | Telemetry: %s | Localized: %s", detections_jsonl, bool(srt_csv), bool(geotagged_csv))

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"unable to open video: {video_path}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    start_frame_idx = 0
    end_frame_idx = None
    if dev_clip:
        start_frame_idx, end_frame_idx = compute_dev_snip_frame_range(
            total_frames,
            float(source_fps),
            start_offset_seconds=dev_start_offset_seconds,
            duration_seconds=dev_duration_seconds,
        )
        logger.info("Development clip selected: start_frame=%d end_frame=%s duration_sec=%.1f", start_frame_idx, end_frame_idx, dev_duration_seconds)
        if start_frame_idx > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame_idx)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = build_video_writer(out_path, width, height, source_fps)
    if writer is None:
        cap.release()
        raise RuntimeError(f"unable to create video writer for output: {out_path}")

    preview_active = bool(preview)
    if preview_active:
        cv2.namedWindow(preview_window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(preview_window_name, min(1600, max(960, width // 2)), min(1000, max(540, height // 2)))

    ffmpeg_writer = isinstance(writer, dict)
    if ffmpeg_writer:
        ffmpeg_cmd = writer["ffmpeg"]
        tmp_path = writer["temp_path"]
        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
        writer = proc
    else:
        proc = None
        tmp_path = None

    try:
        progress_total = total_frames if total_frames > 0 else None
        if dev_clip and end_frame_idx is not None and total_frames > 0:
            progress_total = max(1, end_frame_idx - start_frame_idx)

        progress = None
        if verbose:
            progress = tqdm(
                total=progress_total,
                unit="frame",
                desc=f"Overlay {video_path.name}",
                leave=True,
                dynamic_ncols=True,
            )

        idx = start_frame_idx
        active_rec: dict[str, object] | None = None
        observation_history: dict[str, dict[str, object]] = {}
        previous_raw_frame: np.ndarray | None = None
        motion_buffer: list[np.ndarray] = []
        motion_window = max(2, int(flow_smoothing_window))

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx < start_frame_idx:
                idx += 1
                continue
            if end_frame_idx is not None and idx >= end_frame_idx:
                break

            rec = recs.get(idx)
            if rec is not None:
                clean = filter_valid_detections(rec)
                if clean["vehicle_boxes"] or clean["ocr"]:
                    if frame_step <= 1 or idx % frame_step == 0:
                        active_rec = {
                            "vehicle_boxes": clean["vehicle_boxes"],
                            "ocr": clean["ocr"],
                        }
            elif active_rec is None:
                active_rec = None

            if frame_step > 1 and idx % frame_step != 0 and active_rec is None:
                idx += 1
                continue

            frame_localizations = localized_rows.get(idx, [])
            for localized in frame_localizations:
                history_key = "|".join(
                    [
                        str(localized.get("plate_text") or localized.get("vehicle_type") or "obj"),
                        f"{safe_float(localized.get('latitude')):.5f}",
                        f"{safe_float(localized.get('longitude')):.5f}",
                    ]
                )
                observation_history[history_key] = localized

            current_telemetry = nearest_telemetry(idx, telemetry_rows)

            if previous_raw_frame is not None and previous_raw_frame.size:
                try:
                    rec_for_roi = rec if rec is not None else active_rec
                    roi_candidates = []
                    if isinstance(rec_for_roi, dict):
                        for item in rec_for_roi.get("vehicle_boxes", []) or []:
                            xyxy = normalize_xyxy(item.get("xyxy"))
                            if xyxy is not None:
                                roi_candidates.append(xyxy)
                    if roi_candidates:
                        roi = choose_flow_roi_for_frame(
                            frame.shape[:2],
                            roi_candidates,
                            fallback_roi=(0, 0, frame.shape[1], frame.shape[0]),
                            padding=flow_roi_padding,
                        )
                    else:
                        roi = (0, 0, frame.shape[1], frame.shape[0])

                    motion_buffer.append(frame.copy())
                    if len(motion_buffer) > motion_window:
                        motion_buffer.pop(0)
                    if len(motion_buffer) >= 2:
                        prev_motion = motion_buffer[-2]
                        curr_motion = motion_buffer[-1]
                        prev_for_flow = cv2.GaussianBlur(prev_motion, (5, 5), 1.5)
                        curr_for_flow = cv2.GaussianBlur(curr_motion, (5, 5), 1.5)
                        vector_step = suggest_flow_vector_step(frame.shape[1], frame.shape[0])
                        # Keep the source frame crisp for the final output while only using
                        # smoothed copies for optical-flow estimation, otherwise the overlay
                        # itself becomes blurrier than the original 1080p footage.
                        motion_overlay, _ = render_motion_heatmap_overlay(
                            prev_for_flow,
                            curr_for_flow,
                            roi=roi,
                            motion_scale=30.0,
                            vector_step=vector_step,
                            alpha=motion_alpha,
                            arrow_scale=motion_arrow_scale,
                            arrow_thickness=motion_arrow_thickness,
                            device=device,
                        )
                        frame = cv2.addWeighted(frame, 1.0, motion_overlay, 0.08, 0)
                except Exception:
                    pass

            if active_rec:
                overlay = frame.copy()
                for v in active_rec.get("vehicle_boxes", []):
                    xyxy = normalize_xyxy(v.get("xyxy"))
                    if xyxy is None:
                        continue
                    x1, y1, x2, y2 = xyxy
                    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 180, 180), -1)
                for o in active_rec.get("ocr", []):
                    xyxy = normalize_xyxy(o.get("xyxy"))
                    if xyxy is None:
                        continue
                    x1, y1, x2, y2 = xyxy
                    cv2.rectangle(overlay, (x1, y1), (x2, y2), (50, 170, 50), -1)
                cv2.addWeighted(overlay, 0.06, frame, 0.94, 0, frame)

                for v in active_rec.get("vehicle_boxes", []):
                    xyxy = normalize_xyxy(v.get("xyxy"))
                    if xyxy is None:
                        continue
                    x1, y1, x2, y2 = xyxy
                    label = f"{v.get('class_name','veh')} {v.get('color','unknown')} {v.get('conf',0):.2f}"
                    depth = safe_float(v.get('depth_proxy_m'), 0.0)
                    flow = safe_float(v.get('flow_magnitude'), 0.0)
                    label += f" depth={depth:.2f}m flow={flow:.1f}px"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
                    cv2.putText(frame, label, (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)

                for det_idx, o in enumerate(active_rec.get("ocr", [])):
                    xyxy = normalize_xyxy(o.get("xyxy"))
                    if xyxy is None:
                        continue
                    x1, y1, x2, y2 = xyxy
                    label = f"{o.get('ocr_text','')} ({o.get('ocr_conf',0):.2f})"
                    if det_idx < len(frame_localizations):
                        localized = frame_localizations[det_idx]
                        label += f" @ {safe_float(localized.get('latitude')):.5f},{safe_float(localized.get('longitude')):.5f}"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, label, (x1, max(0, y1 - 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)

            draw_panel(frame, 14, 14, min(520, width - 28), 108)
            hud_lines = [
                f"Frame {idx}  Vehicles={len(active_rec.get('vehicle_boxes', [])) if active_rec else 0}  Plates={len(active_rec.get('ocr', [])) if active_rec else 0}  Localized={len(frame_localizations)}",
            ]
            if current_telemetry is not None:
                hud_lines.extend(
                    [
                        f"Drone Lat/Lon {safe_float(current_telemetry.get('latitude')):.6f}, {safe_float(current_telemetry.get('longitude')):.6f}",
                        f"Rel Alt {safe_float(current_telemetry.get('rel_alt')):.1f} m  SRT Frame {safe_int(current_telemetry.get('frame'), 0)}",
                        f"Timestamp {str(current_telemetry.get('timestamp', ''))}",
                    ]
                )
            else:
                hud_lines.append("Telemetry unavailable for current frame")
            draw_text_lines(frame, hud_lines, 24, 38, scale=0.58)

            if frame_localizations:
                panel_height = min(120 + len(frame_localizations[:3]) * 22, max(120, height // 3))
                draw_panel(frame, 14, height - panel_height - 14, min(620, width - 28), panel_height)
                lines = ["Localized objects"]
                for localized in frame_localizations[:3]:
                    lines.append(
                        f"{localized.get('plate_text', '') or 'plate?'} {localized.get('vehicle_type', 'unknown')} {localized.get('vehicle_color', 'unknown')}"
                    )
                    lines.append(
                        f"  {safe_float(localized.get('latitude')):.6f}, {safe_float(localized.get('longitude')):.6f} alt {safe_float(localized.get('rel_alt')):.1f}m"
                    )
                draw_text_lines(frame, lines, 24, height - panel_height + 16, scale=0.55)

            draw_map_inset(
                frame,
                telemetry_rows,
                current_telemetry,
                list(observation_history.values()),
                map_bounds,
            )

            if ffmpeg_writer:
                proc.stdin.write(frame.tobytes())
            else:
                writer.write(frame)

            if preview_active:
                cv2.imshow(preview_window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q"), ord("Q")):
                    logger.info("Preview interrupted by user; exiting without finishing the full render.")
                    break
                if key in (ord("s"), ord("S")):
                    logger.info("Preview save requested; current render is being kept at %s", out_path)
                    try:
                        if ffmpeg_writer and proc is not None:
                            proc.stdin.flush()
                        elif writer is not None and hasattr(writer, "release"):
                            writer.release()
                            writer = build_video_writer(out_path, width, height, source_fps)
                            if writer is None:
                                raise RuntimeError(f"failed to reopen writer for save at {out_path}")
                            if isinstance(writer, dict):
                                proc = subprocess.Popen(writer["ffmpeg"], stdin=subprocess.PIPE)
                                ffmpeg_writer = True
                            else:
                                proc = None
                                ffmpeg_writer = False
                    except Exception as exc:
                        logger.warning("Preview save request failed: %s", exc)

            previous_raw_frame = frame.copy()
            if progress is not None:
                progress.update(1)
            idx += 1

        if progress is not None:
            progress.close()
    finally:
        if preview_active:
            cv2.destroyAllWindows()
        if proc is not None:
            proc.stdin.close()
            proc.wait(timeout=30)
            if tmp_path and tmp_path.exists() and not out_path.exists():
                tmp_path.replace(out_path)
        else:
            writer.release()
        cap.release()
        logger.info("Completed overlay render: %s (%d frames)", out_path, idx)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render step-by-step overlay video")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--detections", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument("--srt-csv", type=Path)
    parser.add_argument("--geotagged-csv", type=Path)
    parser.add_argument("--flow-smoothing-window", type=int, default=12)
    parser.add_argument("--flow-roi-padding", type=int, default=48)
    parser.add_argument("--motion-alpha", type=float, default=0.12, help="opacity of the motion heatmap overlay; lower values preserve sharper original image detail")
    parser.add_argument("--motion-arrow-scale", type=float, default=5.5, help="multiplier for the visible optical-flow arrow length")
    parser.add_argument("--motion-arrow-thickness", type=int, default=3, help="line thickness for optial-flow arrows")
    parser.add_argument("--device", type=str, default="auto", help="compute device: auto, cpu, or cuda:N")
    parser.add_argument("--preview", action="store_true", help="show a live OpenCV preview window; press S to keep the current render and Q/Esc to exit early")
    parser.add_argument("--preview-window-name", type=str, default="IntelSight Overlay Preview", help="window title for the live preview")
    parser.add_argument("--dev-clip", action="store_true", help="render a short development clip using the default 30s sample starting 20s into the video")
    parser.add_argument("--dev-start-offset-seconds", type=float, default=20.0, help="start offset in seconds for the development clip")
    parser.add_argument("--dev-duration-seconds", type=float, default=30.0, help="duration in seconds for the development clip")
    parser.add_argument("--verbose", action="store_true", default=True, help="display progress and render status")
    parser.add_argument("--quiet", action="store_false", dest="verbose", help="suppress progress output")
    args = parser.parse_args()

    render(
        args.video,
        args.detections,
        args.output,
        args.frame_step,
        args.srt_csv,
        args.geotagged_csv,
        flow_smoothing_window=args.flow_smoothing_window,
        flow_roi_padding=args.flow_roi_padding,
        verbose=args.verbose,
        dev_clip=args.dev_clip,
        dev_start_offset_seconds=args.dev_start_offset_seconds,
        dev_duration_seconds=args.dev_duration_seconds,
        motion_alpha=args.motion_alpha,
        motion_arrow_scale=args.motion_arrow_scale,
        motion_arrow_thickness=args.motion_arrow_thickness,
        device=args.device,
        preview=args.preview,
        preview_window_name=args.preview_window_name,
    )
    print(f"overlay={args.output}")


if __name__ == "__main__":
    main()
