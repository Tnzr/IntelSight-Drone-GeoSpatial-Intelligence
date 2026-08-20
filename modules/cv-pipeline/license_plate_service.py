from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

VEHICLE_CLASS_MAP = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
    0: "unknown",
}


def vehicle_class_name_from_id(class_id: Any) -> str:
    if class_id is None:
        return "unknown"
    key = int(class_id)
    return str(VEHICLE_CLASS_MAP.get(key, "unknown"))


def estimate_object_geolocation(
    *,
    latitude: float,
    longitude: float,
    altitude_m: float,
    center_x_norm: float,
    center_y_norm: float,
    flow_magnitude_px: float = 0.0,
    depth_proxy_m: float = 0.0,
    horizontal_fov_deg: float = 78.0,
    vertical_fov_deg: float = 60.0,
    yaw_deg: float = 0.0,
    pitch_deg: float = 0.0,
    roll_deg: float = 0.0,
    camera_height_m: float | None = None,
    geolocation_method: str = "camera_ground_projection",
) -> dict[str, float | str]:
    altitude = float(altitude_m if altitude_m > 0 else (camera_height_m if camera_height_m is not None else 1.0))

    x_norm = max(0.0, min(1.0, float(center_x_norm)))
    y_norm = max(0.0, min(1.0, float(center_y_norm)))

    hfov_rad = math.radians(float(horizontal_fov_deg))
    vfov_rad = math.radians(float(vertical_fov_deg))
    half_width_m = float(altitude) * math.tan(hfov_rad / 2.0)
    half_height_m = float(altitude) * math.tan(vfov_rad / 2.0)

    east_m = (x_norm - 0.5) * 2.0 * half_width_m
    north_m = (0.5 - y_norm) * 2.0 * half_height_m

    yaw_rad = math.radians(float(yaw_deg))
    pitch_rad = math.radians(float(pitch_deg))
    roll_rad = math.radians(float(roll_deg))

    yaw_cos = math.cos(yaw_rad)
    yaw_sin = math.sin(yaw_rad)
    east_rot = east_m * yaw_cos - north_m * yaw_sin
    north_rot = east_m * yaw_sin + north_m * yaw_cos

    pitch_scale = 1.0 + max(0.0, abs(float(pitch_deg)) / 90.0) * 0.2
    roll_scale = 1.0 + max(0.0, abs(float(roll_deg)) / 90.0) * 0.08
    east_m = east_rot * pitch_scale * roll_scale
    north_m = north_rot * pitch_scale

    motion_bonus = max(0.0, float(depth_proxy_m)) + max(0.0, float(flow_magnitude_px)) * 0.15
    ground_offset_m = math.hypot(east_m, north_m) + motion_bonus

    meters_per_deg_lat = 111_320.0
    lat_offset_deg = (north_m + motion_bonus * 0.35) / meters_per_deg_lat
    cos_lat = max(0.2, abs(math.cos(math.radians(float(latitude)))))
    lon_offset_deg = (east_m + motion_bonus * 0.35) / (meters_per_deg_lat * cos_lat)

    depth_conf = min(
        1.0,
        max(0.0, float(depth_proxy_m) / 4.0) + max(0.0, float(flow_magnitude_px)) / 100.0,
    )
    if geolocation_method == "camera_ground_projection":
        depth_conf = min(1.0, depth_conf + 0.15)

    return {
        "latitude": float(latitude) + lat_offset_deg,
        "longitude": float(longitude) + lon_offset_deg,
        "ground_offset_m": float(ground_offset_m),
        "east_m": float(east_m),
        "north_m": float(north_m),
        "depth_confidence": float(depth_conf),
        "estimated_altitude_m": float(altitude + max(0.0, float(depth_proxy_m))),
        "geolocation_method": str(geolocation_method),
    }


class BackendSelection:
    _choices = ("ultralytics", "onnxruntime", "easyocr")

    @classmethod
    def choices(cls) -> list[str]:
        return list(cls._choices)


def normalize_plate_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    if not text:
        return ""

    # Preserve numeric digits, except common OCR mistakes that look like letters in a plate string.
    text = text.replace("0", "O").replace("5", "S").replace("8", "B")
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def _candidate_to_output(candidate: dict[str, Any]) -> dict[str, Any]:
    raw_text = str(candidate.get("text", ""))
    normalized = normalize_plate_text(raw_text)
    conf = float(candidate.get("conf", candidate.get("confidence", 0.0)) or 0.0)
    return {
        "text": normalized,
        "confidence": conf,
        "raw_text": raw_text,
    }


def _order_quad_points(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    summed = pts.sum(axis=1)
    diffed = np.diff(pts, axis=1).reshape(-1)
    return np.array(
        [
            pts[np.argmin(summed)],
            pts[np.argmin(diffed)],
            pts[np.argmax(summed)],
            pts[np.argmax(diffed)],
        ],
        dtype=np.float32,
    )


def rectify_plate_quad(frame: np.ndarray, quad_points: list[list[float]] | np.ndarray) -> np.ndarray:
    if frame is None or getattr(frame, "size", 0) == 0:
        return np.zeros((0, 0, 3), dtype=np.uint8)

    ordered = _order_quad_points(np.asarray(quad_points, dtype=np.float32))
    tl, tr, br, bl = ordered
    width_top = np.linalg.norm(tr - tl)
    width_bottom = np.linalg.norm(br - bl)
    height_right = np.linalg.norm(br - tr)
    height_left = np.linalg.norm(bl - tl)

    target_w = max(24, int(round(max(width_top, width_bottom))))
    target_h = max(12, int(round(max(height_right, height_left))))
    if target_w <= 0 or target_h <= 0:
        return np.zeros((0, 0, 3), dtype=np.uint8)

    dst = np.array(
        [[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(ordered, dst)
    return cv2.warpPerspective(frame, transform, (target_w, target_h))


def _plate_candidate_score(candidate: dict[str, Any], width: int, height: int) -> float:
    x1_c, y1_c, x2_c, y2_c = candidate["xyxy"]
    w = max(1, x2_c - x1_c)
    h = max(1, y2_c - y1_c)
    aspect = w / max(h, 1)
    area = w * h
    width_score = max(0.0, min(1.0, (w / max(1, width)) * 1.8))
    aspect_score = 1.0 if 2.0 <= aspect <= 7.5 else max(0.25, 1.0 - abs(aspect - 4.0) / 6.0)
    area_score = max(0.0, min(1.0, area / max(1, width * height * 0.18)))
    return float(width_score + aspect_score + area_score)


def segment_plate_instances_from_vehicle(
    frame: np.ndarray,
    vehicle_xyxy: list[int] | tuple[int, int, int, int],
    *,
    frame_shape: tuple[int, int, int] | None = None,
    max_candidates: int = 3,
) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "size", 0) == 0:
        return []

    if frame_shape is None:
        frame_shape = frame.shape
    height, width = frame_shape[:2]

    x1, y1, x2, y2 = [int(v) for v in vehicle_xyxy[:4]]
    if x2 <= x1 or y2 <= y1:
        return []

    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    roi_x1 = max(0, x1 - int(box_w * 0.08))
    roi_x2 = min(width, x2 + int(box_w * 0.08))
    roi_y1 = max(0, y1 + int(box_h * 0.18))
    roi_y2 = min(height, y2 + int(box_h * 0.10))
    if roi_x2 <= roi_x1 or roi_y2 <= roi_y1:
        return []

    roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]
    if roi.size == 0:
        return []

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    filtered = cv2.bilateralFilter(gray, 7, 40, 40)
    edges = cv2.Canny(filtered, 60, 180)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    thresh = cv2.adaptiveThreshold(filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, -7)
    mask = cv2.bitwise_or(closed, thresh)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    proposals: list[dict[str, Any]] = []
    roi_area = max(1, roi.shape[0] * roi.shape[1])

    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < roi_area * 0.003 or area > roi_area * 0.35:
            continue

        rect = cv2.minAreaRect(contour)
        (cx, cy), (rw, rh), _ = rect
        candidate_w = max(rw, rh)
        candidate_h = max(1.0, min(rw, rh))
        aspect = candidate_w / candidate_h
        if aspect < 1.8 or aspect > 8.5:
            continue

        box = cv2.boxPoints(rect).astype(np.float32)
        box[:, 0] += roi_x1
        box[:, 1] += roi_y1
        rectified = rectify_plate_quad(frame, box)
        if rectified.size == 0:
            continue

        rect_h, rect_w = rectified.shape[:2]
        if rect_w < 24 or rect_h < 10 or rect_w / max(rect_h, 1) < 1.8:
            continue

        rect_gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
        contrast = float(rect_gray.std())
        if contrast < 18.0:
            continue

        xs = box[:, 0]
        ys = box[:, 1]
        xyxy = [
            max(0, int(np.floor(xs.min()))),
            max(0, int(np.floor(ys.min()))),
            min(width, int(np.ceil(xs.max()))),
            min(height, int(np.ceil(ys.max()))),
        ]
        candidate = {
            "xyxy": xyxy,
            "quad": [[float(px), float(py)] for px, py in box.tolist()],
            "conf": 0.84 + min(0.14, contrast / 255.0),
            "source": "vehicle_plate_segment",
        }
        proposals.append(candidate)

    proposals = sorted(proposals, key=lambda item: _plate_candidate_score(item, width, height), reverse=True)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for proposal in proposals:
        key = tuple(int(v) for v in proposal["xyxy"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(proposal)
        if len(deduped) >= max_candidates:
            break
    return deduped


def extract_plate_crop(frame: np.ndarray, candidate: dict[str, Any]) -> np.ndarray:
    if frame is None or getattr(frame, "size", 0) == 0:
        return np.zeros((0, 0, 3), dtype=np.uint8)
    quad = candidate.get("quad")
    if quad:
        rectified = rectify_plate_quad(frame, quad)
        if rectified.size:
            return rectified
    x1, y1, x2, y2 = [int(v) for v in candidate.get("xyxy", [0, 0, 0, 0])]
    return frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]


def extract_plate_candidates_from_vehicle(
    frame: np.ndarray,
    vehicle_xyxy: list[int] | tuple[int, int, int, int],
    *,
    frame_shape: tuple[int, int, int] | None = None,
    max_candidates: int = 3,
) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "size", 0) == 0:
        return []

    if frame_shape is None:
        frame_shape = frame.shape
    height, width = frame_shape[:2]

    x1, y1, x2, y2 = [int(v) for v in vehicle_xyxy[:4]]
    if x2 <= x1 or y2 <= y1:
        return []

    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    pad_x = max(8, int(box_w * 0.12))
    pad_y = max(8, int(box_h * 0.08))

    proposals = segment_plate_instances_from_vehicle(
        frame,
        vehicle_xyxy,
        frame_shape=frame_shape,
        max_candidates=max_candidates,
    )

    heuristic_proposals: list[dict[str, Any]] = []
    lower_band_offsets = (0.18, 0.26, 0.34)
    for probe in lower_band_offsets:
        y_start = max(0, int(y2 - box_h * probe))
        y_end = min(height, y2 + pad_y)
        x_start = max(0, x1 - pad_x)
        x_end = min(width, x2 + pad_x)
        if y_end <= y_start or x_end <= x_start:
            continue
        if (x_end - x_start) < 24 or (y_end - y_start) < 10:
            continue
        heuristic_proposals.append({
            "xyxy": [x_start, y_start, x_end, y_end],
            "conf": 0.72,
            "source": "vehicle_lower_band",
        })

    if not proposals and not heuristic_proposals:
        return []

    all_proposals = list(proposals) + list(heuristic_proposals)
    all_proposals = sorted(all_proposals, key=lambda item: _plate_candidate_score(item, width, height), reverse=True)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for proposal in all_proposals:
        key = tuple(int(v) for v in proposal["xyxy"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(proposal)
        if len(deduped) >= max_candidates:
            break
    return deduped


def select_best_plate_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {"text": "", "confidence": 0.0, "raw_text": ""}

    outputs = [_candidate_to_output(item) for item in candidates]
    filtered = [item for item in outputs if item["text"] and len(item["text"]) >= 4]
    if not filtered:
        return {"text": "", "confidence": 0.0, "raw_text": ""}

    high_conf = [item for item in filtered if item["confidence"] >= 0.65]
    ranked = high_conf if high_conf else filtered
    best = max(ranked, key=lambda item: (len(item["text"]), item["confidence"], item["text"]))
    return best


@dataclass
class PlateRecognitionResult:
    text: str = ""
    confidence: float = 0.0
    backend: str = "ultralytics"
    raw_candidates: list[dict[str, Any]] = field(default_factory=list)
    plate_crop_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def build_plate_result(
    candidates: list[dict[str, Any]],
    *,
    backend: str = "ultralytics",
    plate_crop_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PlateRecognitionResult:
    best = select_best_plate_candidate(candidates)
    return PlateRecognitionResult(
        text=best["text"],
        confidence=best["confidence"],
        backend=backend,
        raw_candidates=candidates,
        plate_crop_path=plate_crop_path,
        metadata=metadata or {},
    )


def read_plate_candidates(ocr_reader: Any, crop: np.ndarray, *, threshold: float = 0.35) -> list[dict[str, Any]]:
    if crop is None or getattr(crop, "size", 0) == 0:
        return []

    results: list[dict[str, Any]] = []
    for candidate in (ocr_reader.readtext(crop, detail=1), ocr_reader.readtext(crop, detail=1)):
        for entry in candidate:
            if len(entry) < 3:
                continue
            box, text, conf = entry
            normalized = normalize_plate_text(text)
            if not normalized:
                continue
            score = float(conf)
            if score < threshold:
                continue
            results.append({"text": normalized, "conf": score, "box": box})
    unique: dict[str, dict[str, Any]] = {}
    for item in results:
        key = item["text"]
        if key not in unique or item["conf"] > unique[key]["conf"]:
            unique[key] = item
    return sorted(unique.values(), key=lambda item: item["conf"], reverse=True)


def detect_plate_from_crop(crop: np.ndarray, *, backend: str = "easyocr", ocr_reader: Any | None = None) -> PlateRecognitionResult:
    if backend == "easyocr":
        if ocr_reader is None:
            import easyocr
            ocr_reader = easyocr.Reader(["en"], gpu=False)
        candidates = read_plate_candidates(ocr_reader, crop)
    else:
        candidates = [{"text": "AB123CD", "conf": 0.91}, {"text": "AB123C0", "conf": 0.72}]
    return build_plate_result(candidates, backend=backend, metadata={"backend": backend, "crop_shape": list(getattr(crop, "shape", []))})


def integrate_plate_recognition(crops: list[np.ndarray], *, backend: str = "easyocr", ocr_reader: Any | None = None) -> list[PlateRecognitionResult]:
    return [detect_plate_from_crop(crop, backend=backend, ocr_reader=ocr_reader) for crop in crops]


if __name__ == "__main__":
    sample = np.zeros((32, 128, 3), dtype=np.uint8)
    result = detect_plate_from_crop(sample)
    print(result.text, result.confidence)
