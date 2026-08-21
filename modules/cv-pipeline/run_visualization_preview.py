from __future__ import annotations

import argparse
import json
import math
import sqlite3
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ultralytics import YOLO

from spatial_feature_matching import MatchConfig, build_spatial_buckets, mutual_nearest_matches, spatial_candidate_ids


VEHICLE_CLASSES = {2, 3, 5, 7}
FEATURE_MATCH_CONFIG = MatchConfig()


def report_progress(phase: str, current: int, total: int, message: str) -> None:
    print(json.dumps({"progress": {
        "phase": phase,
        "current": current,
        "total": total,
        "message": message,
    }}), flush=True)


def box_iou(first: list[int], second: list[int]) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    first_area = max(1, first[2] - first[0]) * max(1, first[3] - first[1])
    second_area = max(1, second[2] - second[0]) * max(1, second[3] - second[1])
    return intersection / max(1, first_area + second_area - intersection)


def association_score(first: list[int], second: list[int]) -> float:
    overlap = box_iou(first, second)
    first_center = ((first[0] + first[2]) / 2, (first[1] + first[3]) / 2)
    second_center = ((second[0] + second[2]) / 2, (second[1] + second[3]) / 2)
    distance = ((first_center[0] - second_center[0]) ** 2 + (first_center[1] - second_center[1]) ** 2) ** 0.5
    scale = max(first[2] - first[0], first[3] - first[1], second[2] - second[0], second[3] - second[1], 1)
    proximity = max(0.0, 1.0 - distance / (scale * 1.75))
    return max(overlap, proximity * 0.8)


def local_feature_matches(first: dict[str, Any], second: dict[str, Any]) -> list[cv2.DMatch]:
    first_descriptors = first.get("_descriptors")
    second_descriptors = second.get("_descriptors")
    matches = mutual_nearest_matches(first_descriptors, second_descriptors, FEATURE_MATCH_CONFIG)
    return [
        cv2.DMatch(match.query_index, match.train_index, float(match.distance))
        for match in matches
    ]


def extract_local_features(gray: np.ndarray, item: dict[str, Any]) -> None:
    height, width = gray.shape
    x1, y1, x2, y2 = item["xyxy"]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    if x2 - x1 < 12 or y2 - y1 < 12:
        item["_keypoints"] = []
        item["_descriptors"] = None
        return
    crop = gray[y1:y2, x1:x2]
    scale = min(4.0, max(1.0, 96 / min(crop.shape)))
    if scale > 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    keypoints, descriptors = cv2.ORB_create(
        nfeatures=100,
        edgeThreshold=8,
        patchSize=15,
        fastThreshold=7,
    ).detectAndCompute(crop, None)
    item["_keypoints"] = [(point.pt[0] / scale + x1, point.pt[1] / scale + y1) for point in keypoints]
    item["_descriptors"] = descriptors


def extract_appearance(frame: np.ndarray, item: dict[str, Any]) -> None:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = item["xyxy"]
    crop = frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
    if crop.size == 0:
        item["_histogram"] = None
        item["_crop"] = None
        return
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [18, 16], [0, 180, 0, 256])
    item["_histogram"] = cv2.normalize(histogram, histogram).flatten()
    item["_crop"] = crop.copy()


def appearance_similarity(first: dict[str, Any], second: dict[str, Any]) -> float:
    first_histogram = first.get("_histogram")
    second_histogram = second.get("_histogram")
    if first_histogram is None or second_histogram is None:
        return 0.0
    return max(0.0, float(cv2.compareHist(first_histogram, second_histogram, cv2.HISTCMP_CORREL)))


def geo_distance_m(first: dict[str, Any], second: dict[str, Any]) -> float:
    coordinates = (first.get("_latitude"), first.get("_longitude"), second.get("_latitude"), second.get("_longitude"))
    if any(value is None for value in coordinates):
        return float("inf")
    first_latitude, first_longitude, second_latitude, second_longitude = (float(value) for value in coordinates)
    north_m = (first_latitude - second_latitude) * 111_320
    east_m = (first_longitude - second_longitude) * 111_320 * math.cos(math.radians(first_latitude))
    return math.hypot(north_m, east_m)


def public_object(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


def assign_identity_ids(
    objects: list[dict[str, Any]],
    gallery: dict[int, dict[str, Any]],
    next_identity_id: int,
    source_frame: int,
    frame_step: int,
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], int]:
    current = {}
    claimed = set()
    spatial_buckets = build_spatial_buckets(gallery, FEATURE_MATCH_CONFIG.grid_size)
    for item in sorted(objects, key=lambda value: float(value["confidence"]), reverse=True):
        candidates = []
        nearby_identity_ids = spatial_candidate_ids(item["xyxy"], spatial_buckets, FEATURE_MATCH_CONFIG)
        for identity_id, prior in gallery.items():
            if identity_id in claimed or item["class_id"] != prior["class_id"]:
                continue
            frame_gap = source_frame - int(prior.get("_last_frame", source_frame))
            distance_m = geo_distance_m(item, prior)
            if identity_id not in nearby_identity_ids and (frame_gap <= frame_step * 4 or distance_m > 12):
                continue
            spatial_score = association_score(item["xyxy"], prior["xyxy"])
            matches = local_feature_matches(item, prior)
            item_descriptors = item.get("_descriptors")
            prior_descriptors = prior.get("_descriptors")
            descriptor_count = min(
                len(item_descriptors) if item_descriptors is not None else 0,
                len(prior_descriptors) if prior_descriptors is not None else 0,
            )
            feature_score = len(matches) / max(8, descriptor_count)
            color_score = appearance_similarity(item, prior)
            short_gap = frame_gap <= frame_step * 4
            evidence_passes = (
                (short_gap and spatial_score >= 0.16)
                or (len(matches) >= 6 and color_score >= 0.15)
                or (len(matches) >= 3 and color_score >= 0.72 and distance_m <= 12)
            )
            if not evidence_passes:
                continue
            gap_score = max(0.0, 1.0 - frame_gap / max(frame_step * 40, 1))
            geo_score = 0.0 if not math.isfinite(distance_m) else max(0.0, 1.0 - distance_m / 15)
            score = 0.42 * min(1.0, feature_score * 2) + 0.25 * color_score + 0.18 * spatial_score + 0.1 * geo_score + 0.05 * gap_score
            candidates.append((score, identity_id, len(matches), color_score))

        score, identity_id, match_count, color_score = max(candidates, default=(0.0, -1, 0, 0.0))
        if identity_id < 0:
            identity_id = next_identity_id
            next_identity_id += 1
            item["_best_crop"] = item.get("_crop")
            item["_best_crop_score"] = float(item["confidence"]) * max(1, (item["xyxy"][2] - item["xyxy"][0]) * (item["xyxy"][3] - item["xyxy"][1]))
            item["_largest_crop"] = item.get("_crop")
            item["_largest_crop_area"] = (item["xyxy"][2] - item["xyxy"][0]) * (item["xyxy"][3] - item["xyxy"][1])
            item["_match_history"] = []
            item["_appearance_history"] = []
        else:
            prior = gallery[identity_id]
            item["_best_crop"] = prior.get("_best_crop")
            item["_best_crop_score"] = prior.get("_best_crop_score", 0.0)
            item["_largest_crop"] = prior.get("_largest_crop")
            item["_largest_crop_area"] = prior.get("_largest_crop_area", 0)
            item["_match_history"] = [*prior.get("_match_history", []), match_count]
            item["_appearance_history"] = [*prior.get("_appearance_history", []), color_score]
            crop_score = float(item["confidence"]) * max(1, (item["xyxy"][2] - item["xyxy"][0]) * (item["xyxy"][3] - item["xyxy"][1]))
            if crop_score > item["_best_crop_score"]:
                item["_best_crop"] = item.get("_crop")
                item["_best_crop_score"] = crop_score
        crop_area = (item["xyxy"][2] - item["xyxy"][0]) * (item["xyxy"][3] - item["xyxy"][1])
        if item.get("_crop") is not None and crop_area > item.get("_largest_crop_area", 0):
            item["_largest_crop"] = item.get("_crop")
            item["_largest_crop_area"] = crop_area
        item["track_id"] = identity_id
        item["_identity_score"] = score
        item["_last_frame"] = source_frame
        claimed.add(identity_id)
        current[identity_id] = item
        gallery[identity_id] = item
    return current, gallery, next_identity_id


def parse_srt(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    records = []
    for block in path.read_text(encoding="utf-8", errors="replace").split("\n\n"):
        lines = block.splitlines()
        telemetry = next((line for line in lines if "[latitude:" in line), "")
        if not telemetry:
            continue

        def value(key: str) -> float | None:
            try:
                raw = telemetry.split(key, 1)[1].lstrip().split("]", 1)[0].split()[0]
                return float(raw)
            except (IndexError, ValueError):
                return None

        records.append({
            "frame": int(lines[0]) if lines and lines[0].isdigit() else len(records) + 1,
            "timestamp": next((line.split(" --> ", 1)[0] for line in lines if " --> " in line), ""),
            "latitude": value("[latitude:"),
            "longitude": value("[longitude:"),
            "relative_altitude_m": value("[rel_alt:"),
            "focal_len_35mm": value("[focal_len:"),
        })
    return records


def telemetry_for_frame(records: list[dict[str, Any]], frame: int, fps: float) -> dict[str, Any]:
    if not records:
        return {}
    if frame <= 0:
        return records[0]
    # DJI SRT subtitle blocks arrive at ~60 Hz (one per video frame), so the record
    # index maps 1:1 onto the video frame number. Clamp to the available range.
    block_index = min(len(records) - 1, max(0, int(frame)))
    return records[block_index]


def attach_ego_headings(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate each SRT record with the ego course-over-ground heading (deg, 0=north).

    Derived from the neighboring GPS positions because the SRT stream carries no
    camera/aircraft attitude. Nadir-aligned imagery is assumed; heading rotates the
    image plane in the ground frame. The window spans ~0.5 s (30 records at ~60 Hz)
    so GPS updates (~5 Hz) produce a stable course instead of noise.
    """
    window = 30
    enriched = [dict(record) for record in records]
    for index, record in enumerate(enriched):
        before = enriched[max(0, index - window)]
        after = enriched[min(len(enriched) - 1, index + window)]
        latitude_delta = (after["latitude"] or before["latitude"] or 0) - (before["latitude"] or after["latitude"] or 0)
        longitude_delta = (after["longitude"] or before["longitude"] or 0) - (before["longitude"] or after["longitude"] or 0)
        if latitude_delta == 0 and longitude_delta == 0:
            record["_heading_deg"] = None
            continue
        record["_heading_deg"] = math.degrees(math.atan2(longitude_delta, latitude_delta)) % 360.0
    return enriched


def focal_length_pixels(width: int, focal_35mm: float | None) -> float:
    """Convert the 35mm-equivalent focal length reported by the SRT to pixels.

    The 35mm-equivalent convention references a 36mm-wide frame, so
    f_px = width_px * focal_35 / 36.
    """
    focal = float(focal_35mm) if focal_35mm else 24.0
    return width * focal / 36.0


def project_ground_ray(
    telemetry: dict[str, Any],
    box: list[int],
    width: int,
    height: int,
) -> tuple[float | None, float | None, str]:
    """Project a detection's ground position from the ego pose and its pixel ray.

    Assumes a nadir-aligned camera: the ground offset of each pixel follows from the
    pinhole geometry (focal length from SRT, altitude as standoff), then the image
    plane is rotated by the ego course-over-ground heading. Falls back to the fixed
    FOV image-plane approximation when telemetry fields are missing.
    """
    latitude = telemetry.get("latitude")
    longitude = telemetry.get("longitude")
    altitude = telemetry.get("relative_altitude_m")
    if latitude is None or longitude is None or altitude is None:
        return None, None, "unavailable"

    focal_35mm = telemetry.get("focal_len_35mm")
    heading = telemetry.get("_heading_deg")
    if focal_35mm is None or heading is None:
        return approximate_object_position(telemetry, box, width, height)

    standoff_m = max(1.5, float(altitude))
    focal_px = focal_length_pixels(width, focal_35mm)
    center_x = (box[0] + box[2]) / 2
    center_y = (box[1] + box[3]) / 2
    dx_m = (center_x - width / 2) / focal_px * standoff_m
    dy_m = (center_y - height / 2) / focal_px * standoff_m

    heading_rad = math.radians(float(heading))
    east_m = dy_m * math.sin(heading_rad) + dx_m * math.cos(heading_rad)
    north_m = dy_m * math.cos(heading_rad) - dx_m * math.sin(heading_rad)

    object_latitude = float(latitude) + north_m / 111_320
    longitude_scale = max(1.0, 111_320 * math.cos(math.radians(float(latitude))))
    object_longitude = float(longitude) + east_m / longitude_scale
    return object_latitude, object_longitude, "ground_ray_projection"


def track_position_summary(
    items: list[dict[str, Any]],
) -> tuple[float | None, float | None, str, float | None]:
    """Aggregate per-observation ground rays into one robust track position.

    Iterative 2-sigma trimming around the median keeps outlier ray intersections
    (mis-associations, motion blur) from dragging the object location.
    """
    positions = [
        (float(item["latitude"]), float(item["longitude"]))
        for item in items
        if item.get("latitude") is not None and item.get("longitude") is not None
    ]
    if not positions:
        return None, None, "unavailable", None
    if len(positions) == 1:
        return positions[0][0], positions[0][1], "ground_ray_single", None

    arrays = np.asarray(positions)
    for _ in range(2):
        median = np.median(arrays, axis=0)
        north_m = (arrays[:, 0] - median[0]) * 111_320
        east_m = (arrays[:, 1] - median[1]) * 111_320 * math.cos(math.radians(float(median[0])))
        distances = np.hypot(north_m, east_m)
        sigma = distances.std() if distances.size > 1 else 0.0
        if sigma <= 1e-6:
            break
        keep = distances <= max(2.0, 2.5 * sigma)
        if keep.all():
            break
        arrays = arrays[keep]
        if len(arrays) < 2:
            break

    summary = arrays.mean(axis=0)
    north_m = (arrays[:, 0] - summary[0]) * 111_320
    east_m = (arrays[:, 1] - summary[1]) * 111_320 * math.cos(math.radians(float(summary[0])))
    spread_m = float(np.hypot(north_m, east_m).mean())
    mode = "ground_ray_multi" if len(positions) > 1 else "ground_ray_single"
    return float(summary[0]), float(summary[1]), mode, spread_m


def draw_flow(frame: np.ndarray, previous: np.ndarray, boxes: list[list[int]], padding: int) -> tuple[np.ndarray, float]:
    if not boxes:
        return frame, 0.0
    height, width = frame.shape[:2]
    overlay = frame.copy()
    magnitudes = []
    for box in boxes:
        x1 = max(0, box[0] - padding)
        y1 = max(0, box[1] - padding)
        x2 = min(width, box[2] + padding)
        y2 = min(height, box[3] + padding)
        if x2 - x1 < 12 or y2 - y1 < 12:
            continue
        previous_gray = cv2.cvtColor(previous[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        current_gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(previous_gray, current_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        magnitudes.append(float(np.mean(magnitude)))
        spacing = max(16, min(x2 - x1, y2 - y1) // 5)
        for local_y in range(spacing // 2, y2 - y1, spacing):
            for local_x in range(spacing // 2, x2 - x1, spacing):
                dx, dy = flow[local_y, local_x]
                vector_magnitude = math.hypot(float(dx), float(dy))
                if vector_magnitude < 0.45:
                    continue
                scale = min(4.0, 18.0 / max(vector_magnitude, 0.1))
                start = (x1 + local_x, y1 + local_y)
                end = (round(start[0] + dx * scale), round(start[1] + dy * scale))
                cv2.arrowedLine(overlay, start, end, (40, 220, 255), 2, cv2.LINE_AA, tipLength=0.28)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (255, 180, 30), 1)
    return overlay, float(np.mean(magnitudes)) if magnitudes else 0.0


def draw_feature_correspondences(
    frame: np.ndarray,
    current_tracks: dict[int, dict[str, Any]],
    previous_tracks: dict[int, dict[str, Any]],
) -> dict[int, int]:
    counts = {}
    for track_id, current in current_tracks.items():
        previous = previous_tracks.get(track_id)
        if previous is None:
            counts[track_id] = 0
            continue
        matches = local_feature_matches(current, previous)[:8]
        counts[track_id] = len(matches)
        current_points = current.get("_keypoints", [])
        previous_points = previous.get("_keypoints", [])
        for match in matches:
            current_point = tuple(round(value) for value in current_points[match.queryIdx])
            previous_point = np.array(previous_points[match.trainIdx], dtype=np.float32)
            current_vector = np.array(current_point, dtype=np.float32)
            delta = current_vector - previous_point
            distance = float(np.linalg.norm(delta))
            start_vector = current_vector if distance < 0.1 else current_vector - delta / distance * min(10.0, distance)
            start_point = tuple(round(float(value)) for value in start_vector)
            cv2.arrowedLine(frame, start_point, current_point, (255, 80, 220), 1, cv2.LINE_AA, tipLength=0.25)
            cv2.circle(frame, current_point, 3, (80, 255, 170), -1, cv2.LINE_AA)
    return counts


def approximate_object_position(
    telemetry: dict[str, Any],
    box: list[int],
    width: int,
    height: int,
) -> tuple[float | None, float | None, str]:
    latitude = telemetry.get("latitude")
    longitude = telemetry.get("longitude")
    altitude = telemetry.get("relative_altitude_m")
    if latitude is None or longitude is None or altitude is None:
        return latitude, longitude, "unavailable"
    ground_altitude = max(1.0, float(altitude))
    ground_width = 2 * ground_altitude * math.tan(math.radians(73.7 / 2))
    ground_height = 2 * ground_altitude * math.tan(math.radians(53.1 / 2))
    center_x = (box[0] + box[2]) / 2
    center_y = (box[1] + box[3]) / 2
    east_m = (center_x / width - 0.5) * ground_width
    north_m = (0.5 - center_y / height) * ground_height
    object_latitude = float(latitude) + north_m / 111_320
    longitude_scale = max(1.0, 111_320 * math.cos(math.radians(float(latitude))))
    object_longitude = float(longitude) + east_m / longitude_scale
    return object_latitude, object_longitude, "image_plane_offset_approximation"


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_video = args.output_dir / f"{args.video.stem}.cv-preview.mp4"
    observations_path = args.output_dir / f"{args.video.stem}.objects.json"
    detections_path = args.output_dir / f"{args.video.stem}.detections.jsonl"
    database_path = args.output_dir / "object-recognition.sqlite3"
    crops_dir = args.output_dir / "identity-crops"
    crops_dir.mkdir(exist_ok=True)
    telemetry = attach_ego_headings(parse_srt(args.srt))

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video: {args.video}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    offset_frames = int(max(0.0, args.start_offset) * fps)
    if offset_frames:
        capture.set(cv2.CAP_PROP_POS_FRAMES, offset_frames)
        source_start_frame = int(capture.get(cv2.CAP_PROP_POS_FRAMES))
    else:
        source_start_frame = 0
    source_frame = source_start_frame
    output_width = min(1920, width)
    output_height = max(2, int(round(height * output_width / width)) // 2 * 2)
    if getattr(args, "full_video", False):
        max_source_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or (source_start_frame + int(args.duration * fps))
    else:
        max_source_frames = source_start_frame + int(args.duration * fps)
    total_processed_frames = max(1, (max_source_frames - source_start_frame + args.frame_step - 1) // args.frame_step)
    report_progress("initializing", 2, 100, "Opening video and loading YOLO model")

    ffmpeg = subprocess.Popen(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{output_width}x{output_height}",
            "-r", str(fps / args.frame_step), "-i", "-", "-an", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(output_video),
        ],
        stdin=subprocess.PIPE,
    )
    model = YOLO(str(args.model))
    report_progress("inference", 5, 100, "Analyzing sampled frames")
    previous_frame: np.ndarray | None = None
    observations: list[dict[str, Any]] = []
    tracks: dict[int, list[dict[str, Any]]] = defaultdict(list)
    identity_gallery: dict[int, dict[str, Any]] = {}
    next_identity_id = 1
    processed = 0
    fps_values: list[float] = []

    try:
        with detections_path.open("w", encoding="utf-8") as detections_file:
            while source_frame < max_source_frames:
                ok, frame = capture.read()
                if not ok:
                    break
                if source_frame % args.frame_step:
                    source_frame += 1
                    continue

                result = model.track(
                    frame,
                    persist=True,
                    tracker="bytetrack.yaml",
                    conf=args.confidence,
                    classes=sorted(VEHICLE_CLASSES),
                    device=args.device,
                    verbose=False,
                )[0]
                boxes: list[list[int]] = []
                frame_objects = []
                if result.boxes is not None:
                    for box in result.boxes:
                        xyxy = [int(value) for value in box.xyxy[0].tolist()]
                        class_id = int(box.cls.item())
                        confidence = float(box.conf.item())
                        boxes.append(xyxy)
                        frame_objects.append({
                            "class_id": class_id,
                            "class_name": model.names.get(class_id, str(class_id)),
                            "confidence": round(confidence, 4),
                            "xyxy": xyxy,
                        })

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                telemetry_row = telemetry_for_frame(telemetry, source_frame, fps)
                for item in frame_objects:
                    extract_local_features(gray, item)
                    extract_appearance(frame, item)
                    object_latitude, object_longitude, geolocation_mode = project_ground_ray(
                        telemetry_row, item["xyxy"], width, height,
                    )
                    item["_latitude"] = object_latitude
                    item["_longitude"] = object_longitude
                    item["_geolocation_mode"] = geolocation_mode
                prior_gallery = identity_gallery.copy()
                current_tracks, identity_gallery, next_identity_id = assign_identity_ids(
                    frame_objects,
                    identity_gallery,
                    next_identity_id,
                    source_frame,
                    args.frame_step,
                )

                flow_mean = 0.0
                frame_start_time = time.monotonic()
                if args.optical_flow and previous_frame is not None:
                    frame, flow_mean = draw_flow(frame, previous_frame, boxes, args.roi_padding)
                feature_match_counts = draw_feature_correspondences(frame, current_tracks, prior_gallery) if args.reid else {}

                for item in frame_objects:
                    observation = {
                        **public_object(item),
                        "video": args.video.name,
                        "frame": source_frame,
                        "timestamp_sec": round(source_frame / fps, 3),
                        "latitude": item["_latitude"],
                        "longitude": item["_longitude"],
                        "relative_altitude_m": telemetry_row.get("relative_altitude_m"),
                        "geolocation_mode": item["_geolocation_mode"],
                        "flow_magnitude_px": round(flow_mean, 4),
                        "local_feature_matches": feature_match_counts.get(item["track_id"], 0),
                        "identity_score": round(float(item.get("_identity_score", 0.0)), 4),
                    }
                    observations.append(observation)
                    tracks[item["track_id"]].append(observation)

                    x1, y1, x2, y2 = item["xyxy"]
                    if args.detections:
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 230, 220), 3)
                    if args.detections or args.reid:
                        label = f"{item['class_name']} {item['confidence']:.2f}"
                        if args.reid:
                            label = f"ID {item['track_id']} | {label} | ORB {feature_match_counts.get(item['track_id'], 0)}"
                        cv2.putText(frame, label, (x1, max(24, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 230, 220), 2, cv2.LINE_AA)

                record = {
                    "video": args.video.name,
                    "frame": source_frame,
                    "vehicle_boxes": [public_object(item) for item in frame_objects],
                    "optical_flow_mean_px": round(flow_mean, 4),
                    "local_feature_matches": feature_match_counts,
                    "telemetry": telemetry_row,
                }
                detections_file.write(json.dumps(record) + "\n")

                hud = f"Frame {source_frame} | Objects {len(frame_objects)} | ROI flow {flow_mean:.2f}px"
                cv2.rectangle(frame, (12, 12), (620, 54), (5, 16, 24), -1)
                cv2.putText(frame, hud, (24, 41), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (235, 245, 250), 2, cv2.LINE_AA)
                resized = cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_AREA)
                if ffmpeg.stdin is None:
                    raise RuntimeError("ffmpeg preview stream closed unexpectedly")
                ffmpeg.stdin.write(resized.tobytes())
                previous_frame = frame.copy()
                processed += 1
                if processed == 1 or processed % 2 == 0 or processed == total_processed_frames:
                    report_progress(
                        "inference",
                        5 + round(88 * processed / total_processed_frames),
                        100,
                        f"Analyzed {processed} of {total_processed_frames} sampled frames",
                    )
                source_frame += 1
                frame_elapsed = time.monotonic() - frame_start_time
                fps_values.append(round(1.0 / max(0.001, frame_elapsed), 2))
    finally:
        capture.release()
        if ffmpeg.stdin is not None:
            ffmpeg.stdin.close()
        return_code = ffmpeg.wait()

    if return_code != 0 or not output_video.is_file():
        raise RuntimeError("ffmpeg failed to encode the visualization preview")

    report_progress("persisting", 95, 100, "Saving tracks and geolocated observations")
    track_records = []
    for track_id, items in sorted(tracks.items()):
        confidences = [float(item["confidence"]) for item in items]
        profile = identity_gallery[track_id]
        crop_path = crops_dir / f"identity-{track_id}.jpg"
        crop = profile.get("_best_crop")
        if crop is None:
            crop = profile.get("_largest_crop")
        if crop is not None and crop.size:
            cv2.imwrite(str(crop_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        else:
            crop_path = None
        match_counts = [int(item.get("local_feature_matches", 0)) for item in items]
        identity_scores = [float(item.get("identity_score", 0.0)) for item in items if float(item.get("identity_score", 0.0)) > 0]
        summary_latitude, summary_longitude, summary_mode, geo_spread_m = track_position_summary(items)
        track_records.append({
            "track_id": track_id,
            "class_name": items[0]["class_name"],
            "confidence": round(sum(confidences) / len(confidences), 4),
            "first_frame": items[0]["frame"],
            "last_frame": items[-1]["frame"],
            "observations": len(items),
            "latitude": summary_latitude,
            "longitude": summary_longitude,
            "geo_spread_m": round(geo_spread_m, 3) if geo_spread_m is not None else None,
            "relative_altitude_m": items[len(items) // 2].get("relative_altitude_m"),
            "geolocation_mode": summary_mode,
            "representative_crop_path": str(crop_path) if crop_path is not None else None,
            "local_feature_matches_avg": round(sum(match_counts) / len(match_counts), 2),
            "local_feature_matches_max": max(match_counts, default=0),
            "identity_score_avg": round(sum(identity_scores) / len(identity_scores), 4) if identity_scores else 0.0,
            "identity_method": "spatial_mnn_orb_hsv_geo_gallery",
            "plate_status": "not_run",
            "plate_text": None,
        })

    track_history = {}
    for track_id, items in sorted(tracks.items()):
        track_history[str(track_id)] = [
            {
                "frame": item["frame"],
                "timestamp_sec": item["timestamp_sec"],
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "relative_altitude_m": item["relative_altitude_m"],
                "confidence": item["confidence"],
                "class_name": item["class_name"],
                "geolocation_mode": item["geolocation_mode"],
            }
            for item in items
        ]

    payload = {
        "overlay_path": str(output_video),
        "detections_path": str(detections_path),
        "database_path": str(database_path),
        "processed_frames": processed,
        "observation_count": len(observations),
        "objects": track_records,
        "track_history": track_history,
        "video_fps": round(float(fps), 3),
        "video_width": width,
        "video_height": height,
        "fps_over_time": fps_values,
        "configuration": {
            "detections": args.detections,
            "optical_flow": args.optical_flow,
            "reid": args.reid,
            "confidence": args.confidence,
            "frame_step": args.frame_step,
            "duration_seconds": args.duration,
            "start_offset_seconds": args.start_offset,
            "full_video": getattr(args, "full_video", False),
            "roi_padding": args.roi_padding,
            "device": args.device,
        },
    }
    with sqlite3.connect(database_path) as database:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS geolocated_objects (
                video TEXT NOT NULL,
                track_id INTEGER NOT NULL,
                class_name TEXT NOT NULL,
                confidence REAL NOT NULL,
                first_frame INTEGER NOT NULL,
                last_frame INTEGER NOT NULL,
                observations INTEGER NOT NULL,
                latitude REAL,
                longitude REAL,
                relative_altitude_m REAL,
                geolocation_mode TEXT NOT NULL,
                geo_spread_m REAL,
                PRIMARY KEY (video, track_id)
            );
            CREATE TABLE IF NOT EXISTS detection_observations (
                video TEXT NOT NULL,
                frame INTEGER NOT NULL,
                track_id INTEGER NOT NULL,
                class_name TEXT NOT NULL,
                confidence REAL NOT NULL,
                bbox_json TEXT NOT NULL,
                timestamp_sec REAL NOT NULL,
                latitude REAL,
                longitude REAL,
                relative_altitude_m REAL,
                flow_magnitude_px REAL NOT NULL,
                geolocation_mode TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS object_identity_profiles (
                video TEXT NOT NULL,
                identity_id INTEGER NOT NULL,
                representative_crop_path TEXT,
                identity_method TEXT NOT NULL,
                local_feature_matches_avg REAL NOT NULL,
                local_feature_matches_max INTEGER NOT NULL,
                identity_score_avg REAL NOT NULL,
                plate_status TEXT NOT NULL,
                plate_text TEXT,
                PRIMARY KEY (video, identity_id)
            );
            """
        )
        try:
            database.execute("ALTER TABLE geolocated_objects ADD COLUMN geo_spread_m REAL")
        except sqlite3.OperationalError:
            pass
        database.execute("DELETE FROM geolocated_objects WHERE video = ?", (args.video.name,))
        database.execute("DELETE FROM detection_observations WHERE video = ?", (args.video.name,))
        database.execute("DELETE FROM object_identity_profiles WHERE video = ?", (args.video.name,))
        database.executemany(
            "INSERT INTO geolocated_objects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    args.video.name, item["track_id"], item["class_name"], item["confidence"],
                    item["first_frame"], item["last_frame"], item["observations"], item["latitude"],
                    item["longitude"], item["relative_altitude_m"], item["geolocation_mode"], item["geo_spread_m"],
                )
                for item in track_records
            ],
        )
        database.executemany(
            "INSERT INTO detection_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item["video"], item["frame"], item["track_id"], item["class_name"], item["confidence"],
                    json.dumps(item["xyxy"]), item["timestamp_sec"], item["latitude"], item["longitude"],
                    item["relative_altitude_m"], item["flow_magnitude_px"], item["geolocation_mode"],
                )
                for item in observations
            ],
        )
        database.executemany(
            "INSERT INTO object_identity_profiles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    args.video.name, item["track_id"], item["representative_crop_path"], item["identity_method"],
                    item["local_feature_matches_avg"], item["local_feature_matches_max"], item["identity_score_avg"],
                    item["plate_status"], item["plate_text"],
                )
                for item in track_records
            ],
        )
    observations_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a bounded IntelSight CV visualization preview")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--srt", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--start-offset", type=float, default=10.0,
                        help="Seconds to skip at the start of the mission (launch footage).")
    parser.add_argument("--full-video", action="store_true",
                        help="Process the entire video from the start offset to the end.")
    parser.add_argument("--frame-step", type=int, default=5)
    parser.add_argument("--confidence", type=float, default=0.35)
    parser.add_argument("--roi-padding", type=int, default=48)
    parser.add_argument("--device", default="0")
    parser.add_argument("--detections", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--optical-flow", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--reid", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    print(json.dumps(run(args)))


if __name__ == "__main__":
    main()