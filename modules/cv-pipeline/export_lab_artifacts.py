#!/usr/bin/env python
"""Generate Workshop Lab demo artifacts for the web-dashboard and Tauri app.

Mirrors the per-module visualization cells in cv_pipeline_lab.ipynb and writes
the PNGs plus manifest.json to output/lab-artifacts/.

Usage:
    python modules/cv-pipeline/export_lab_artifacts.py [--video PATH] [--device 0|cpu]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "modules" / "cv-pipeline"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import run_cv_pipeline as rcp
import license_plate_service as lps

LAB_DIR = ROOT / "output" / "lab-artifacts"
LAB_DIR.mkdir(parents=True, exist_ok=True)


def save_fig(fig, name: str) -> Path:
    path = LAB_DIR / name
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("saved", path)
    return path


def pipeline_diagram() -> None:
    fig, ax = plt.subplots(figsize=(17, 6))
    ax.axis("off")
    stage_rows = [
        ("1 Ingest", ["MP4 video", "TXT flight log", "SRT telemetry"], "#dbeafe"),
        ("2 Parse", ["flightrecord-parser\n(Rust)", "flight-visualizer\nSRT parser"], "#dcfce7"),
        ("3 Perceive", ["cv-pipeline\ndetect + OCR", "plate service\ncandidates + fusion"], "#fef9c3"),
        ("4 Ground", ["SRT sync\ngeotagging", "fuse\nmulti-frame"], "#ffedd5"),
        ("5 Report", ["lp_vehicle_report\nHTML / GeoJSON", "overlay video\nmotion viz"], "#fce7f3"),
        ("6 Review", ["web-dashboard\nserver review", "desktop-app\nTauri UX", "PostGIS + API\n(planned)"], "#e0e7ff"),
    ]
    col_w = 2.2
    row_h = 1.0
    for col, (title, boxes, color) in enumerate(stage_rows):
        x = 0.4 + col * (col_w + 0.22)
        ax.text(x + col_w / 2, 2.95, title, ha="center", va="center", fontsize=12, fontweight="bold")
        for i, label in enumerate(boxes):
            y = 1.7 - i * (row_h + 0.12)
            rect = mpatches.FancyBboxPatch(
                (x, y - 0.42), col_w, 0.85,
                boxstyle="round,pad=0.08", linewidth=1.2,
                edgecolor="#475569", facecolor=color)
            ax.add_patch(rect)
            ax.text(x + col_w / 2, y, label, ha="center", va="center", fontsize=9)
        if col < len(stage_rows) - 1:
            ax.annotate("", xy=(x + col_w + 0.2, 1.7), xytext=(x + col_w, 1.7),
                        arrowprops=dict(arrowstyle="-|>", color="#334155", lw=2))
    ax.set_xlim(0, len(stage_rows) * (col_w + 0.22) + 0.3)
    ax.set_ylim(-0.6, 3.3)
    fig.suptitle("IntelSight module integration data flow", fontsize=14)
    save_fig(fig, "pipeline_dataflow.png")


def module1_parser() -> None:
    frames_files = sorted(ROOT.glob("output/flightrecords/*.frames.csv"))
    if not frames_files:
        print("skip module1: no frames.csv")
        return
    frames_path = frames_files[0]
    telemetry = pd.read_csv(frames_path)
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    axes[0].plot(telemetry["longitude"], telemetry["latitude"], marker=".", markersize=2, linewidth=1)
    axes[0].set_title("Trajectory (lon/lat)")
    axes[0].set_xlabel("longitude"); axes[0].set_ylabel("latitude")
    axes[1].plot(telemetry["height"], marker=".", markersize=2, linewidth=1)
    axes[1].set_title("Barometric height over samples")
    axes[1].set_xlabel("sample index"); axes[1].set_ylabel("height (m)")
    axes[2].hist(telemetry["yaw"].dropna(), bins=36)
    axes[2].set_title("Aircraft yaw distribution")
    axes[2].set_xlabel("yaw (deg)")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.suptitle(f"Module 1: Rust parser output — {frames_path.stem[:60]}")
    fig.tight_layout()
    save_fig(fig, "module1_parser_telemetry.png")


def module2_srt() -> None:
    srt_files = sorted(ROOT.glob("output/flightrecords/flight_mission_drone/FlagerPublix/*.srt.csv"))
    if not srt_files:
        srt_files = sorted(ROOT.glob("output/flightrecords/flight_mission_drone/*.srt.csv"))
    if not srt_files:
        print("skip module2: no srt.csv")
        return
    srt_path = srt_files[0]
    srt = pd.read_csv(srt_path)
    srt["t_sec"] = (srt["diff_ms"] - srt["diff_ms"].iloc[0]) / 1000.0
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    axes[0].plot(srt["t_sec"], srt["rel_alt"], linewidth=1)
    axes[0].set_title("Relative altitude over mission time")
    axes[0].set_xlabel("time (s)"); axes[0].set_ylabel("rel_alt (m)")
    axes[1].plot(srt["t_sec"], srt["focal_len"], linewidth=1, color="tab:orange")
    axes[1].set_title("Focal length (35mm equiv) over time")
    axes[1].set_xlabel("time (s)"); axes[1].set_ylabel("focal_len (mm)")
    axes[2].plot(srt["longitude"], srt["latitude"], marker=".", markersize=2, linewidth=1, color="tab:green")
    axes[2].set_title("SRT trajectory (lon/lat)")
    axes[2].set_xlabel("longitude"); axes[2].set_ylabel("latitude")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.suptitle(f"Module 2: SRT telemetry — {srt_path.stem[:60]}")
    fig.tight_layout()
    save_fig(fig, "module2_srt_telemetry.png")


def module3_detection(video_path: Path, device: str) -> None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print("skip module3: cannot open", video_path)
        return
    frame_idx = 240
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print("skip module3: cannot read frame", frame_idx)
        return

    models = rcp.LazyModels(device)
    result = models.vehicle_model().predict([frame], device=device, verbose=False)[0]
    vehicle_boxes = []
    if getattr(result, "boxes", None) is not None:
        for box in result.boxes:
            cls_id = int(box.cls.item())
            if cls_id not in {2, 3, 5, 7}:
                continue
            xyxy = [int(x) for x in box.xyxy[0].tolist()]
            vehicle_boxes.append({
                "xyxy": xyxy,
                "class_name": lps.vehicle_class_name_from_id(cls_id),
                "conf": round(float(box.conf.item()), 4),
            })
    vehicle_boxes = sorted(vehicle_boxes, key=lambda item: item["conf"], reverse=True)[:8]

    canvas = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).copy()
    for item in vehicle_boxes:
        x1, y1, x2, y2 = item["xyxy"]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(canvas, f"{item['class_name']} {item['conf']:.2f}", (x1, max(18, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
    fig, ax = plt.subplots(figsize=(16, 9))
    ax.imshow(canvas)
    ax.set_title(f"Module 3: vehicle detection — {video_path.name} frame {frame_idx} ({len(vehicle_boxes)} vehicles)")
    ax.axis("off")
    save_fig(fig, "module3_detection_vehicles.png")

    if vehicle_boxes:
        focus = vehicle_boxes[0]
        candidates = lps.extract_plate_candidates_from_vehicle(
            frame, focus["xyxy"], frame_shape=frame.shape, max_candidates=3)
        x1, y1, x2, y2 = focus["xyxy"]
        crop_rgb = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
        overlay = crop_rgb.copy()
        for item in candidates:
            quad = item.get("quad")
            if quad:
                pts = np.array(quad, dtype=np.int32).reshape((-1, 1, 2))
                pts -= np.array([x1, y1])
                cv2.polylines(overlay, [pts], True, (255, 150, 0), 2)
            else:
                cx1, cy1, cx2, cy2 = item["xyxy"]
                cv2.rectangle(overlay, (cx1 - x1, cy1 - y1), (cx2 - x1, cy2 - y1), (255, 255, 0), 2)
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.imshow(overlay)
        ax.set_title(f"Module 3: plate candidates inside focus vehicle ({len(candidates)} proposals)")
        ax.axis("off")
        save_fig(fig, "module3_plate_candidates.png")


def module4_integration() -> None:
    fused_files = sorted(ROOT.glob("output/cv/*/fused/*.fused.csv"))
    geotagged_files = sorted(ROOT.glob("output/cv/*/synced/*.geotagged.csv"))
    if not fused_files or not geotagged_files:
        print("skip module4: no fused/geotagged outputs")
        return
    fused_df = pd.read_csv(fused_files[0])
    geo_df = pd.read_csv(geotagged_files[0])
    fig, axes = plt.subplots(1, 2, figsize=(18, 6))
    axes[0].scatter(geo_df["longitude"], geo_df["latitude"], s=3, c="#94a3b8", label="drone pose (SRT sync)")
    has_ll = {"latitude", "longitude"} <= set(fused_df.columns)
    if has_ll and not fused_df[["latitude", "longitude"]].dropna().empty:
        axes[0].scatter(fused_df["longitude"], fused_df["latitude"], s=45, c="tab:red", marker="^",
                        label="fused object points")
    axes[0].set_title("Integrated map: drone path vs fused object points")
    axes[0].set_xlabel("longitude"); axes[0].set_ylabel("latitude")
    axes[0].legend(); axes[0].grid(True, alpha=0.25)

    conf_col = next((c for c in ("fused_confidence", "plate_confidence") if c in fused_df.columns), None)
    if conf_col:
        fused_df[conf_col].hist(bins=20, ax=axes[1])
        axes[1].set_title(f"{conf_col} distribution")
        axes[1].set_xlabel(conf_col)
    else:
        axes[1].text(0.5, 0.5, "no confidence column", ha="center", va="center", transform=axes[1].transAxes)
    axes[1].grid(True, alpha=0.25)
    fig.suptitle("Module 4: integrated sync + fusion report")
    fig.tight_layout()
    save_fig(fig, "module4_integration_fusion.png")

    report_files = sorted(ROOT.glob("output/cv/*/lp_vehicle_report.geojson"))
    if report_files:
        with report_files[0].open("r", encoding="utf-8") as f:
            gj = json.load(f)
        modes: dict[str, int] = {}
        for feat in gj.get("features", []):
            props = feat.get("properties", {})
            key = str(props.get("geolocation_mode", "unknown"))
            modes[key] = modes.get(key, 0) + 1
        print("module4 geojson features:", len(gj.get("features", [])), "| modes:", modes)


def module5_flow(video_path: Path) -> None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print("skip module5: cannot open", video_path)
        return
    frame_idx = 242
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx - 2)
    ok, prev_frame = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok2, curr_frame = cap.read()
    cap.release()
    if not (ok and ok2):
        print("skip module5: cannot read frames")
        return

    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
    flow = cv2.calcOpticalFlowFarneback(prev_gray, curr_gray, None,
                                        pyr_scale=0.5, levels=3, winsize=15,
                                        iterations=3, poly_n=5, poly_sigma=1.2,
                                        flags=cv2.OPTFLOW_FARNEBACK_GAUSSIAN)
    mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    heatmap = cv2.applyColorMap(np.clip((mag / 35.0) * 255.0, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    overlay = cv2.addWeighted(curr_frame, 0.45, heatmap, 0.55, 0)
    overlay_rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
    curr_rgb = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2RGB)

    fig, axes = plt.subplots(1, 2, figsize=(18, 7))
    axes[0].imshow(curr_rgb); axes[0].set_title(f"Frame {frame_idx}"); axes[0].axis("off")
    axes[1].imshow(overlay_rgb); axes[1].set_title("Optical flow overlay (dense Farneback)")
    axes[1].axis("off")
    fig.suptitle("Module 5: overlay motion view")
    fig.tight_layout()
    save_fig(fig, "module5_overlay_flow.png")


def manifest() -> None:
    entries = []
    for artifact in sorted(LAB_DIR.glob("*.png")):
        entries.append({
            "name": artifact.name,
            "path": str(artifact.relative_to(ROOT)),
            "module": artifact.name.split("_")[0],
        })
    manifest_path = LAB_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print("manifest:", manifest_path, "| artifacts:", len(entries))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=None,
                        help="mission MP4 for module3/module5 demos")
    parser.add_argument("--device", default=None,
                        help="inference device (default: cuda if available)")
    args = parser.parse_args()

    device = args.device
    if device is None:
        import torch

        device = "0" if torch.cuda.is_available() else "cpu"

    video = args.video
    if video is None:
        candidates = sorted(ROOT.glob("data/flightrecords/flight_mission_drone/FlagerPublix/*.MP4"))
        video = candidates[0] if candidates else None

    pipeline_diagram()
    module1_parser()
    module2_srt()
    if video is not None:
        module3_detection(video, device)
        module5_flow(video)
    else:
        print("skip module3/module5: no mission video available")
    module4_integration()
    manifest()


if __name__ == "__main__":
    main()
