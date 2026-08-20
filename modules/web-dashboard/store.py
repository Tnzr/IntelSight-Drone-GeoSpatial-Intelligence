from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = WORKSPACE_ROOT / "output" / "web-dashboard"
CACHE_PATH = CACHE_DIR / "mission_digest.sqlite3"


def ensure_cache_path() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_PATH


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_cache_key(*parts: str) -> str:
    normalized = "|".join(part or "" for part in parts)
    return _hash_text(normalized)


def source_label(source: Any) -> str:
    if isinstance(source, Path):
        return source.name
    return str(getattr(source, "name", "uploaded"))


def _write_record(cursor: sqlite3.Cursor, cache_key: str, row_id: int, payload: dict[str, Any], table_name: str) -> None:
    timestamp_value = str(payload.get("timestamp", ""))
    cursor.execute(
        f"""
        INSERT OR REPLACE INTO {table_name} (
            cache_key,
            row_id,
            payload_json,
            latitude,
            longitude,
            altitude_m,
            frame,
            timestamp,
            review_status,
            vehicle_type,
            vehicle_color,
            fused_confidence,
            support_frames
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cache_key,
            row_id,
            json.dumps(payload, default=str),
            float(payload.get("latitude", 0.0) or 0.0),
            float(payload.get("longitude", 0.0) or 0.0),
            float(payload.get("altitude_m", payload.get("rel_alt", 0.0)) or 0.0),
            int(payload.get("frame", payload.get("srt_frame", row_id)) or row_id),
            timestamp_value,
            str(payload.get("review_status", "")),
            str(payload.get("vehicle_type", "")),
            str(payload.get("vehicle_color", "")),
            float(payload.get("fused_confidence", payload.get("vehicle_type_conf", 0.0)) or 0.0),
            int(payload.get("support_frames", 0) or 0),
        ),
    )


def build_world_mapping(detections: pd.DataFrame) -> pd.DataFrame:
    if detections is None or detections.empty:
        return pd.DataFrame(columns=[
            "object_label",
            "latitude",
            "longitude",
            "altitude_m",
            "vehicle_type",
            "plate_text",
            "review_status",
            "fused_confidence",
            "geolocation_mode",
            "timestamp",
        ])

    frame = detections.copy()
    frame["latitude"] = pd.to_numeric(frame.get("latitude", pd.Series(dtype=float)), errors="coerce")
    frame["longitude"] = pd.to_numeric(frame.get("longitude", pd.Series(dtype=float)), errors="coerce")
    frame["altitude_m"] = pd.to_numeric(frame.get("altitude_m", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    frame["fused_confidence"] = pd.to_numeric(frame.get("fused_confidence", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    frame["vehicle_type"] = frame.get("vehicle_type", pd.Series(dtype=str)).fillna("").astype(str)
    frame["plate_text"] = frame.get("plate_text", pd.Series(dtype=str)).fillna("").astype(str)
    frame["review_status"] = frame.get("review_status", pd.Series(dtype=str)).fillna("review").astype(str)
    frame["geolocation_mode"] = frame.get("geolocation_mode", pd.Series(dtype=str)).fillna("camera_ground_projection").astype(str)
    frame["timestamp"] = frame.get("timestamp", pd.Series(dtype=str)).fillna("").astype(str)

    frame["object_label"] = frame.apply(
        lambda row: str(row.get("plate_text") or row.get("vehicle_type") or "object").strip() or "object",
        axis=1,
    )

    world = frame[
        [
            "object_label",
            "latitude",
            "longitude",
            "altitude_m",
            "vehicle_type",
            "plate_text",
            "review_status",
            "fused_confidence",
            "geolocation_mode",
            "timestamp",
        ]
    ].dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    return world


def initialize_db(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON;")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS mission_digest (
            cache_key TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            trajectory_source TEXT NOT NULL,
            detection_source TEXT NOT NULL,
            summary_source TEXT,
            video_source TEXT,
            trajectory_rows INTEGER NOT NULL,
            detection_rows INTEGER NOT NULL,
            summary_json TEXT
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS trajectory_points (
            cache_key TEXT NOT NULL,
            row_id INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude_m REAL NOT NULL,
            frame INTEGER NOT NULL,
            timestamp TEXT,
            review_status TEXT,
            vehicle_type TEXT,
            vehicle_color TEXT,
            fused_confidence REAL,
            support_frames INTEGER,
            PRIMARY KEY (cache_key, row_id)
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS detection_observations (
            cache_key TEXT NOT NULL,
            row_id INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude_m REAL NOT NULL,
            frame INTEGER NOT NULL,
            timestamp TEXT,
            review_status TEXT,
            vehicle_type TEXT,
            vehicle_color TEXT,
            fused_confidence REAL,
            support_frames INTEGER,
            PRIMARY KEY (cache_key, row_id)
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS world_map (
            cache_key TEXT NOT NULL,
            row_id INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            object_label TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude_m REAL NOT NULL,
            vehicle_type TEXT,
            plate_text TEXT,
            review_status TEXT,
            fused_confidence REAL,
            geolocation_mode TEXT,
            timestamp TEXT,
            PRIMARY KEY (cache_key, row_id)
        )
    """)


def _upsert_frame_table(
    connection: sqlite3.Connection,
    cache_key: str,
    table_name: str,
    frame: pd.DataFrame,
) -> None:
    connection.execute(f"DELETE FROM {table_name} WHERE cache_key = ?", (cache_key,))
    if frame.empty:
        return

    cursor = connection.cursor()
    for row_id, payload in enumerate(frame.to_dict(orient="records")):
        _write_record(cursor, cache_key, row_id, payload, table_name)


def _upsert_world_map_table(connection: sqlite3.Connection, cache_key: str, detections: pd.DataFrame) -> None:
    connection.execute("DELETE FROM world_map WHERE cache_key = ?", (cache_key,))
    world_rows = build_world_mapping(detections)
    if world_rows.empty:
        return

    for row_id, row in world_rows.iterrows():
        payload = row.to_dict()
        connection.execute(
            """
            INSERT OR REPLACE INTO world_map (
                cache_key,
                row_id,
                payload_json,
                object_label,
                latitude,
                longitude,
                altitude_m,
                vehicle_type,
                plate_text,
                review_status,
                fused_confidence,
                geolocation_mode,
                timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                int(row_id),
                json.dumps(payload, default=str),
                str(row.get("object_label", "object")),
                float(row.get("latitude", 0.0) or 0.0),
                float(row.get("longitude", 0.0) or 0.0),
                float(row.get("altitude_m", 0.0) or 0.0),
                str(row.get("vehicle_type", "")),
                str(row.get("plate_text", "")),
                str(row.get("review_status", "")),
                float(row.get("fused_confidence", 0.0) or 0.0),
                str(row.get("geolocation_mode", "camera_ground_projection")),
                str(row.get("timestamp", "")),
            ),
        )


def ingest_mission_digest(
    trajectory: pd.DataFrame,
    detections: pd.DataFrame,
    *,
    cache_key: str,
    trajectory_source: str,
    detection_source: str,
    summary_source: str | None = None,
    video_source: str | None = None,
    summary_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cache_path = ensure_cache_path()
    with sqlite3.connect(cache_path) as connection:
        initialize_db(connection)
        connection.execute(
            "DELETE FROM mission_digest WHERE cache_key = ?",
            (cache_key,),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO mission_digest (
                cache_key,
                created_at,
                trajectory_source,
                detection_source,
                summary_source,
                video_source,
                trajectory_rows,
                detection_rows,
                summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                datetime.now(timezone.utc).isoformat(),
                trajectory_source,
                detection_source,
                summary_source,
                video_source,
                int(len(trajectory)),
                int(len(detections)),
                json.dumps(summary_payload or {}, default=str),
            ),
        )
        _upsert_frame_table(connection, cache_key, "trajectory_points", trajectory)
        _upsert_frame_table(connection, cache_key, "detection_observations", detections)
        _upsert_world_map_table(connection, cache_key, detections)
        connection.commit()

    return {
        "cache_key": cache_key,
        "trajectory_rows": int(len(trajectory)),
        "detection_rows": int(len(detections)),
        "cache_path": str(cache_path),
    }


def load_mission_digest(cache_key: str) -> dict[str, pd.DataFrame]:
    cache_path = ensure_cache_path()
    if not cache_path.exists():
        return {"mission_digest": pd.DataFrame(), "trajectory_points": pd.DataFrame(), "detection_observations": pd.DataFrame()}

    with sqlite3.connect(cache_path) as connection:
        mission = pd.read_sql_query(
            "SELECT * FROM mission_digest WHERE cache_key = ?",
            connection,
            params=(cache_key,),
        )
        trajectory = pd.read_sql_query(
            "SELECT * FROM trajectory_points WHERE cache_key = ? ORDER BY row_id",
            connection,
            params=(cache_key,),
        )
        detections = pd.read_sql_query(
            "SELECT * FROM detection_observations WHERE cache_key = ? ORDER BY row_id",
            connection,
            params=(cache_key,),
        )
    return {"mission_digest": mission, "trajectory_points": trajectory, "detection_observations": detections}


def get_cached_mission(cache_key: str) -> dict[str, Any]:
    frames = load_mission_digest(cache_key)
    mission_df = frames.get("mission_digest", pd.DataFrame())
    if mission_df.empty:
        return {
            "cache_key": cache_key,
            "meta": {},
            "summary": {},
            "trajectory": pd.DataFrame(),
            "detections": pd.DataFrame(),
        }

    meta = mission_df.iloc[0].to_dict()
    summary_json = str(meta.get("summary_json") or "{}")
    try:
        summary = json.loads(summary_json)
    except json.JSONDecodeError:
        summary = {}

    def decode_payload_rows(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty or "payload_json" not in frame.columns:
            return pd.DataFrame()
        rows: list[dict[str, Any]] = []
        for payload in frame["payload_json"].tolist():
            try:
                parsed = json.loads(payload) if isinstance(payload, str) else payload
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                rows.append(parsed)
        return pd.DataFrame(rows)

    trajectory_rows = decode_payload_rows(frames.get("trajectory_points", pd.DataFrame()))
    detection_rows = decode_payload_rows(frames.get("detection_observations", pd.DataFrame()))
    return {
        "cache_key": cache_key,
        "meta": meta,
        "summary": summary if isinstance(summary, dict) else {},
        "trajectory": trajectory_rows,
        "detections": detection_rows,
    }


def list_cached_missions(limit: int = 20) -> pd.DataFrame:
    cache_path = ensure_cache_path()
    if not cache_path.exists():
        return pd.DataFrame()

    with sqlite3.connect(cache_path) as connection:
        return pd.read_sql_query(
            """
            SELECT cache_key, created_at, trajectory_source, detection_source, summary_source, video_source,
                   trajectory_rows, detection_rows
            FROM mission_digest
            ORDER BY created_at DESC
            LIMIT ?
            """,
            connection,
            params=(int(limit),),
        )
