import sqlite3
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "modules" / "cv-pipeline"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

WEB_DIR = ROOT / "modules" / "web-dashboard"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import license_plate_service as lps
import render_overlay_video as rov
import run_cv_pipeline as rcp
import store


class LicensePlateServiceTests(unittest.TestCase):
    def test_normalize_plate_text(self) -> None:
        self.assertEqual(lps.normalize_plate_text("AB-123-CD"), "AB123CD")
        self.assertEqual(lps.normalize_plate_text("ab 123 cd"), "AB123CD")
        self.assertEqual(lps.normalize_plate_text("O0I1X"), "OOI1X")

    def test_service_backend_names(self) -> None:
        self.assertIn("ultralytics", lps.BackendSelection.choices())
        self.assertIn("onnxruntime", lps.BackendSelection.choices())

    def test_parse_ocr_candidates(self) -> None:
        candidates = [
            {"text": "AB-123-CD", "conf": 0.74},
            {"text": "AB 123 CD", "conf": 0.81},
            {"text": "A0-123-CO", "conf": 0.56},
        ]
        item = lps.select_best_plate_candidate(candidates)
        self.assertEqual(item["text"], "AB123CD")
        self.assertGreaterEqual(item["confidence"], 0.8)

    def test_vehicle_classification_and_geolocation_helpers(self) -> None:
        label = lps.vehicle_class_name_from_id(2)
        self.assertEqual(label, "car")

        geo = lps.estimate_object_geolocation(
            latitude=25.7650,
            longitude=-80.3710,
            altitude_m=40.0,
            center_x_norm=0.5,
            center_y_norm=0.25,
            flow_magnitude_px=11.0,
            depth_proxy_m=1.6,
        )
        self.assertIn("latitude", geo)
        self.assertIn("longitude", geo)
        self.assertIn("ground_offset_m", geo)
        self.assertGreater(geo["ground_offset_m"], 0.0)
        self.assertGreaterEqual(geo["depth_confidence"], 0.0)

    def test_camera_ground_projection_estimate(self) -> None:
        geo = lps.estimate_object_geolocation(
            latitude=25.7650,
            longitude=-80.3710,
            altitude_m=40.0,
            center_x_norm=0.55,
            center_y_norm=0.38,
            yaw_deg=20.0,
            pitch_deg=-8.0,
            roll_deg=0.0,
            flow_magnitude_px=8.0,
            depth_proxy_m=1.2,
            geolocation_method="camera_ground_projection",
        )
        self.assertGreater(geo["ground_offset_m"], 0.0)
        self.assertEqual(geo["geolocation_method"], "camera_ground_projection")
        self.assertGreaterEqual(geo["depth_confidence"], 0.0)

    def test_plate_candidate_selection_uses_confidence_and_length(self) -> None:
        candidates = [
            {"text": "AB123CD", "conf": 0.81},
            {"text": "AB123C", "conf": 0.92},
            {"text": "A8123", "conf": 0.95},
        ]
        item = lps.select_best_plate_candidate(candidates)
        self.assertEqual(item["text"], "AB123CD")
        self.assertGreaterEqual(item["confidence"], 0.8)

    def test_render_helpers_filter_zero_boxes_and_keep_last_valid_detection(self) -> None:
        rec = {
            "vehicle_boxes": [
                {"xyxy": [0, 0, 0, 0]},
                {"xyxy": [10, 20, 100, 120]},
            ],
            "ocr": [
                {"xyxy": [0, 0, 0, 0], "plate_conf": 0.0},
                {"xyxy": [200, 300, 500, 600], "plate_conf": 0.42},
            ],
        }
        filtered = rov.filter_valid_detections(rec)
        self.assertEqual(len(filtered["vehicle_boxes"]), 1)
        self.assertEqual(len(filtered["ocr"]), 1)
        self.assertEqual(filtered["vehicle_boxes"][0]["xyxy"], [10, 20, 100, 120])
        self.assertEqual(filtered["ocr"][0]["xyxy"], [200, 300, 500, 600])

        self.assertEqual(
            rov.normalize_xyxy(["0", "0", "80", "60"]),
            [0, 0, 80, 60],
        )
        self.assertIsNone(rov.normalize_xyxy([0, 0, 0, 0]))

        selected = rov.choose_flow_roi_for_frame(
            (1080, 1920),
            [
                [15, 20, 100, 120],
                [1300, 700, 1800, 930],
                [100, 100, 200, 200],
            ],
            fallback_roi=(0, 0, 1920, 1080),
            min_edge_margin_ratio=0.12,
            padding=20,
        )
        self.assertGreater(selected[0], 0)
        self.assertGreater(selected[1], 0)
        self.assertLess(selected[2], 1920)
        self.assertLess(selected[3], 1080)
        self.assertGreater((selected[2] - selected[0]) * (selected[3] - selected[1]), 0)

        self.assertEqual(
            rov.compute_dev_snip_frame_range(3000, 30.0, start_offset_seconds=20.0, duration_seconds=30.0),
            (600, 1500),
        )

        self.assertIsNone(rov.resolve_active_detection(23, {12: {"frame": 12}}, None))
        self.assertEqual(
            rov.resolve_active_detection(23, {12: {"frame": 12}}, {"frame": 12}),
            {"frame": 12},
        )

    def test_plate_like_box_filter_and_sparser_flow_step(self) -> None:
        frame_w, frame_h = 1920, 1080
        plate_like = [1040, 420, 1188, 486]
        car_like = [240, 460, 1080, 820]

        self.assertTrue(rov.is_plate_like_box(plate_like, frame_w, frame_h))
        self.assertFalse(rov.is_plate_like_box(car_like, frame_w, frame_h))

        step = rov.suggest_flow_vector_step(frame_w, frame_h)
        self.assertGreater(step, 8)
        self.assertLessEqual(step, 24)

    def test_extract_plate_candidates_from_vehicle_box(self) -> None:
        frame = 255 * np.ones((300, 600, 3), dtype=np.uint8)
        vehicle = [80, 120, 460, 220]
        candidates = lps.extract_plate_candidates_from_vehicle(frame, vehicle, frame_shape=frame.shape)
        self.assertTrue(candidates)
        self.assertTrue(all(len(item["xyxy"]) == 4 for item in candidates))
        self.assertTrue(all(item["xyxy"][1] >= vehicle[1] for item in candidates))

    def test_segment_plate_instances_from_vehicle_rectifies_skewed_plate(self) -> None:
        frame = np.zeros((320, 640, 3), dtype=np.uint8)
        vehicle = [120, 90, 520, 250]
        cv2 = __import__("cv2")
        cv2.rectangle(frame, (vehicle[0], vehicle[1]), (vehicle[2], vehicle[3]), (70, 70, 70), -1)
        rect = ((360, 205), (120, 28), -24.0)
        quad = cv2.boxPoints(rect).astype(np.int32)
        cv2.fillConvexPoly(frame, quad, (240, 240, 240))
        cv2.polylines(frame, [quad], True, (20, 20, 20), 2)

        candidates = lps.segment_plate_instances_from_vehicle(frame, vehicle, frame_shape=frame.shape, max_candidates=3)
        self.assertTrue(candidates)
        segmented = next((item for item in candidates if item.get("source") == "vehicle_plate_segment"), None)
        self.assertIsNotNone(segmented)
        crop = lps.extract_plate_crop(frame, segmented)
        self.assertGreater(crop.shape[1], crop.shape[0])
        self.assertGreater(crop.shape[1], 40)
        self.assertIn("quad", segmented)

    def test_extract_plate_candidates_prefers_segmented_candidate_when_available(self) -> None:
        frame = np.zeros((280, 560, 3), dtype=np.uint8)
        vehicle = [100, 80, 440, 220]
        cv2 = __import__("cv2")
        cv2.rectangle(frame, (vehicle[0], vehicle[1]), (vehicle[2], vehicle[3]), (65, 65, 65), -1)
        rect = ((300, 185), (110, 26), -18.0)
        quad = cv2.boxPoints(rect).astype(np.int32)
        cv2.fillConvexPoly(frame, quad, (245, 245, 245))
        cv2.polylines(frame, [quad], True, (10, 10, 10), 2)

        candidates = lps.extract_plate_candidates_from_vehicle(frame, vehicle, frame_shape=frame.shape, max_candidates=3)
        self.assertTrue(candidates)
        self.assertEqual(candidates[0].get("source"), "vehicle_plate_segment")

    def test_merge_plate_boxes_prioritizes_vehicle_regions(self) -> None:
        model_boxes = [
            {"conf": 0.95, "xyxy": [1, 2, 30, 20]},
            {"conf": 0.88, "xyxy": [40, 10, 80, 28]},
        ]
        vehicle_boxes = [
            {"conf": 0.72, "xyxy": [100, 120, 180, 150]},
            {"conf": 0.72, "xyxy": [100, 120, 180, 150]},
        ]

        merged = rcp.merge_plate_boxes(model_boxes, vehicle_boxes, max_candidates=4)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["xyxy"], [100, 120, 180, 150])

        merged_without_vehicle = rcp.merge_plate_boxes(model_boxes, [], max_candidates=1)
        self.assertEqual(len(merged_without_vehicle), 1)
        self.assertEqual(merged_without_vehicle[0]["xyxy"], [1, 2, 30, 20])

    def test_should_run_ocr_respects_interval(self) -> None:
        tuning = rcp.RuntimeTuning(ocr_frame_interval=3)
        self.assertTrue(rcp.should_run_ocr(0, tuning))
        self.assertFalse(rcp.should_run_ocr(1, tuning))
        self.assertFalse(rcp.should_run_ocr(2, tuning))
        self.assertTrue(rcp.should_run_ocr(3, tuning))

    def test_should_refresh_track_ocr_skips_recent_high_confidence_tracks(self) -> None:
        tuning = rcp.RuntimeTuning(ocr_frame_interval=3)
        track = rcp.VehicleTrackState(
            track_id=7,
            xyxy=[100, 100, 200, 180],
            signature=np.zeros((16, 16), dtype=np.uint8),
            ocr_items=[{"ocr_conf": 0.91}],
            plate_boxes=[],
            last_ocr_frame=8,
            last_ocr_confidence=0.91,
        )
        self.assertFalse(rcp.should_refresh_track_ocr(track, frame_idx=9, tuning=tuning))
        self.assertTrue(rcp.should_refresh_track_ocr(track, frame_idx=12, tuning=tuning))

    def test_resolve_devices_and_queue_limits(self) -> None:
        self.assertEqual(rcp.resolve_devices("cpu"), ["cpu"])
        self.assertEqual(rcp.resolve_devices("0,1"), ["cuda:0", "cuda:1"])
        self.assertEqual(rcp.resolve_device_token("cuda:1"), "cuda:1")
        self.assertEqual(rcp.resolve_device_token("0"), "cuda:0")
        self.assertEqual(rcp.resolve_device_token("cpu"), "cpu")
        self.assertEqual(rcp.bound_queue_size(40, 12), 12)
        self.assertEqual(rcp.bound_queue_size(5, 12), 5)

    def test_build_track_roi_uses_prior_box_bounds_for_motion_first_detection(self) -> None:
        frame_shape = (1080, 1920, 3)
        prior_track = [500, 300, 800, 500]
        roi = rcp.build_track_roi(prior_track, frame_shape, margin_ratio=0.35, min_side=160)
        self.assertLess(roi[0], prior_track[0])
        self.assertLess(roi[1], prior_track[1])
        self.assertGreater(roi[2], prior_track[2])
        self.assertGreater(roi[3], prior_track[3])
        self.assertLess(roi[2], frame_shape[1])
        self.assertLess(roi[3], frame_shape[0])
        self.assertGreater(roi[2] - roi[0], 0)
        self.assertGreater(roi[3] - roi[1], 0)

    def test_runtime_device_resolution_and_optical_flow_fallback(self) -> None:
        resolved_auto = rov.resolve_device("auto")
        self.assertIn(resolved_auto, {"cpu", "cuda:0"})
        self.assertEqual(rov.resolve_device("cpu"), "cpu")

    def test_flight_state_resolution_uses_real_telemetry_over_placeholders(self) -> None:
        telemetry = [
            {"frame": 0, "latitude": 25.7600, "longitude": -80.3700, "altitude_m": 12.0, "yaw_deg": 10.0, "pitch_deg": -2.0, "roll_deg": 0.0},
            {"frame": 16, "latitude": 25.7610, "longitude": -80.3710, "altitude_m": 14.0, "yaw_deg": 18.0, "pitch_deg": -6.0, "roll_deg": 1.5},
        ]

        state = rcp.resolve_flight_state_for_frame(8, telemetry, default_latitude=25.7650, default_longitude=-80.3710, default_altitude_m=40.0)
        self.assertAlmostEqual(state["latitude"], 25.7600)
        self.assertAlmostEqual(state["longitude"], -80.3700)
        self.assertAlmostEqual(state["altitude_m"], 12.0)
        self.assertAlmostEqual(state["yaw_deg"], 10.0)

        geo = lps.estimate_object_geolocation(
            latitude=state["latitude"],
            longitude=state["longitude"],
            altitude_m=state["altitude_m"],
            center_x_norm=0.5,
            center_y_norm=0.25,
            flow_magnitude_px=11.0,
            depth_proxy_m=1.6,
            yaw_deg=state["yaw_deg"],
            pitch_deg=state["pitch_deg"],
            roll_deg=state["roll_deg"],
        )
        self.assertGreater(geo["ground_offset_m"], 0.0)
        self.assertLess(geo["latitude"], 25.7650)

        prev = np.zeros((120, 160, 3), dtype=np.uint8)
        curr = np.zeros_like(prev)
        cv2 = __import__("cv2")
        cv2.rectangle(curr, (20, 25), (90, 80), (120, 120, 120), -1)
        cv2.rectangle(curr, (100, 50), (140, 95), (200, 200, 200), -1)

        flow, device = rov.compute_optical_flow(cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY), cv2.cvtColor(curr, cv2.COLOR_BGR2GRAY), roi=(10, 10, 145, 105), device="cpu")
        self.assertEqual(flow.shape[2], 2)
        self.assertIn(device, {"cpu", "cuda:0"})

    def test_render_motion_heatmap_overlay_returns_summary_and_valid_frame(self) -> None:
        prev = np.zeros((120, 160, 3), dtype=np.uint8)
        curr = np.zeros_like(prev)
        cv2 = __import__("cv2")
        cv2.rectangle(curr, (20, 25), (90, 80), (120, 120, 120), -1)
        cv2.rectangle(curr, (100, 50), (140, 95), (200, 200, 200), -1)

        overlay, stats = rov.render_motion_heatmap_overlay(prev, curr, roi=(10, 10, 145, 105), motion_scale=30.0, vector_step=8)

        self.assertEqual(overlay.shape, curr.shape)
        self.assertIn("mean_motion_px", stats)
        self.assertIn("active_ratio", stats)
        self.assertGreaterEqual(stats["max_motion_px"], 0.0)
        self.assertEqual(stats["roi"], (10, 10, 145, 105))

    def test_estimate_optical_flow_kinematics_reports_translation_and_rotation(self) -> None:
        prev = np.zeros((120, 160, 3), dtype=np.uint8)
        curr = prev.copy()
        cv2 = __import__("cv2")
        cv2.rectangle(curr, (30, 30), (80, 80), (90, 90, 90), -1)

        metrics = rov.estimate_optical_flow_kinematics(prev, curr, roi=(0, 0, 160, 120), vector_step=8)

        self.assertIn("translation_px", metrics)
        self.assertIn("rotation_proxy_deg", metrics)
        self.assertGreaterEqual(metrics["translation_px"], 0.0)
        self.assertGreaterEqual(metrics["mean_speed_px"], 0.0)
        self.assertIsInstance(metrics["translation_vector_px"], tuple)

    def test_spatial_feature_index_groups_keypoints_by_cell(self) -> None:
        keypoints = [
            cv2.KeyPoint(10, 12, 10),
            cv2.KeyPoint(45, 20, 10),
            cv2.KeyPoint(50, 80, 10),
            cv2.KeyPoint(12, 90, 10),
        ]
        descriptors = np.array([
            [1, 2, 3, 4],
            [5, 6, 7, 8],
            [9, 10, 11, 12],
            [13, 14, 15, 16],
        ], dtype=np.float32)

        index = rov.build_spatial_feature_index(keypoints, descriptors, cell_size=32)
        self.assertIn((0, 0), index)
        self.assertIn((1, 0), index)
        self.assertEqual(sum(len(v) for v in index.values()), len(keypoints))

    def test_spatial_match_candidates_respect_search_radius(self) -> None:
        cells = rov.get_candidate_spatial_cells((20, 10), 18, 32)
        self.assertTrue((0, 0) in cells)
        self.assertTrue((1, 0) in cells)

    def test_match_features_with_spatial_index_returns_vehicle_matches(self) -> None:
        frame_prev = np.zeros((120, 120, 3), dtype=np.uint8)
        frame_curr = np.zeros_like(frame_prev)
        cv2 = __import__("cv2")
        cv2.rectangle(frame_prev, (20, 20), (60, 60), (180, 180, 180), -1)
        cv2.rectangle(frame_curr, (24, 22), (64, 62), (180, 180, 180), -1)

        detector = cv2.SIFT_create() if hasattr(cv2, 'SIFT_create') else cv2.ORB_create(nfeatures=1000)
        kp_prev, desc_prev = detector.detectAndCompute(frame_prev, None)
        kp_curr, desc_curr = detector.detectAndCompute(frame_curr, None)

        if desc_prev is None or desc_curr is None:
            self.skipTest('feature detector produced no descriptors for synthetic vehicle frames')

        matches = rov.match_features_with_spatial_index(
            kp_prev,
            desc_prev,
            kp_curr,
            desc_curr,
            center_xy=(40, 40),
            radius_px=40,
            cell_size=24,
            max_matches=30,
        )
        self.assertGreater(len(matches), 0)

    def test_frame_difference_and_ocr_remap_support_reuse(self) -> None:
        frame_a = np.zeros((40, 60), dtype=np.uint8)
        frame_b = np.zeros((40, 60), dtype=np.uint8)
        frame_b[:, :3] = 255
        self.assertEqual(rcp.frame_difference_score(frame_a, frame_a), 0.0)
        self.assertGreater(rcp.frame_difference_score(frame_a, frame_b), 0.0)

        remapped = rcp.remap_ocr_items(
            [{"xyxy": [20, 20, 40, 30], "ocr_text": "AB123CD", "ocr_conf": 0.9}],
            [10, 10, 50, 50],
            [20, 20, 100, 100],
            (200, 200, 3),
            7,
        )
        self.assertEqual(remapped[0]["track_id"], 7)
        self.assertTrue(remapped[0]["reused_from_track"])
        self.assertEqual(remapped[0]["xyxy"], [40, 40, 80, 60])

    def test_attach_track_ids_to_ocr_items_uses_best_vehicle_overlap(self) -> None:
        ocr_items = [{"xyxy": [12, 12, 42, 28], "ocr_text": "AB123CD", "ocr_conf": 0.88}]
        vehicles = [
            {"track_id": 3, "xyxy": [10, 10, 50, 40]},
            {"track_id": 8, "xyxy": [80, 80, 120, 120]},
        ]
        attached = rcp.attach_track_ids_to_ocr_items(ocr_items, vehicles)
        self.assertEqual(attached[0]["track_id"], 3)

    def test_letterbox_and_unletterbox_round_trip(self) -> None:
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        canvas, meta = rcp.letterbox_image(image, (640, 640))
        self.assertEqual(canvas.shape, (640, 640, 3))
        recovered = rcp.unletterbox_xyxy([160, 160, 480, 320], meta)
        self.assertTrue(all(isinstance(v, int) for v in recovered))
        self.assertGreater(recovered[2], recovered[0])

    def test_yolox_predictions_to_candidates_decodes_single_class_rows(self) -> None:
        meta = rcp.LetterboxMeta(scale=1.0, pad_x=0, pad_y=0, width=640, height=640)
        prediction = np.array([
            [320.0, 320.0, 200.0, 80.0, 0.95, 0.98],
            [322.0, 321.0, 198.0, 78.0, 0.90, 0.95],
            [100.0, 100.0, 30.0, 10.0, 0.10, 0.90],
        ], dtype=np.float32)
        candidates = rcp.yolox_predictions_to_candidates(prediction, meta, conf_threshold=0.25, iou_threshold=0.4)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source"], "roi_plate_model_box")
        self.assertGreater(candidates[0]["conf"], 0.8)

    def test_map_roi_xyxy_to_frame_offsets_coordinates(self) -> None:
        mapped = rcp.map_roi_xyxy_to_frame([10, 20, 40, 50], (100, 200), (1080, 1920, 3))
        self.assertEqual(mapped, [110, 220, 140, 250])

    def test_world_mapping_builds_localized_points_for_database(self) -> None:
        detections = pd.DataFrame([
            {
                "latitude": 25.7650,
                "longitude": -80.3710,
                "altitude_m": 40.0,
                "vehicle_type": "car",
                "vehicle_color": "gray",
                "plate_text": "AB123CD",
                "fused_confidence": 0.92,
                "review_status": "stable",
                "frame": 12,
                "timestamp": "00:00:00",
                "geolocation_mode": "camera_ground_projection",
                "proxy_ground_offset_m": 5.5,
            }
        ])
        world = store.build_world_mapping(detections)
        self.assertFalse(world.empty)
        self.assertEqual(world.iloc[0]["latitude"], 25.7650)
        self.assertEqual(world.iloc[0]["object_label"], "AB123CD")

        cache_key = "world-map-regression"
        store.ingest_mission_digest(
            trajectory=pd.DataFrame([{"latitude": 25.7650, "longitude": -80.3710, "altitude_m": 40.0, "frame": 1}]),
            detections=detections,
            cache_key=cache_key,
            trajectory_source="trajectory.csv",
            detection_source="detections.csv",
            summary_source="summary.json",
            video_source="video.mp4",
            summary_payload={"total_observations": 1},
        )

        with sqlite3.connect(store.ensure_cache_path()) as connection:
            rows = pd.read_sql_query(
                "SELECT object_label, latitude, longitude FROM world_map WHERE cache_key = ? ORDER BY row_id",
                connection,
                params=(cache_key,),
            )
        self.assertEqual(rows.iloc[0]["object_label"], "AB123CD")
        self.assertEqual(float(rows.iloc[0]["latitude"]), 25.7650)


if __name__ == "__main__":
    unittest.main()
