from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    x1 = max(ax1, bx1)
    y1 = max(ay1, by1)
    x2 = min(ax2, bx2)
    y2 = min(ay2, by2)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / float(area_a + area_b - inter)


def closest_vehicle(plate_box: list[int], vehicles: list[dict[str, Any]]) -> dict[str, Any] | None:
    best = None
    best_score = 0.0
    for v in vehicles:
        score = iou(plate_box, v.get("xyxy", [0, 0, 0, 0]))
        if score > best_score:
            best_score = score
            best = v
    return best


def load_detection_rows(detection_file: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with detection_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def bbox_area(xyxy: list[int]) -> int:
    if len(xyxy) < 4:
        return 0
    x1, y1, x2, y2 = [int(v) for v in xyxy[:4]]
    return max(0, x2 - x1) * max(0, y2 - y1)


def estimate_frame_size(rec: dict[str, Any]) -> tuple[int, int]:
    width = int(rec.get("frame_width", 0) or 0)
    height = int(rec.get("frame_height", 0) or 0)
    if width > 0 and height > 0:
        return width, height

    max_x = 0
    max_y = 0
    for collection in [rec.get("vehicle_boxes", []) or [], rec.get("plate_boxes", []) or [], rec.get("ocr", []) or []]:
        for item in collection:
            xyxy = item.get("xyxy", [])
            if isinstance(xyxy, list) and len(xyxy) >= 4:
                max_x = max(max_x, int(xyxy[2]))
                max_y = max(max_y, int(xyxy[3]))

    guessed_width = max(max_x, 1)
    guessed_height = max(max_y, 1)
    return guessed_width, guessed_height


def bbox_center_norm(xyxy: list[int], frame_width: int, frame_height: int) -> tuple[float, float]:
    if len(xyxy) < 4 or frame_width <= 0 or frame_height <= 0:
        return 0.5, 0.5
    x1, y1, x2, y2 = [float(v) for v in xyxy[:4]]
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    return max(0.0, min(1.0, cx / frame_width)), max(0.0, min(1.0, cy / frame_height))


def sync_one(detection_file: Path, srt_csv: Path, out_dir: Path) -> Path:
    det_rows = load_detection_rows(detection_file)
    srt_df = pd.read_csv(srt_csv)
    if "frame" not in srt_df.columns:
        raise RuntimeError(f"SRT CSV missing frame column: {srt_csv}")

    srt_df = srt_df.dropna(subset=["frame", "latitude", "longitude"]).copy()
    srt_df["frame"] = srt_df["frame"].astype(int)
    srt_map = {int(r.frame): r for r in srt_df.itertuples(index=False)}

    flat_rows = []
    for rec in det_rows:
        srt_frame = int(rec.get("srt_frame_hint", 0))
        if srt_frame not in srt_map:
            continue
        srt = srt_map[srt_frame]
        frame_width, frame_height = estimate_frame_size(rec)

        vehicles = rec.get("vehicle_boxes", []) or []
        ocr_items = rec.get("ocr", []) or []

        for o in ocr_items:
            pb = o.get("xyxy", [0, 0, 0, 0])
            v = closest_vehicle(pb, vehicles)
            vehicle_xyxy = v.get("xyxy", []) if v else []
            vehicle_padded_xyxy = v.get("xyxy_padded", vehicle_xyxy) if v else []
            center_source_xyxy = vehicle_padded_xyxy if len(vehicle_padded_xyxy) >= 4 else (vehicle_xyxy if len(vehicle_xyxy) >= 4 else pb)
            bbox_center_x_norm, bbox_center_y_norm = bbox_center_norm(center_source_xyxy, frame_width, frame_height)
            flat_rows.append(
                {
                    "video": rec.get("video"),
                    "frame": rec.get("frame"),
                    "srt_frame": srt_frame,
                    "timestamp": str(getattr(srt, "timestamp", "")),
                    "latitude": float(getattr(srt, "latitude", 0.0)),
                    "longitude": float(getattr(srt, "longitude", 0.0)),
                    "rel_alt": float(getattr(srt, "rel_alt", 0.0)),
                    "abs_alt": float(getattr(srt, "abs_alt", 0.0)),
                    "plate_text": o.get("ocr_text", ""),
                    "plate_ocr_conf": float(o.get("ocr_conf", 0.0)),
                    "plate_det_conf": float(o.get("plate_conf", 0.0)),
                    "plate_sharpness": float(o.get("sharpness", 0.0)),
                    "plate_bbox": json.dumps(pb),
                    "vehicle_type": v.get("class_name") if v else "unknown",
                    "vehicle_type_conf": float(v.get("conf", 0.0)) if v else 0.0,
                    "vehicle_color": v.get("color") if v else "unknown",
                    "vehicle_color_votes": json.dumps(v.get("color_votes", {})) if v else "{}",
                    "vehicle_make_model": v.get("make_model_guess") if v else None,
                    "vehicle_bbox": json.dumps(v.get("xyxy", [])) if v else "[]",
                    "vehicle_bbox_padded": json.dumps(vehicle_padded_xyxy) if v else "[]",
                    "vehicle_bbox_area": int(v.get("bbox_area", bbox_area(vehicle_xyxy))) if v else bbox_area(vehicle_xyxy),
                    "vehicle_bbox_area_ratio": float(v.get("bbox_area_ratio", 0.0)) if v else 0.0,
                    "plate_bbox_area": bbox_area(pb),
                    "plate_bbox_area_ratio": float(bbox_area(pb)) / max(1.0, float(v.get("bbox_area", bbox_area(vehicle_xyxy))) if v else float(bbox_area(vehicle_xyxy))),
                    "flow_magnitude_px": float(v.get("flow_magnitude", rec.get("optical_flow_mean_px", 0.0))) if v else float(rec.get("optical_flow_mean_px", 0.0)),
                    "depth_proxy_m": float(v.get("depth_proxy_m", rec.get("depth_proxy_m", 0.0))) if v else float(rec.get("depth_proxy_m", 0.0)),
                    "frame_width": frame_width,
                    "frame_height": frame_height,
                    "bbox_center_x_norm": round(float(bbox_center_x_norm), 6),
                    "bbox_center_y_norm": round(float(bbox_center_y_norm), 6),
                }
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"{detection_file.stem}.geotagged.csv"
    pd.DataFrame(flat_rows).to_csv(out_csv, index=False)
    return out_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync CV detections with DJI SRT telemetry")
    parser.add_argument("--detections-dir", required=True, type=Path)
    parser.add_argument("--srt-csv-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    outputs = []
    for det_file in sorted(args.detections_dir.glob("*.detections.jsonl")):
        stem = det_file.stem.replace(".detections", "")
        srt_csv = args.srt_csv_dir / f"{stem}.srt.csv"
        if not srt_csv.exists():
            continue
        outputs.append(str(sync_one(det_file, srt_csv, args.output_dir)))

    summary = {"synced_files": len(outputs), "outputs": outputs}
    summary_path = args.output_dir / "sync-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
