from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def resize_to_height(frame: np.ndarray, target_height: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if h == target_height:
        return frame
    scale = target_height / float(h)
    target_w = max(1, int(round(w * scale)))
    return cv2.resize(frame, (target_w, target_height), interpolation=cv2.INTER_AREA)


def build_side_by_side_video(
    original_path: Path,
    overlay_path: Path,
    output_path: Path,
    label_left: str = "Original",
    label_right: str = "Perception overlay",
    target_fps: float = 30.0,
    panel_width: int = 960,
    panel_height: int = 540,
) -> None:
    src_cap = cv2.VideoCapture(str(original_path))
    overlay_cap = cv2.VideoCapture(str(overlay_path))

    if not src_cap.isOpened():
        raise RuntimeError(f"unable to open original video: {original_path}")
    if not overlay_cap.isOpened():
        raise RuntimeError(f"unable to open overlay video: {overlay_path}")

    src_fps = src_cap.get(cv2.CAP_PROP_FPS) or 30.0
    overlay_fps = overlay_cap.get(cv2.CAP_PROP_FPS) or 30.0
    output_fps = min(src_fps, overlay_fps, target_fps) or 30.0

    output_path.parent.mkdir(parents=True, exist_ok=True)

    src_ok, src_frame = src_cap.read()
    overlay_ok, overlay_frame = overlay_cap.read()
    if not src_ok or not overlay_ok:
        raise RuntimeError("failed to read the first frame from either input video")

    def annotate(frame: np.ndarray, label: str, x_offset: int) -> np.ndarray:
        out = frame.copy()
        cv2.rectangle(out, (0, 0), (out.shape[1] - 1, 38), (0, 0, 0), -1)
        cv2.putText(
            out,
            label,
            (x_offset + 18, 27),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        return out

    def resize_panel(frame: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
        return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)

    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(output_fps),
        (panel_width * 2, panel_height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"unable to open writer for output: {output_path}")

    src_msec = src_cap.get(cv2.CAP_PROP_POS_MSEC)
    overlay_msec = overlay_cap.get(cv2.CAP_PROP_POS_MSEC)
    frames_written = 0

    while src_ok and overlay_ok:
        src_frame_resized = resize_panel(src_frame, panel_width, panel_height)
        overlay_frame_resized = resize_panel(overlay_frame, panel_width, panel_height)

        left = annotate(src_frame_resized, label_left, 0)
        right = annotate(overlay_frame_resized, label_right, 0)
        pair = np.concatenate([left, right], axis=1)
        writer.write(pair)
        frames_written += 1

        next_src_ts = src_cap.get(cv2.CAP_PROP_POS_MSEC)
        next_overlay_ts = overlay_cap.get(cv2.CAP_PROP_POS_MSEC)
        if src_cap.get(cv2.CAP_PROP_FRAME_COUNT) > 0 and next_src_ts >= src_cap.get(cv2.CAP_PROP_FRAME_COUNT) * 1000.0 / max(src_fps, 1.0):
            src_ok = False
        else:
            src_ok, src_frame = src_cap.read()

        if overlay_cap.get(cv2.CAP_PROP_FRAME_COUNT) > 0 and next_overlay_ts >= overlay_cap.get(cv2.CAP_PROP_FRAME_COUNT) * 1000.0 / max(overlay_fps, 1.0):
            overlay_ok = False
        else:
            overlay_ok, overlay_frame = overlay_cap.read()

        # Align by timestamps to minimize the original-vs-overlay drift.
        while overlay_ok:
            overlay_ts = overlay_cap.get(cv2.CAP_PROP_POS_MSEC)
            if abs(overlay_ts - src_msec) <= 50.0:
                break
            if overlay_ts < src_msec:
                overlay_ok, overlay_frame = overlay_cap.read()
                continue
            break

        src_msec = src_cap.get(cv2.CAP_PROP_POS_MSEC)

    writer.release()
    src_cap.release()
    overlay_cap.release()
    print(f"side_by_side={output_path}")
    print(f"frames_written={frames_written}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render original-vs-overlay comparison video")
    parser.add_argument("--source", required=True, type=Path, help="Original input video")
    parser.add_argument("--overlay", required=True, type=Path, help="Overlay video")
    parser.add_argument("--output", required=True, type=Path, help="Output comparison video")
    parser.add_argument("--left-label", default="Original", help="Label shown on the left panel")
    parser.add_argument("--right-label", default="Motion overlay", help="Label shown on the right panel")
    args = parser.parse_args()

    build_side_by_side_video(
        args.source,
        args.overlay,
        args.output,
        label_left=args.left_label,
        label_right=args.right_label,
    )


if __name__ == "__main__":
    main()
