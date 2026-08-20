from __future__ import annotations

import argparse
import csv
import json
import logging
import multiprocessing as mp
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from tqdm import tqdm

from license_plate_service import (
    estimate_object_geolocation,
    extract_plate_crop,
    extract_plate_candidates_from_vehicle,
    select_best_plate_candidate,
    vehicle_class_name_from_id,
)

logger = logging.getLogger("intelsight.cv")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def resolve_checkpoint(name: str) -> str:
    local = MODELS_DIR / name
    return str(local) if local.exists() else name



@dataclass
class StageMetrics:
    video: str
    gpu: str
    frames_read: int
    frames_processed: int
    detections_vehicle: int
    detections_plate: int
    ocr_attempts: int
    read_ms: float
    detect_ms: float
    ocr_ms: float
    post_ms: float
    total_ms: float


@dataclass(frozen=True)
class RuntimeTuning:
    use_full_frame_plate_detector: bool = True
    prefer_roi_plate_model: bool = True
    ocr_frame_interval: int = 1
    max_plate_boxes: int = 8
    max_ocr_crops: int = 5
    min_plate_crop_area: int = 400
    enhanced_ocr_confidence_threshold: float = 0.72
    reid_frame_diff_threshold: float = 0.025
    reid_match_iou_threshold: float = 0.45
    reid_similarity_threshold: float = 0.9
    plate_model_path: str | None = None


@dataclass
class VehicleTrackState:
    track_id: int
    xyxy: list[int]
    signature: np.ndarray
    ocr_items: list[dict[str, Any]]
    plate_boxes: list[dict[str, Any]]
    last_ocr_frame: int | None = None
    last_ocr_confidence: float = 0.0


@dataclass(frozen=True)
class LetterboxMeta:
    scale: float
    pad_x: int
    pad_y: int
    width: int
    height: int


def resolve_device_token(raw_device: str) -> str:
    token = str(raw_device).strip().lower()
    if token in {"", "cpu", "cuda"}:
        return "cpu" if token in {"", "cpu"} else "cuda:0"
    if token.startswith("cuda:"):
        return token
    if token.isdigit():
        return f"cuda:{token}"
    return token


def resolve_devices(device_spec: str) -> list[str]:
    if not device_spec or device_spec.strip() == "":
        return ["cpu"]
    raw_devices = [item.strip() for item in device_spec.split(",") if item.strip()]
    if not raw_devices:
        return ["cpu"]
    resolved: list[str] = []
    for item in raw_devices:
        resolved.append(resolve_device_token(item))
    return resolved


def bound_queue_size(length: int, max_items: int) -> int:
    if max_items <= 0:
        return max(1, length)
    return min(length, max_items)


def resolve_flight_state_for_frame(
    frame_idx: int,
    telemetry_rows: list[dict[str, Any]] | None,
    *,
    default_latitude: float = 25.7650,
    default_longitude: float = -80.3710,
    default_altitude_m: float = 40.0,
    default_yaw_deg: float = 0.0,
    default_pitch_deg: float = 0.0,
    default_roll_deg: float = 0.0,
) -> dict[str, float]:
    if not telemetry_rows:
        return {
            "latitude": float(default_latitude),
            "longitude": float(default_longitude),
            "altitude_m": float(default_altitude_m),
            "yaw_deg": float(default_yaw_deg),
            "pitch_deg": float(default_pitch_deg),
            "roll_deg": float(default_roll_deg),
        }

    best_row = None
    best_delta = None
    for row in telemetry_rows:
        raw_frame_value = row.get("frame", row.get("srt_frame", -1))
        if raw_frame_value is None:
            frame_value = -1
        else:
            try:
                frame_value = int(float(raw_frame_value))
            except (TypeError, ValueError):
                continue
        if frame_value < 0:
            continue
        delta = abs(frame_value - int(frame_idx))
        if best_delta is None or delta < best_delta:
            best_row = row
            best_delta = delta

    if best_row is None:
        return {
            "latitude": float(default_latitude),
            "longitude": float(default_longitude),
            "altitude_m": float(default_altitude_m),
            "yaw_deg": float(default_yaw_deg),
            "pitch_deg": float(default_pitch_deg),
            "roll_deg": float(default_roll_deg),
        }

    latitude = best_row.get("latitude")
    longitude = best_row.get("longitude")
    altitude = best_row.get("altitude_m")
    if altitude is None:
        altitude = best_row.get("altitude")
    if altitude is None:
        altitude = best_row.get("height")
    if altitude is None:
        altitude = default_altitude_m
    yaw = best_row.get("yaw_deg")
    if yaw is None:
        yaw = best_row.get("yaw")
    if yaw is None:
        yaw = default_yaw_deg
    pitch = best_row.get("pitch_deg")
    if pitch is None:
        pitch = best_row.get("pitch")
    if pitch is None:
        pitch = default_pitch_deg
    roll = best_row.get("roll_deg")
    if roll is None:
        roll = best_row.get("roll")
    if roll is None:
        roll = default_roll_deg

    return {
        "latitude": float(latitude if latitude is not None else default_latitude),
        "longitude": float(longitude if longitude is not None else default_longitude),
        "altitude_m": float(altitude if altitude is not None else default_altitude_m),
        "yaw_deg": float(yaw if yaw is not None else default_yaw_deg),
        "pitch_deg": float(pitch if pitch is not None else default_pitch_deg),
        "roll_deg": float(roll if roll is not None else default_roll_deg),
    }


def load_telemetry_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            frame_value = row.get("frame")
            if frame_value is None and row.get("srt_frame") is not None:
                frame_value = row.get("srt_frame")
            if frame_value is None:
                continue
            try:
                frame_idx = int(float(frame_value))
            except (TypeError, ValueError):
                continue
            latitude = row.get("latitude")
            longitude = row.get("longitude")
            altitude_m = row.get("altitude_m")
            if altitude_m is None:
                altitude_m = row.get("altitude")
            if altitude_m is None:
                altitude_m = row.get("height")
            yaw_deg = row.get("yaw_deg")
            if yaw_deg is None:
                yaw_deg = row.get("yaw")
            pitch_deg = row.get("pitch_deg")
            if pitch_deg is None:
                pitch_deg = row.get("pitch")
            roll_deg = row.get("roll_deg")
            if roll_deg is None:
                roll_deg = row.get("roll")

            rows.append({
                "frame": frame_idx,
                "latitude": float(latitude if latitude is not None else 0.0),
                "longitude": float(longitude if longitude is not None else 0.0),
                "altitude_m": float(altitude_m if altitude_m is not None else 0.0),
                "yaw_deg": float(yaw_deg if yaw_deg is not None else 0.0),
                "pitch_deg": float(pitch_deg if pitch_deg is not None else 0.0),
                "roll_deg": float(roll_deg if roll_deg is not None else 0.0),
            })
    rows.sort(key=lambda item: int(item.get("frame", 0)))
    return rows


def nms_boxes(boxes: list[list[float]], scores: list[float], iou_threshold: float = 0.45) -> list[int]:
    if not boxes:
        return []
    order = sorted(range(len(boxes)), key=lambda idx: scores[idx], reverse=True)
    keep: list[int] = []
    while order:
        current = order.pop(0)
        keep.append(current)
        remaining = []
        for idx in order:
            if bbox_iou(boxes[current], boxes[idx]) < iou_threshold:
                remaining.append(idx)
        order = remaining
    return keep


def letterbox_image(image: np.ndarray, target_size: tuple[int, int]) -> tuple[np.ndarray, LetterboxMeta]:
    target_w, target_h = target_size
    height, width = image.shape[:2]
    scale = min(target_w / max(width, 1), target_h / max(height, 1))
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((target_h, target_w, 3), 114, dtype=np.uint8)
    pad_x = (target_w - new_w) // 2
    pad_y = (target_h - new_h) // 2
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    return canvas, LetterboxMeta(scale=scale, pad_x=pad_x, pad_y=pad_y, width=width, height=height)


def unletterbox_xyxy(xyxy: list[float], meta: LetterboxMeta) -> list[int]:
    x1, y1, x2, y2 = xyxy
    scale = max(meta.scale, 1e-6)
    x1 = (x1 - meta.pad_x) / scale
    y1 = (y1 - meta.pad_y) / scale
    x2 = (x2 - meta.pad_x) / scale
    y2 = (y2 - meta.pad_y) / scale
    return [
        max(0, min(meta.width, int(round(x1)))),
        max(0, min(meta.height, int(round(y1)))),
        max(0, min(meta.width, int(round(x2)))),
        max(0, min(meta.height, int(round(y2)))),
    ]


def yolox_predictions_to_candidates(prediction: np.ndarray, meta: LetterboxMeta, conf_threshold: float = 0.25, iou_threshold: float = 0.45) -> list[dict[str, Any]]:
    array = np.asarray(prediction)
    if array.ndim == 3:
        array = array[0]
    if array.ndim != 2 or array.shape[0] == 0:
        return []

    candidates: list[dict[str, Any]] = []
    for row in array:
        if row.shape[0] < 5:
            continue
        cx, cy, w, h = [float(v) for v in row[:4]]
        objectness = float(row[4])
        class_conf = float(np.max(row[5:])) if row.shape[0] > 5 else 1.0
        score = objectness * class_conf
        if score < conf_threshold:
            continue
        xyxy = [cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0]
        candidates.append({
            "xyxy": xyxy,
            "conf": score,
            "source": "roi_plate_model_box",
        })

    if not candidates:
        return []

    boxes = [item["xyxy"] for item in candidates]
    scores = [float(item["conf"]) for item in candidates]
    keep = nms_boxes(boxes, scores, iou_threshold=iou_threshold)
    output = []
    for idx in keep:
        candidate = dict(candidates[idx])
        candidate["xyxy"] = unletterbox_xyxy(candidate["xyxy"], meta)
        output.append(candidate)
    return output


class OnnxPlateDetector:
    def __init__(self, model_path: str):
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("onnxruntime is required for ONNX plate models") from exc

        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        input_shape = self.session.get_inputs()[0].shape
        height = int(input_shape[2]) if len(input_shape) >= 4 and isinstance(input_shape[2], int) else 640
        width = int(input_shape[3]) if len(input_shape) >= 4 and isinstance(input_shape[3], int) else 640
        self.input_size = (width, height)

    def predict(self, image: np.ndarray, conf_threshold: float = 0.25, iou_threshold: float = 0.45) -> list[dict[str, Any]]:
        letterboxed, meta = letterbox_image(image, self.input_size)
        tensor = letterboxed.astype(np.float32).transpose(2, 0, 1)[None, ...]
        outputs = self.session.run(None, {self.input_name: tensor})
        if not outputs:
            return []
        return yolox_predictions_to_candidates(outputs[0], meta, conf_threshold=conf_threshold, iou_threshold=iou_threshold)


class LazyModels:
    def __init__(self, device: str, plate_model_path: str | None = None):
        self.device = device
        self.plate_model_path = plate_model_path
        self._vehicle = None
        self._plate = None
        self._plate_onnx = None
        self._ocr = None

    def vehicle_model(self):
        if self._vehicle is None:
            from ultralytics import YOLO

            # Use the segmentation model as the vehicle detector so we can export masks,
            # instance-level footprints, and downstream flow/depth proxies alongside boxes.
            self._vehicle = YOLO(resolve_checkpoint("yolov8n-seg.pt"))
        return self._vehicle

    def plate_model(self):
        if self._plate is None:
            from ultralytics import YOLO

            checkpoint = self.plate_model_path or resolve_checkpoint("yolov8n.pt")
            self._plate = YOLO(checkpoint)
        return self._plate

    def plate_onnx_model(self):
        if self.plate_model_path is None:
            raise RuntimeError("plate_model_path is not set")
        if self._plate_onnx is None:
            self._plate_onnx = OnnxPlateDetector(self.plate_model_path)
        return self._plate_onnx

    def ocr_model(self):
        if self._ocr is None:
            import easyocr

            self._ocr = easyocr.Reader(["en"], gpu=self.device != "cpu")
        return self._ocr


VEHICLE_COLOR_LABELS = ["black", "white", "gray", "red", "orange", "yellow", "green", "blue", "purple"]


def laplacian_sharpness(img: np.ndarray) -> float:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def enhance_plate_crop(crop: np.ndarray) -> np.ndarray:
    # Lightweight enhancement for blurry plate regions before OCR.
    blurred = cv2.GaussianBlur(crop, (0, 0), 2.0)
    sharpened = cv2.addWeighted(crop, 1.6, blurred, -0.6, 0)
    return cv2.convertScaleAbs(sharpened, alpha=1.15, beta=4)


def expand_xyxy(xyxy: list[int], shape: tuple[int, int, int], padding_ratio: float = 0.12) -> list[int]:
    height, width = shape[:2]
    x1, y1, x2, y2 = xyxy
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    pad_x = int(box_w * padding_ratio)
    pad_y = int(box_h * padding_ratio)
    return [
        max(0, x1 - pad_x),
        max(0, y1 - pad_y),
        min(width, x2 + pad_x),
        min(height, y2 + pad_y),
    ]


def color_vote_from_patch(patch: np.ndarray) -> dict[str, float]:
    if patch.size == 0:
        return {"unknown": 1.0}

    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0].astype(np.float32)
    s = hsv[:, :, 1].astype(np.float32)
    v = hsv[:, :, 2].astype(np.float32)

    sat_mask = s >= 38.0
    bright_mask = v >= 200.0
    dark_mask = v < 55.0

    scores = {label: 0.0 for label in VEHICLE_COLOR_LABELS}
    scores["black"] = float(dark_mask.mean())
    scores["white"] = float((bright_mask & (s < 60.0)).mean())
    scores["gray"] = float(((~dark_mask) & (s < 45.0) & (~bright_mask)).mean())

    hue_ranges = {
        "red": ((h < 10.0) | (h >= 170.0)) & sat_mask,
        "orange": ((h >= 10.0) & (h < 25.0)) & sat_mask,
        "yellow": ((h >= 25.0) & (h < 35.0)) & sat_mask,
        "green": ((h >= 35.0) & (h < 85.0)) & sat_mask,
        "blue": ((h >= 85.0) & (h < 130.0)) & sat_mask,
        "purple": ((h >= 130.0) & (h < 160.0)) & sat_mask,
    }

    for label, mask in hue_ranges.items():
        scores[label] = float(mask.mean())

    total = sum(scores.values()) or 1.0
    return {label: score / total for label, score in scores.items()}


def dominant_color_name(img: np.ndarray) -> str:
    if img.size == 0:
        return "unknown"

    crop = img
    if crop.shape[0] > 12 and crop.shape[1] > 12:
        h, w = crop.shape[:2]
        inner_y1 = int(h * 0.18)
        inner_y2 = int(h * 0.82)
        inner_x1 = int(w * 0.12)
        inner_x2 = int(w * 0.88)
        crop = crop[inner_y1:inner_y2, inner_x1:inner_x2]

    votes = color_vote_from_patch(crop)
    if not votes:
        return "unknown"
    return max(votes.items(), key=lambda item: item[1])[0]


def bbox_iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = [int(v) for v in a[:4]]
    bx1, by1, bx2, by2 = [int(v) for v in b[:4]]
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter_area = float((inter_x2 - inter_x1) * (inter_y2 - inter_y1))
    a_area = float(max(1, (ax2 - ax1) * (ay2 - ay1)))
    b_area = float(max(1, (bx2 - bx1) * (by2 - by1)))
    return inter_area / max(1.0, a_area + b_area - inter_area)


def build_track_roi(track_xyxy: list[int], frame_shape: tuple[int, int, int], *, margin_ratio: float = 0.35, min_side: int = 160) -> list[int]:
    height, width = frame_shape[:2]
    x1, y1, x2, y2 = [int(v) for v in track_xyxy[:4]]
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    margin_x = max(int(box_w * margin_ratio), 12)
    margin_y = max(int(box_h * margin_ratio), 12)
    roi_x1 = max(0, x1 - margin_x)
    roi_y1 = max(0, y1 - margin_y)
    roi_x2 = min(width, x2 + margin_x)
    roi_y2 = min(height, y2 + margin_y)
    roi_w = max(roi_x2 - roi_x1, min_side)
    roi_h = max(roi_y2 - roi_y1, min_side)
    center_x = (roi_x1 + roi_x2) / 2.0
    center_y = (roi_y1 + roi_y2) / 2.0
    roi_x1 = max(0, int(round(center_x - roi_w / 2.0)))
    roi_y1 = max(0, int(round(center_y - roi_h / 2.0)))
    roi_x2 = min(width, int(round(center_x + roi_w / 2.0)))
    roi_y2 = min(height, int(round(center_y + roi_h / 2.0)))
    return [roi_x1, roi_y1, roi_x2, roi_y2]


def roi_candidates_from_tracks(
    frame: np.ndarray,
    previous_tracks: list[VehicleTrackState],
    *,
    margin_ratio: float = 0.35,
    min_side: int = 160,
) -> list[tuple[int, list[int], list[int]]]:
    rois: list[tuple[int, list[int], list[int]]] = []
    for track in previous_tracks:
        roi = build_track_roi(track.xyxy, frame.shape, margin_ratio=margin_ratio, min_side=min_side)
        rois.append((track.track_id, track.xyxy, roi))
    return rois


def frame_difference_score(prev_gray: np.ndarray | None, curr_gray: np.ndarray) -> float:
    if prev_gray is None or curr_gray.size == 0:
        return 1.0
    if prev_gray.shape != curr_gray.shape:
        curr_gray = cv2.resize(curr_gray, prev_gray.shape[::-1])
    diff = cv2.absdiff(prev_gray, curr_gray)
    return float(diff.mean() / 255.0)


def vehicle_signature(frame: np.ndarray, xyxy: list[int]) -> np.ndarray:
    x1, y1, x2, y2 = [int(v) for v in xyxy[:4]]
    crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
    if crop.size == 0:
        return np.zeros((16, 16), dtype=np.uint8)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
    return resized.astype(np.uint8)


def signature_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    diff = np.abs(a.astype(np.float32) - b.astype(np.float32)).mean() / 255.0
    return float(max(0.0, 1.0 - diff))


def remap_xyxy(source_xyxy: list[int], source_vehicle_xyxy: list[int], target_vehicle_xyxy: list[int], frame_shape: tuple[int, int, int]) -> list[int]:
    sx1, sy1, sx2, sy2 = [int(v) for v in source_vehicle_xyxy[:4]]
    tx1, ty1, tx2, ty2 = [int(v) for v in target_vehicle_xyxy[:4]]
    bx1, by1, bx2, by2 = [int(v) for v in source_xyxy[:4]]
    src_w = max(1, sx2 - sx1)
    src_h = max(1, sy2 - sy1)
    dst_w = max(1, tx2 - tx1)
    dst_h = max(1, ty2 - ty1)

    rel_x1 = (bx1 - sx1) / src_w
    rel_y1 = (by1 - sy1) / src_h
    rel_x2 = (bx2 - sx1) / src_w
    rel_y2 = (by2 - sy1) / src_h

    nx1 = int(round(tx1 + rel_x1 * dst_w))
    ny1 = int(round(ty1 + rel_y1 * dst_h))
    nx2 = int(round(tx1 + rel_x2 * dst_w))
    ny2 = int(round(ty1 + rel_y2 * dst_h))

    height, width = frame_shape[:2]
    return [max(0, min(width, nx1)), max(0, min(height, ny1)), max(0, min(width, nx2)), max(0, min(height, ny2))]


def remap_ocr_items(
    ocr_items: list[dict[str, Any]],
    source_vehicle_xyxy: list[int],
    target_vehicle_xyxy: list[int],
    frame_shape: tuple[int, int, int],
    track_id: int,
) -> list[dict[str, Any]]:
    remapped = []
    for item in ocr_items:
        remapped_item = dict(item)
        remapped_item["xyxy"] = remap_xyxy(item.get("xyxy", [0, 0, 0, 0]), source_vehicle_xyxy, target_vehicle_xyxy, frame_shape)
        remapped_item["track_id"] = track_id
        remapped_item["reused_from_track"] = True
        remapped.append(remapped_item)
    return remapped


def match_previous_track(
    xyxy: list[int],
    signature: np.ndarray,
    previous_tracks: list[VehicleTrackState],
    used_track_ids: set[int],
    tuning: RuntimeTuning,
) -> VehicleTrackState | None:
    best_track = None
    best_score = -1.0
    for track in previous_tracks:
        if track.track_id in used_track_ids:
            continue
        overlap = bbox_iou(xyxy, track.xyxy)
        if overlap < tuning.reid_match_iou_threshold:
            continue
        similarity = signature_similarity(signature, track.signature)
        if similarity < tuning.reid_similarity_threshold:
            continue
        score = overlap * 0.6 + similarity * 0.4
        if score > best_score:
            best_score = score
            best_track = track
    return best_track


def assign_vehicle_tracks(
    vehicle_boxes: list[dict[str, Any]],
    frame: np.ndarray,
    previous_tracks: list[VehicleTrackState],
    tuning: RuntimeTuning,
    next_track_id: int,
) -> tuple[list[VehicleTrackState], int]:
    current_tracks: list[VehicleTrackState] = []
    used_track_ids: set[int] = set()
    for vehicle in vehicle_boxes:
        signature = vehicle_signature(frame, vehicle["xyxy"])
        matched_track = match_previous_track(vehicle["xyxy"], signature, previous_tracks, used_track_ids, tuning)
        track_id = matched_track.track_id if matched_track is not None else next_track_id
        if matched_track is None:
            next_track_id += 1
        else:
            used_track_ids.add(track_id)
        vehicle["track_id"] = track_id
        current_tracks.append(
            VehicleTrackState(
                track_id=track_id,
                xyxy=list(vehicle["xyxy"]),
                signature=signature,
                ocr_items=(matched_track.ocr_items if matched_track is not None else []),
                plate_boxes=(matched_track.plate_boxes if matched_track is not None else []),
                last_ocr_frame=(matched_track.last_ocr_frame if matched_track is not None else None),
                last_ocr_confidence=(matched_track.last_ocr_confidence if matched_track is not None else 0.0),
            )
        )
    return current_tracks, next_track_id


def reuse_track_ocr(
    track: VehicleTrackState | None,
    target_vehicle_xyxy: list[int],
    frame_shape: tuple[int, int, int],
) -> list[dict[str, Any]]:
    if track is None or not track.ocr_items:
        return []
    return remap_ocr_items(track.ocr_items, track.xyxy, target_vehicle_xyxy, frame_shape, track.track_id)


def attach_track_ids_to_ocr_items(ocr_items: list[dict[str, Any]], vehicle_boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for item in ocr_items:
        best_track_id = int(item.get("track_id", 0))
        best_iou = -1.0
        for vehicle in vehicle_boxes:
            overlap = bbox_iou(item.get("xyxy", [0, 0, 0, 0]), vehicle.get("xyxy", [0, 0, 0, 0]))
            if overlap > best_iou:
                best_iou = overlap
                best_track_id = int(vehicle.get("track_id", 0))
        enriched_item = dict(item)
        enriched_item["track_id"] = best_track_id
        enriched.append(enriched_item)
    return enriched


def dedupe_plate_boxes(plate_boxes: list[dict[str, Any]], max_candidates: int) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for plate_box in sorted(plate_boxes, key=lambda item: item["conf"], reverse=True):
        key = tuple(int(v) for v in plate_box["xyxy"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(plate_box)
        if len(deduped) >= max_candidates:
            break
    return deduped


def merge_plate_boxes(
    model_boxes: list[dict[str, Any]],
    vehicle_boxes: list[dict[str, Any]],
    *,
    max_candidates: int,
) -> list[dict[str, Any]]:
    prioritized = list(vehicle_boxes)
    if not vehicle_boxes:
        prioritized.extend(model_boxes)
    return dedupe_plate_boxes(prioritized, max_candidates=max_candidates)


def map_roi_xyxy_to_frame(roi_xyxy: list[int], roi_origin: tuple[int, int], frame_shape: tuple[int, int, int]) -> list[int]:
    offset_x, offset_y = roi_origin
    x1, y1, x2, y2 = [int(v) for v in roi_xyxy[:4]]
    height, width = frame_shape[:2]
    return [
        max(0, min(width, x1 + offset_x)),
        max(0, min(height, y1 + offset_y)),
        max(0, min(width, x2 + offset_x)),
        max(0, min(height, y2 + offset_y)),
    ]


def roi_quad_to_frame(quad: np.ndarray, roi_origin: tuple[int, int]) -> list[list[float]]:
    offset_x, offset_y = roi_origin
    points = np.asarray(quad, dtype=np.float32).reshape(-1, 2).copy()
    points[:, 0] += float(offset_x)
    points[:, 1] += float(offset_y)
    return [[float(x), float(y)] for x, y in points.tolist()]


def extract_plate_candidates_with_roi_model(
    frame: np.ndarray,
    vehicle_xyxy: list[int],
    models: LazyModels,
    device: str,
    *,
    max_candidates: int,
) -> list[dict[str, Any]]:
    x1, y1, x2, y2 = [int(v) for v in vehicle_xyxy[:4]]
    if x2 <= x1 or y2 <= y1:
        return []

    roi = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
    if roi.size == 0:
        return []

    try:
        if models.plate_model_path and str(models.plate_model_path).lower().endswith(".onnx"):
            proposals = []
            for proposal in models.plate_onnx_model().predict(roi):
                item = dict(proposal)
                item["xyxy"] = map_roi_xyxy_to_frame(item["xyxy"], (x1, y1), frame.shape)
                proposals.append(item)
        else:
            result = models.plate_model().predict([roi], device=device, verbose=False)[0]
            proposals = []
            masks_xy = getattr(getattr(result, "masks", None), "xy", None)
            for idx, box in enumerate(getattr(result, "boxes", None) or []):
                conf = float(box.conf.item())
                roi_xyxy = [int(v) for v in box.xyxy[0].tolist()]
                proposal = {
                    "xyxy": map_roi_xyxy_to_frame(roi_xyxy, (x1, y1), frame.shape),
                    "conf": conf,
                    "source": "roi_plate_model_box",
                }
                if masks_xy is not None and idx < len(masks_xy):
                    polygon = np.asarray(masks_xy[idx], dtype=np.float32)
                    if polygon.ndim == 2 and polygon.shape[0] >= 4:
                        rect = cv2.minAreaRect(polygon)
                        quad = cv2.boxPoints(rect)
                        proposal["quad"] = roi_quad_to_frame(quad, (x1, y1))
                        proposal["source"] = "roi_plate_model_segment"
                proposals.append(proposal)
    except Exception as exc:
        logger.warning("ROI plate model failed on vehicle crop: %s", exc)
        return []

    return dedupe_plate_boxes(proposals, max_candidates=max_candidates)


def should_run_ocr(frame_idx: int, tuning: RuntimeTuning) -> bool:
    return frame_idx % max(1, tuning.ocr_frame_interval) == 0


def should_refresh_track_ocr(
    track: VehicleTrackState | None,
    *,
    frame_idx: int,
    tuning: RuntimeTuning,
    min_confidence: float = 0.85,
    max_recent_frame_gap: int | None = None,
) -> bool:
    if track is None:
        return True
    if track.last_ocr_frame is None:
        return True
    if max_recent_frame_gap is None:
        max_recent_frame_gap = max(1, tuning.ocr_frame_interval)
    if track.last_ocr_confidence >= min_confidence and (frame_idx - track.last_ocr_frame) < max_recent_frame_gap:
        return False
    return True


def run_plate_ocr(
    frame: np.ndarray,
    plate_boxes: list[dict[str, Any]],
    models: LazyModels,
    tuning: RuntimeTuning,
) -> tuple[list[dict[str, Any]], int]:
    ocr_items: list[dict[str, Any]] = []
    ocr_attempts = 0

    for plate_box in plate_boxes[: max(1, tuning.max_ocr_crops)]:
        crop = extract_plate_crop(frame, plate_box)
        if crop.size == 0:
            continue

        crop_area = int(crop.shape[0] * crop.shape[1])
        if crop_area < max(1, tuning.min_plate_crop_area):
            continue

        ocr_attempts += 1
        sharpness = laplacian_sharpness(crop)
        texts_raw = models.ocr_model().readtext(crop, detail=1)

        combined = []
        for entry in texts_raw:
            if len(entry) >= 3:
                _, txt, conf = entry
                combined.append({"text": str(txt), "conf": float(conf)})

        top = select_best_plate_candidate(combined)
        needs_enhanced_pass = not top["text"] or float(top["confidence"]) < tuning.enhanced_ocr_confidence_threshold
        if needs_enhanced_pass:
            enhanced = enhance_plate_crop(crop)
            texts_enh = models.ocr_model().readtext(enhanced, detail=1)
            for entry in texts_enh:
                if len(entry) >= 3:
                    _, txt, conf = entry
                    combined.append({"text": str(txt), "conf": float(conf)})
            top = select_best_plate_candidate(combined)

        if top["text"]:
            ocr_conf = top["confidence"]
        else:
            ocr_conf = 0.0

        combined = sorted(combined, key=lambda item: item["conf"], reverse=True)[:5]
        ocr_items.append(
            {
                "xyxy": plate_box["xyxy"],
                "source": plate_box.get("source", "unknown"),
                "quad": plate_box.get("quad"),
                "crop_shape": [int(crop.shape[1]), int(crop.shape[0])],
                "plate_conf": plate_box["conf"],
                "sharpness": sharpness,
                "ocr_text": top["text"],
                "ocr_conf": ocr_conf,
                "ocr_candidates": combined,
            }
        )

    return ocr_items, ocr_attempts


def estimate_optical_flow_depth(prev_frame: np.ndarray | None, curr_frame: np.ndarray, xyxy: list[int]) -> tuple[float, float]:
    if prev_frame is None or curr_frame.size == 0:
        return 0.0, 0.0

    x1, y1, x2, y2 = [int(v) for v in xyxy[:4]]
    if x2 <= x1 or y2 <= y1:
        return 0.0, 0.0

    prev_roi = prev_frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
    curr_roi = curr_frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
    if prev_roi.size == 0 or curr_roi.size == 0:
        return 0.0, 0.0

    prev_gray = cv2.cvtColor(prev_roi, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(curr_roi, cv2.COLOR_BGR2GRAY)
    if prev_gray.shape != curr_gray.shape:
        curr_gray = cv2.resize(curr_gray, prev_gray.shape[::-1])

    flow = cv2.calcOpticalFlowFarneback(prev_gray, curr_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    avg_mag = float(magnitude.mean())
    depth_proxy = float(max(0.0, 1.5 * avg_mag / 10.0))
    return avg_mag, depth_proxy


def video_metadata(video_path: Path) -> dict[str, float | int | str | None]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video: {video_path}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_sec = float(frame_count / fps) if fps > 0 else 0.0
    cap.release()

    return {
        "path": str(video_path),
        "width": width,
        "height": height,
        "fps": fps,
        "frame_count": frame_count,
        "duration_sec": duration_sec,
        "resolution": f"{width}x{height}",
    }


def iter_sampled_frames(video_path: Path, frame_step: int):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video: {video_path}")

    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % frame_step == 0:
            yield idx, frame
        idx += 1

    cap.release()


def run_video(
    video_path: Path,
    output_dir: Path,
    device: str,
    frame_step: int,
    batch_size: int,
    tuning: RuntimeTuning,
    telemetry_path: Path | None = None,
) -> StageMetrics:
    t0 = time.perf_counter()
    models = LazyModels(device, plate_model_path=tuning.plate_model_path)
    metadata = video_metadata(video_path)
    logger.info(
        "Video metadata: %s | resolution=%s | fps=%.2f | frames=%d | duration_sec=%.2f | frame_step=%d | batch_size=%d",
        video_path.name,
        metadata["resolution"],
        float(metadata["fps"]),
        int(metadata["frame_count"]),
        float(metadata["duration_sec"]),
        frame_step,
        batch_size,
    )

    detections_path = output_dir / f"{video_path.stem}.detections.jsonl"
    metrics_path = output_dir / f"{video_path.stem}.metrics.json"

    queue_limit = bound_queue_size(batch_size, max(4, min(32, batch_size)))
    frames = []
    frame_ids = []
    frames_read = 0
    frames_processed = 0
    detections_vehicle = 0
    detections_plate = 0
    ocr_attempts = 0

    read_ms = 0.0
    detect_ms = 0.0
    ocr_ms = 0.0
    post_ms = 0.0

    total_frames = 0
    cap_probe = cv2.VideoCapture(str(video_path))
    if cap_probe.isOpened():
        total_frames = int(cap_probe.get(cv2.CAP_PROP_FRAME_COUNT))
        cap_probe.release()
    if total_frames <= 0:
        total_frames = None

    prev_frame_gray = None
    previous_tracks: list[VehicleTrackState] = []
    next_track_id = 1
    telemetry_rows = load_telemetry_rows(telemetry_path)
    logger.info("Processing video %s (frame_step=%s, total_frames_hint=%s, telemetry_rows=%d)", video_path.name, frame_step, total_frames, len(telemetry_rows))
    with detections_path.open("w", encoding="utf-8") as out:
        for frame_idx, frame in tqdm(
            iter_sampled_frames(video_path, frame_step),
            total=total_frames // max(frame_step, 1) if total_frames else None,
            unit="frame",
            desc=f"{video_path.stem}",
            leave=False,
            file=sys.stderr,
        ):
            r0 = time.perf_counter()
            frames_read += 1
            read_ms += (time.perf_counter() - r0) * 1000

            frames.append(frame)
            frame_ids.append(frame_idx)

            if len(frames) < queue_limit:
                continue

            d0 = time.perf_counter()
            vehicle_results = models.vehicle_model().predict(
                frames, device=device, verbose=False
            )
            if tuning.use_full_frame_plate_detector:
                plate_results = models.plate_model().predict(frames, device=device, verbose=False)
            else:
                plate_results = [None] * len(frames)
            detect_ms += (time.perf_counter() - d0) * 1000

            for i, (v_res, p_res) in enumerate(zip(vehicle_results, plate_results)):
                frame_idx = frame_ids[i]
                frames_processed += 1
                current_frame = frames[i]
                current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
                frame_diff_score = frame_difference_score(prev_frame_gray, current_gray)
                frame_is_static = frame_diff_score <= tuning.reid_frame_diff_threshold
                flow_magnitude = 0.0
                depth_proxy = 0.0
                if prev_frame_gray is not None:
                    flow = cv2.calcOpticalFlowFarneback(prev_frame_gray, current_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                    mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                    flow_magnitude = float(mag.mean())
                    depth_proxy = float(max(0.0, 1.5 * flow_magnitude / 10.0))

                if previous_tracks:
                    track_rois = roi_candidates_from_tracks(current_frame, previous_tracks)
                else:
                    track_rois = []

                flight_state = resolve_flight_state_for_frame(frame_idx, telemetry_rows)

                v_boxes = []
                if getattr(v_res, "boxes", None) is not None:
                    for b_idx, b in enumerate(v_res.boxes):
                        cls_id = int(b.cls.item())
                        conf = float(b.conf.item())
                        xyxy = [int(x) for x in b.xyxy[0].tolist()]
                        if cls_id in {2, 3, 5, 7}:
                            box_in_track_roi = any(
                                roi[0] <= xyxy[0] and roi[1] <= xyxy[1] and roi[2] >= xyxy[2] and roi[3] >= xyxy[3]
                                for _, _, roi in track_rois
                            )
                            if previous_tracks and not box_in_track_roi:
                                continue
                            padded_xyxy = expand_xyxy(xyxy, current_frame.shape, padding_ratio=0.16)
                            x1, y1, x2, y2 = padded_xyxy
                            patch = current_frame[y1:y2, x1:x2]
                            bbox_area = max(1, (x2 - x1) * (y2 - y1))
                            frame_area = max(1, current_frame.shape[0] * current_frame.shape[1])
                            obj_flow = flow_magnitude
                            if getattr(v_res, "masks", None) is not None and b_idx < len(v_res.masks.data):
                                mask = v_res.masks.data[b_idx]
                                if hasattr(mask, "shape") and mask.shape:
                                    obj_flow = float((mask.float().mean() if hasattr(mask, "float") else mask.mean())) * flow_magnitude
                            geo_estimate = estimate_object_geolocation(
                                latitude=flight_state["latitude"],
                                longitude=flight_state["longitude"],
                                altitude_m=flight_state["altitude_m"],
                                center_x_norm=(xyxy[0] + xyxy[2]) / (2 * max(1, current_frame.shape[1])),
                                center_y_norm=(xyxy[1] + xyxy[3]) / (2 * max(1, current_frame.shape[0])),
                                flow_magnitude_px=float(obj_flow),
                                depth_proxy_m=float(max(0.0, 1.5 * obj_flow / 10.0)),
                                yaw_deg=flight_state["yaw_deg"],
                                pitch_deg=flight_state["pitch_deg"],
                                roll_deg=flight_state["roll_deg"],
                            )
                            v_boxes.append(
                                {
                                    "class_id": cls_id,
                                    "class_name": vehicle_class_name_from_id(cls_id),
                                    "conf": conf,
                                    "xyxy": xyxy,
                                    "xyxy_padded": padded_xyxy,
                                    "color": dominant_color_name(patch),
                                    "color_votes": color_vote_from_patch(patch),
                                    "bbox_area": bbox_area,
                                    "bbox_area_ratio": round(float(bbox_area / frame_area), 6),
                                    "make_model_guess": None,
                                    "flow_magnitude": round(float(obj_flow), 4),
                                    "depth_proxy_m": round(float(max(0.0, 1.5 * obj_flow / 10.0)), 4),
                                    "geo_proxy": geo_estimate,
                                }
                            )
                if not v_boxes and previous_tracks:
                    for track_id, prev_xyxy, roi in track_rois:
                        roi_frame = current_frame[max(0, roi[1]):max(0, roi[3]), max(0, roi[0]):max(0, roi[2])]
                        if roi_frame.size == 0:
                            continue
                        roi_result = models.vehicle_model().predict(roi_frame, device=device, verbose=False)
                        for res in roi_result:
                            if getattr(res, "boxes", None) is None:
                                continue
                            for b in res.boxes:
                                cls_id = int(b.cls.item())
                                if cls_id not in {2, 3, 5, 7}:
                                    continue
                                xyxy = [int(x) for x in b.xyxy[0].tolist()]
                                xyxy = [xyxy[0] + roi[0], xyxy[1] + roi[1], xyxy[2] + roi[0], xyxy[3] + roi[1]]
                                v_boxes.append({
                                    "class_id": cls_id,
                                    "class_name": vehicle_class_name_from_id(cls_id),
                                    "conf": float(b.conf.item()),
                                    "xyxy": xyxy,
                                    "xyxy_padded": expand_xyxy(xyxy, current_frame.shape, padding_ratio=0.16),
                                    "color": dominant_color_name(current_frame[max(0, xyxy[1]):max(0, xyxy[3]), max(0, xyxy[0]):max(0, xyxy[2])]),
                                    "color_votes": {},
                                    "bbox_area": max(1, (xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1])),
                                    "bbox_area_ratio": 0.0,
                                    "make_model_guess": None,
                                    "flow_magnitude": round(float(flow_magnitude), 4),
                                    "depth_proxy_m": round(float(depth_proxy), 4),
                                    "geo_proxy": estimate_object_geolocation(
                                        latitude=flight_state["latitude"],
                                        longitude=flight_state["longitude"],
                                        altitude_m=flight_state["altitude_m"],
                                        center_x_norm=(xyxy[0] + xyxy[2]) / (2 * max(1, current_frame.shape[1])),
                                        center_y_norm=(xyxy[1] + xyxy[3]) / (2 * max(1, current_frame.shape[0])),
                                        flow_magnitude_px=float(flow_magnitude),
                                        depth_proxy_m=float(depth_proxy),
                                        yaw_deg=flight_state["yaw_deg"],
                                        pitch_deg=flight_state["pitch_deg"],
                                        roll_deg=flight_state["roll_deg"],
                                    ),
                                })
                detections_vehicle += len(v_boxes)
                current_tracks, next_track_id = assign_vehicle_tracks(v_boxes, current_frame, previous_tracks, tuning, next_track_id)

                model_plate_boxes = []
                if p_res is not None and getattr(p_res, "boxes", None) is not None:
                    for b in p_res.boxes:
                        conf = float(b.conf.item())
                        xyxy = [int(x) for x in b.xyxy[0].tolist()]
                        model_plate_boxes.append({"conf": conf, "xyxy": xyxy})

                vehicle_plate_boxes = []
                for vehicle in v_boxes:
                    if tuning.prefer_roi_plate_model and tuning.plate_model_path:
                        vehicle_plate_boxes.extend(
                            extract_plate_candidates_with_roi_model(
                                current_frame,
                                vehicle["xyxy"],
                                models,
                                device,
                                max_candidates=3,
                            )
                        )
                    for candidate in extract_plate_candidates_from_vehicle(current_frame, vehicle["xyxy"], frame_shape=current_frame.shape, max_candidates=3):
                        vehicle_plate_boxes.append(dict(candidate))

                p_boxes = merge_plate_boxes(
                    model_plate_boxes,
                    vehicle_plate_boxes,
                    max_candidates=tuning.max_plate_boxes,
                )
                detections_plate += len(p_boxes)

                ocr_items = []
                if frame_is_static:
                    for vehicle in v_boxes:
                        matched_track = next((track for track in previous_tracks if track.track_id == int(vehicle.get("track_id", 0))), None)
                        if matched_track is None:
                            continue
                        ocr_items.extend(reuse_track_ocr(matched_track, vehicle["xyxy"], current_frame.shape))

                eligible_tracks = [
                    track for track in current_tracks if should_refresh_track_ocr(track, frame_idx=frame_idx, tuning=tuning)
                ]

                if p_boxes and not ocr_items and eligible_tracks and should_run_ocr(frame_idx, tuning):
                    o0 = time.perf_counter()
                    ocr_items, batch_ocr_attempts = run_plate_ocr(current_frame, p_boxes, models, tuning)
                    ocr_items = attach_track_ids_to_ocr_items(ocr_items, v_boxes)
                    for track in current_tracks:
                        track_ocr = [dict(item) for item in ocr_items if int(item.get("track_id", track.track_id)) == track.track_id]
                        if track_ocr:
                            track.last_ocr_frame = frame_idx
                            track.last_ocr_confidence = max((float(item.get("ocr_conf", 0.0)) for item in track_ocr), default=0.0)
                            track.ocr_items = track_ocr
                    ocr_attempts += batch_ocr_attempts
                    ocr_ms += (time.perf_counter() - o0) * 1000

                for track in current_tracks:
                    if not track.ocr_items:
                        track.ocr_items = [dict(item) for item in ocr_items if int(item.get("track_id", track.track_id)) == track.track_id] if ocr_items else []
                    track.plate_boxes = [dict(box) for box in p_boxes]

                p0 = time.perf_counter()
                record = {
                    "video": video_path.name,
                    "frame": frame_idx,
                    "srt_frame_hint": frame_idx + 1,
                    "timestamp_sec": float(frame_idx) / 30.0,
                    "device": device,
                    "vehicle_boxes": v_boxes,
                    "plate_boxes": p_boxes,
                    "ocr": ocr_items,
                    "optical_flow_mean_px": round(float(flow_magnitude), 4),
                    "depth_proxy_m": round(float(depth_proxy), 4),
                    "frame_diff_score": round(float(frame_diff_score), 6),
                }
                out.write(json.dumps(record) + "\n")
                post_ms += (time.perf_counter() - p0) * 1000

                prev_frame_gray = current_gray
                previous_tracks = current_tracks

            frames = []
            frame_ids = []

        # Flush remaining frames
        if frames:
            d0 = time.perf_counter()
            vehicle_results = models.vehicle_model().predict(frames, device=device, verbose=False)
            if tuning.use_full_frame_plate_detector:
                plate_results = models.plate_model().predict(frames, device=device, verbose=False)
            else:
                plate_results = [None] * len(frames)
            detect_ms += (time.perf_counter() - d0) * 1000

            for i, (v_res, p_res) in enumerate(zip(vehicle_results, plate_results)):
                frame_idx = frame_ids[i]
                frames_processed += 1
                current_frame = frames[i]
                current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
                frame_diff_score = frame_difference_score(prev_frame_gray, current_gray)
                frame_is_static = frame_diff_score <= tuning.reid_frame_diff_threshold
                flow_magnitude = 0.0
                depth_proxy = 0.0
                if prev_frame_gray is not None:
                    flow = cv2.calcOpticalFlowFarneback(prev_frame_gray, current_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                    mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                    flow_magnitude = float(mag.mean())
                    depth_proxy = float(max(0.0, 1.5 * flow_magnitude / 10.0))

                flight_state = resolve_flight_state_for_frame(frame_idx, telemetry_rows)
                v_boxes = []
                if getattr(v_res, "boxes", None) is not None:
                    for b_idx, b in enumerate(v_res.boxes):
                        cls_id = int(b.cls.item())
                        conf = float(b.conf.item())
                        xyxy = [int(x) for x in b.xyxy[0].tolist()]
                        if cls_id in {2, 3, 5, 7}:
                            padded_xyxy = expand_xyxy(xyxy, current_frame.shape, padding_ratio=0.16)
                            x1, y1, x2, y2 = padded_xyxy
                            patch = current_frame[y1:y2, x1:x2]
                            bbox_area = max(1, (x2 - x1) * (y2 - y1))
                            frame_area = max(1, current_frame.shape[0] * current_frame.shape[1])
                            obj_flow = flow_magnitude
                            if getattr(v_res, "masks", None) is not None and b_idx < len(v_res.masks.data):
                                mask = v_res.masks.data[b_idx]
                                if hasattr(mask, "shape") and mask.shape:
                                    obj_flow = float((mask.float().mean() if hasattr(mask, "float") else mask.mean())) * flow_magnitude
                            geo_estimate = estimate_object_geolocation(
                                latitude=flight_state["latitude"],
                                longitude=flight_state["longitude"],
                                altitude_m=flight_state["altitude_m"],
                                center_x_norm=(xyxy[0] + xyxy[2]) / (2 * max(1, current_frame.shape[1])),
                                center_y_norm=(xyxy[1] + xyxy[3]) / (2 * max(1, current_frame.shape[0])),
                                flow_magnitude_px=float(obj_flow),
                                depth_proxy_m=float(max(0.0, 1.5 * obj_flow / 10.0)),
                                yaw_deg=flight_state["yaw_deg"],
                                pitch_deg=flight_state["pitch_deg"],
                                roll_deg=flight_state["roll_deg"],
                            )
                            v_boxes.append(
                                {
                                    "class_id": cls_id,
                                    "class_name": vehicle_class_name_from_id(cls_id),
                                    "conf": conf,
                                    "xyxy": xyxy,
                                    "xyxy_padded": padded_xyxy,
                                    "color": dominant_color_name(patch),
                                    "color_votes": color_vote_from_patch(patch),
                                    "bbox_area": bbox_area,
                                    "bbox_area_ratio": round(float(bbox_area / frame_area), 6),
                                    "make_model_guess": None,
                                    "flow_magnitude": round(float(obj_flow), 4),
                                    "depth_proxy_m": round(float(max(0.0, 1.5 * obj_flow / 10.0)), 4),
                                    "geo_proxy": geo_estimate,
                                }
                            )
                detections_vehicle += len(v_boxes)
                current_tracks, next_track_id = assign_vehicle_tracks(v_boxes, current_frame, previous_tracks, tuning, next_track_id)

                model_plate_boxes = []
                if p_res is not None and getattr(p_res, "boxes", None) is not None:
                    for b in p_res.boxes:
                        conf = float(b.conf.item())
                        xyxy = [int(x) for x in b.xyxy[0].tolist()]
                        model_plate_boxes.append({"conf": conf, "xyxy": xyxy})

                vehicle_plate_boxes = []
                for vehicle in v_boxes:
                    if tuning.prefer_roi_plate_model and tuning.plate_model_path:
                        vehicle_plate_boxes.extend(
                            extract_plate_candidates_with_roi_model(
                                current_frame,
                                vehicle["xyxy"],
                                models,
                                device,
                                max_candidates=3,
                            )
                        )
                    for candidate in extract_plate_candidates_from_vehicle(current_frame, vehicle["xyxy"], frame_shape=current_frame.shape, max_candidates=3):
                        vehicle_plate_boxes.append(dict(candidate))

                p_boxes = merge_plate_boxes(
                    model_plate_boxes,
                    vehicle_plate_boxes,
                    max_candidates=tuning.max_plate_boxes,
                )
                detections_plate += len(p_boxes)

                ocr_items = []
                if frame_is_static:
                    for vehicle in v_boxes:
                        matched_track = next((track for track in previous_tracks if track.track_id == int(vehicle.get("track_id", 0))), None)
                        if matched_track is None:
                            continue
                        ocr_items.extend(reuse_track_ocr(matched_track, vehicle["xyxy"], current_frame.shape))

                eligible_tracks = [
                    track for track in current_tracks if should_refresh_track_ocr(track, frame_idx=frame_idx, tuning=tuning)
                ]

                if p_boxes and not ocr_items and eligible_tracks and should_run_ocr(frame_idx, tuning):
                    o0 = time.perf_counter()
                    ocr_items, batch_ocr_attempts = run_plate_ocr(current_frame, p_boxes, models, tuning)
                    ocr_items = attach_track_ids_to_ocr_items(ocr_items, v_boxes)
                    for track in current_tracks:
                        track_ocr = [dict(item) for item in ocr_items if int(item.get("track_id", track.track_id)) == track.track_id]
                        if track_ocr:
                            track.last_ocr_frame = frame_idx
                            track.last_ocr_confidence = max((float(item.get("ocr_conf", 0.0)) for item in track_ocr), default=0.0)
                            track.ocr_items = track_ocr
                    ocr_attempts += batch_ocr_attempts
                    ocr_ms += (time.perf_counter() - o0) * 1000

                for track in current_tracks:
                    if not track.ocr_items:
                        track.ocr_items = [dict(item) for item in ocr_items if int(item.get("track_id", track.track_id)) == track.track_id] if ocr_items else []
                    track.plate_boxes = [dict(box) for box in p_boxes]

                p0 = time.perf_counter()
                record = {
                    "video": video_path.name,
                    "frame": frame_idx,
                    "srt_frame_hint": frame_idx + 1,
                    "timestamp_sec": float(frame_idx) / 30.0,
                    "device": device,
                    "vehicle_boxes": v_boxes,
                    "plate_boxes": p_boxes,
                    "ocr": ocr_items,
                    "optical_flow_mean_px": round(float(flow_magnitude), 4),
                    "depth_proxy_m": round(float(depth_proxy), 4),
                    "frame_diff_score": round(float(frame_diff_score), 6),
                }
                out.write(json.dumps(record) + "\n")
                post_ms += (time.perf_counter() - p0) * 1000

                prev_frame_gray = current_gray
                previous_tracks = current_tracks

    total_ms = (time.perf_counter() - t0) * 1000
    metrics = StageMetrics(
        video=video_path.name,
        gpu=device,
        frames_read=frames_read,
        frames_processed=frames_processed,
        detections_vehicle=detections_vehicle,
        detections_plate=detections_plate,
        ocr_attempts=ocr_attempts,
        read_ms=round(read_ms, 2),
        detect_ms=round(detect_ms, 2),
        ocr_ms=round(ocr_ms, 2),
        post_ms=round(post_ms, 2),
        total_ms=round(total_ms, 2),
    )

    logger.info(
        "Finished %s: frames=%d detections_vehicle=%d detections_plate=%d ocr_attempts=%d elapsed_ms=%.0f",
        video_path.name,
        metrics.frames_read,
        metrics.detections_vehicle,
        metrics.detections_plate,
        metrics.ocr_attempts,
        metrics.total_ms,
    )
    metrics_path.write_text(json.dumps(asdict(metrics), indent=2), encoding="utf-8")
    return metrics


def worker(args: tuple[list[str], str, str, int, int, RuntimeTuning, Path | None]) -> list[dict[str, Any]]:
    video_paths, out_dir, device, frame_step, batch_size, tuning, telemetry_path = args
    out = []
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if device == "cpu" or not torch.cuda.is_available():
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        effective_device = "cpu"
    else:
        os.environ["CUDA_VISIBLE_DEVICES"] = device
        effective_device = device

    for v in video_paths:
        metrics = run_video(Path(v), output_dir, effective_device, frame_step, batch_size, tuning, telemetry_path)
        out.append(asdict(metrics))
    return out


def chunk(items: list[str], n: int) -> list[list[str]]:
    buckets = [[] for _ in range(max(n, 1))]
    for i, item in enumerate(items):
        buckets[i % max(n, 1)].append(item)
    return [b for b in buckets if b]


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-GPU CV pipeline scaffold")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--devices", default="0", help="Comma-separated GPU ids, or 'cpu'")
    parser.add_argument("--frame-step", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--ocr-frame-interval", type=int, default=3)
    parser.add_argument("--max-plate-boxes", type=int, default=6)
    parser.add_argument("--max-ocr-crops", type=int, default=3)
    parser.add_argument("--min-plate-crop-area", type=int, default=400)
    parser.add_argument("--plate-model-path", type=str)
    parser.add_argument("--telemetry-csv", type=Path, default=None, help="Optional telemetry CSV with frame/latitude/longitude/altitude/yaw/pitch/roll values.")
    parser.add_argument(
        "--disable-roi-plate-model",
        action="store_true",
        help="Disable dedicated ROI plate model inference even when a plate checkpoint path is provided.",
    )
    parser.add_argument(
        "--disable-full-frame-plate-detector",
        action="store_true",
        help="Skip the placeholder full-frame plate detector and rely on vehicle-derived plate regions.",
    )
    args = parser.parse_args()

    tuning = RuntimeTuning(
        use_full_frame_plate_detector=not args.disable_full_frame_plate_detector,
        prefer_roi_plate_model=not args.disable_roi_plate_model,
        ocr_frame_interval=max(1, args.ocr_frame_interval),
        max_plate_boxes=max(1, args.max_plate_boxes),
        max_ocr_crops=max(1, args.max_ocr_crops),
        min_plate_crop_area=max(1, args.min_plate_crop_area),
        plate_model_path=args.plate_model_path,
    )

    videos = sorted([str(p) for p in args.input_dir.glob("*.MP4")])
    if not videos:
        raise RuntimeError("No MP4 files found in input directory")

    devices = resolve_devices(args.devices)
    if not devices:
        devices = ["cpu"]
    if not torch.cuda.is_available() and all(d != "cpu" for d in devices):
        devices = ["cpu"]

    assignments = chunk(videos, len(devices))
    telemetry_path = args.telemetry_csv if args.telemetry_csv is not None else None
    if telemetry_path is not None and telemetry_path.is_dir():
        telemetry_path = None

    worker_args = []
    for i, batch in enumerate(assignments):
        worker_args.append((batch, str(args.output_dir), devices[i], args.frame_step, args.batch_size, tuning, telemetry_path))

    t0 = time.perf_counter()
    if len(worker_args) == 1:
        print(f"Processing {len(videos)} video(s) sequentially on device={devices[0]}")
        worker_results = [worker(worker_args[0])]
    else:
        print(f"Processing {len(videos)} video(s) across {len(worker_args)} worker(s)")
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=len(worker_args)) as pool:
            worker_results = pool.map(worker, worker_args)
    total_ms = (time.perf_counter() - t0) * 1000

    flat = [item for sub in worker_results for item in sub]
    summary = {
        "videos": len(videos),
        "devices": devices,
        "frame_step": args.frame_step,
        "batch_size": args.batch_size,
        "total_ms": round(total_ms, 2),
        "per_video": flat,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "cv-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
