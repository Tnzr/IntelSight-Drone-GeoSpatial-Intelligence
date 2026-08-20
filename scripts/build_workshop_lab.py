#!/usr/bin/env python
"""Rebuild cv_pipeline_lab.ipynb as the IntelSight Workshop Lab.

Idempotent: inserts the per-module workshop sections and integration
visualizations only if they are not already present. Safe to re-run.

Usage:
    python scripts/build_workshop_lab.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "modules" / "cv-pipeline" / "cv_pipeline_lab.ipynb"


def md(lines: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": [line + "\n" for line in lines.split("\n")],
    }


def code(lines: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [line + "\n" for line in lines.split("\n")],
    }


WORKSHOP_HEADER = md(
    """# IntelSight Workshop Lab

This notebook is the workshop walkthrough for every IntelSight module and the
integrations between them. Run the cells top to bottom; each module section is
self-contained, shows real pipeline artifacts, and exports its visualization to
`output/lab-artifacts/` for the web-dashboard and Tauri desktop app to display.

## Workshop structure

| Section | Module | What you learn |
|---|---|---|
| Module Map | integration | data-flow diagram between all modules |
| Module 1 | `flightrecord-parser` (Rust) | TXT flight log -> telemetry CSV/GeoJSON |
| Module 2 | `flight-visualizer` | SRT telemetry parsing and fields |
| Module 3 | `cv-pipeline` | detection, plate candidates, OCR, tracking |
| Module 4 | `cv-pipeline` sync + fuse | geotagging, multi-frame fusion, report |
| Module 5 | `render_overlay_video` | optical-flow motion view for the overlay |
| Lab export | integration | manifest of demo PNGs consumed by the apps |

## Guided exercises

- Module 1: compare `latitude/longitude` from the TXT frames CSV against the SRT CSV for the same mission; estimate the telemetry-rate difference.
- Module 2: find the SRT rows where `focal_len` changes; explain why the Mini 4 Pro reports 35mm-equivalent values.
- Module 3: change `FRAME_PAIR_INDEX` and re-run detection; observe how box counts change with scene density.
- Module 4: look at `geolocation_mode` and `geo_spread_m` in the fused output; find one `proxy` observation and one `telemetry` observation.
- Module 5: compare the flow overlay between a static scene window and a moving-scene window.
""",
)

MODULE_MAP_CODE = code(
    """LAB_DIR = ROOT / 'output' / 'lab-artifacts'
LAB_DIR.mkdir(parents=True, exist_ok=True)

import matplotlib.patches as mpatches


def draw_pipeline_diagram(out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(17, 6))
    ax.axis('off')
    stage_rows = [
        ('1 Ingest', ['MP4 video', 'TXT flight log', 'SRT telemetry'], '#dbeafe'),
        ('2 Parse', ['flightrecord-parser\\n(Rust)', 'flight-visualizer\\nSRT parser'], '#dcfce7'),
        ('3 Perceive', ['cv-pipeline\\ndetect + OCR', 'plate service\\ncandidates + fusion'], '#fef9c3'),
        ('4 Ground', ['SRT sync\\ngeotagging', 'fuse\\nmulti-frame'], '#ffedd5'),
        ('5 Report', ['lp_vehicle_report\\nHTML / GeoJSON', 'overlay video\\nmotion viz'], '#fce7f3'),
        ('6 Review', ['web-dashboard\\nserver review', 'desktop-app\\nTauri UX', 'PostGIS + API\\n(planned)'], '#e0e7ff'),
    ]
    col_w = 2.2
    row_h = 1.0
    for col, (title, boxes, color) in enumerate(stage_rows):
        x = 0.4 + col * (col_w + 0.22)
        ax.text(x + col_w / 2, 2.95, title, ha='center', va='center', fontsize=12, fontweight='bold')
        for i, label in enumerate(boxes):
            y = 1.7 - i * (row_h + 0.12)
            rect = mpatches.FancyBboxPatch(
                (x, y - 0.42), col_w, 0.85,
                boxstyle='round,pad=0.08', linewidth=1.2,
                edgecolor='#475569', facecolor=color)
            ax.add_patch(rect)
            ax.text(x + col_w / 2, y, label, ha='center', va='center', fontsize=9)
        if col < len(stage_rows) - 1:
            ax.annotate('', xy=(x + col_w + 0.2, 1.7), xytext=(x + col_w, 1.7),
                        arrowprops=dict(arrowstyle='-|>', color='#334155', lw=2))
    ax.set_xlim(0, len(stage_rows) * (col_w + 0.22) + 0.3)
    ax.set_ylim(-0.6, 3.3)
    fig.suptitle('IntelSight module integration data flow', fontsize=14)
    fig.savefig(out_path, dpi=130, bbox_inches='tight')
    plt.close(fig)
    print('saved', out_path)


draw_pipeline_diagram(LAB_DIR / 'pipeline_dataflow.png')
""",
)

MODULE1_MD = md(
    """## Module 1 · flightrecord-parser (Rust)

The Rust module in `modules/flightrecord-parser/` converts DJI TXT flight logs
into normalized telemetry. The exported `frames.csv` is the ground truth for
IMU attitude (`pitch/roll/yaw`) that the SRT files do not carry.

The cell below loads a real `frames.csv` from `output/flightrecords/` and plots
the ENU trajectory, altitude profile, and heading distribution. This is the
data the future camera-projection and SfM stages will anchor to.
""",
)

MODULE1_CODE = code(
    """import glob as _glob

frames_files = sorted(ROOT.glob('output/flightrecords/*.frames.csv'))
if not frames_files:
    print('No frames.csv found under output/flightrecords. Run scripts/run_flightrecord_pipeline.sh first.')
else:
    frames_path = frames_files[0]
    print('Demo file:', frames_path.name)
    telemetry = pd.read_csv(frames_path)
    print('Columns:', list(telemetry.columns))
    print(telemetry[['customDateTime', 'latitude', 'longitude', 'height', 'pitch', 'roll', 'yaw']].head(3).to_string(index=False))

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    axes[0].plot(telemetry['longitude'], telemetry['latitude'], marker='.', markersize=2, linewidth=1)
    axes[0].set_title('Trajectory (lon/lat)')
    axes[0].set_xlabel('longitude'); axes[0].set_ylabel('latitude')
    axes[1].plot(telemetry['height'], marker='.', markersize=2, linewidth=1)
    axes[1].set_title('Barometric height over samples')
    axes[1].set_xlabel('sample index'); axes[1].set_ylabel('height (m)')
    axes[2].hist(telemetry['yaw'].dropna(), bins=36)
    axes[2].set_title('Aircraft yaw distribution')
    axes[2].set_xlabel('yaw (deg)')
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.suptitle(f'Module 1: Rust parser output — {frames_path.stem[:60]}')
    fig.tight_layout()
    fig.savefig(LAB_DIR / 'module1_parser_telemetry.png', dpi=130)
    plt.show()
""",
)

MODULE2_MD = md(
    """## Module 2 · flight-visualizer (SRT telemetry)

`modules/flight-visualizer/parse_dji_srt.py` extracts per-frame telemetry from
the DJI SRT subtitle stream: pose, altitude, camera parameters, and
`focal_len` (35mm-equivalent). The SRT is the time-aligned telemetry source
for frame geotagging.
""",
)

MODULE2_CODE = code(
    """srt_files = sorted(ROOT.glob('output/flightrecords/flight_mission_drone/FlagerPublix/*.srt.csv'))
if not srt_files:
    srt_files = sorted(ROOT.glob('output/flightrecords/flight_mission_drone/*.srt.csv'))
if not srt_files:
    print('No SRT CSVs found. Run scripts/run_srt_dashboard.sh first.')
else:
    srt_path = srt_files[0]
    print('Demo file:', srt_path.name)
    srt = pd.read_csv(srt_path)
    print('Columns:', list(srt.columns))
    srt['t_sec'] = (srt['diff_ms'] - srt['diff_ms'].iloc[0]) / 1000.0

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    axes[0].plot(srt['t_sec'], srt['rel_alt'], linewidth=1)
    axes[0].set_title('Relative altitude over mission time')
    axes[0].set_xlabel('time (s)'); axes[0].set_ylabel('rel_alt (m)')
    axes[1].plot(srt['t_sec'], srt['focal_len'], linewidth=1, color='tab:orange')
    axes[1].set_title('Focal length (35mm equiv) over time')
    axes[1].set_xlabel('time (s)'); axes[1].set_ylabel('focal_len (mm)')
    axes[2].plot(srt['longitude'], srt['latitude'], marker='.', markersize=2, linewidth=1, color='tab:green')
    axes[2].set_title('SRT trajectory (lon/lat)')
    axes[2].set_xlabel('longitude'); axes[2].set_ylabel('latitude')
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.suptitle(f'Module 2: SRT telemetry — {srt_path.stem[:60]}')
    fig.tight_layout()
    fig.savefig(LAB_DIR / 'module2_srt_telemetry.png', dpi=130)
    plt.show()
""",
)

MODULE3_MD = md(
    """## Module 3 · cv-pipeline (detection, plates, OCR, tracking)

The next cells (already part of this notebook) walk through the perception
module:

- `LazyModels` lazy-loads the segmentation vehicle model and the plate model.
- `license_plate_service` proposes plate candidates from vehicle crops.
- `run_plate_ocr` gates OCR by sharpness and box geometry.
- `assign_vehicle_tracks` links detections across frames using IoU +
  signature similarity, which drives OCR reuse decisions.

Continue to the cells below to inspect each stage visually.
""",
)

MODULE4_MD = md(
    """## Module 4 · Integration: sync + fused geospatial report

`sync_detections_with_srt.py` stamps every detection with the nearest SRT
record; `fuse_plate_observations.py` merges repeated observations of the same
vehicle into one geospatial record with `geolocation_mode` and
`geo_spread_m`. The cell below renders the integrated map and fusion
statistics, and exports them for the apps.
""",
)

MODULE4_CODE = code(
    """fused_dirs = sorted(ROOT.glob('output/cv/*/fused/*.fused.csv'))
geotagged_csvs = sorted(ROOT.glob('output/cv/*/synced/*.geotagged.csv'))
report_geojsons = sorted(ROOT.glob('output/cv/*/lp_vehicle_report.geojson'))

if fused_dirs and geotagged_csvs:
    fused_path = fused_dirs[0]
    geo_path = geotagged_csvs[0]
    fused_df = pd.read_csv(fused_path)
    geo_df = pd.read_csv(geo_path)
    print('Fused records:', len(fused_df), '| Geotagged detections:', len(geo_df))
    print('Fused columns:', list(fused_df.columns)[:14])

    fig, axes = plt.subplots(1, 2, figsize=(18, 6))
    axes[0].scatter(geo_df['longitude'], geo_df['latitude'], s=3, c='#94a3b8', label='drone pose (SRT sync)')
    has_ll = 'latitude' in fused_df.columns and 'longitude' in fused_df.columns
    if has_ll and not fused_df[['latitude', 'longitude']].dropna().empty:
        axes[0].scatter(fused_df['longitude'], fused_df['latitude'], s=45, c='tab:red', marker='^', label='fused object points')
    axes[0].set_title('Integrated map: drone path vs fused object points')
    axes[0].set_xlabel('longitude'); axes[0].set_ylabel('latitude')
    axes[0].legend(); axes[0].grid(True, alpha=0.25)

    if 'fused_confidence' in fused_df.columns:
        fused_df['fused_confidence'].hist(bins=20, ax=axes[1])
        axes[1].set_title('Fused plate confidence distribution')
        axes[1].set_xlabel('confidence')
    elif 'plate_confidence' in fused_df.columns:
        fused_df['plate_confidence'].hist(bins=20, ax=axes[1])
        axes[1].set_title('Plate confidence distribution')
        axes[1].set_xlabel('confidence')
    else:
        axes[1].text(0.5, 0.5, 'no confidence column', ha='center', va='center', transform=axes[1].transAxes)
    axes[1].grid(True, alpha=0.25)
    fig.suptitle('Module 4: integrated sync + fusion report')
    fig.tight_layout()
    fig.savefig(LAB_DIR / 'module4_integration_fusion.png', dpi=130)
    plt.show()
else:
    print('No fused/geotagged outputs yet. Run scripts/run_lp_geospatial_pipeline.sh on a mission first.')

if report_geojsons:
    report_path = report_geojsons[0]
    with report_path.open('r', encoding='utf-8') as f:
        gj = json.load(f)
    features = gj.get('features', [])
    modes = {}
    for feat in features:
        props = feat.get('properties', {})
        modes[props.get('geolocation_mode', 'unknown')] = modes.get(props.get('geolocation_mode', 'unknown'), 0) + 1
    print('Report GeoJSON:', report_path.name, '| features:', len(features), '| geolocation modes:', modes)
""",
)

MODULE5_MD = md(
    """## Module 5 · render_overlay_video (motion)

The overlay renderer composites the detection HUD with telemetry. The motion
cell below reuses its optical-flow engine to produce the workshop motion view
and exports the frame for the apps. This is the visualization that will feed
the "Live preview performance demo" in the desktop app.
""",
)

MODULE5_CODE = code(
    """from pathlib import Path as _Path

_demo_idx = FRAME_PAIR_INDEX if 'FRAME_PAIR_INDEX' in globals() else 240
_prev_idx = max(0, _demo_idx - FRAME_STEP)
_prev_frame = read_frame(VIDEO_PATH, _prev_idx)
_curr_frame = read_frame(VIDEO_PATH, _demo_idx)
_roi = choose_motion_roi((_curr_frame.shape[0], _curr_frame.shape[1]), padding=30)
_flow_overlay, _flow_summary = render_optical_flow(_prev_frame, _curr_frame, box=_roi, motion_scale=35.0)
print('flow summary:', _flow_summary)

_fig, _axes = plt.subplots(1, 2, figsize=(18, 7))
_axes[0].imshow(as_rgb(_curr_frame)); _axes[0].set_title(f'Frame {_demo_idx}'); _axes[0].axis('off')
_axes[1].imshow(as_rgb(_flow_overlay)); _axes[1].set_title(f'Optical flow overlay (ROI {_roi})'); _axes[1].axis('off')
_fig.suptitle('Module 5: overlay motion view')
_fig.tight_layout()
_fig.savefig(LAB_DIR / 'module5_overlay_flow.png', dpi=130)
plt.show()
""",
)

EXPORT_MD = md(
    """## Lab artifact export for the apps

Every module cell above has saved its figure to `output/lab-artifacts/`.
This final cell writes `manifest.json` so the web-dashboard and the Tauri
desktop app can list and render the workshop visualizations without running
the notebook.
""",
)

EXPORT_CODE = code(
    """manifest = []
for artifact in sorted(LAB_DIR.glob('*.png')):
    manifest.append({
        'name': artifact.name,
        'path': str(artifact.relative_to(ROOT)),
        'module': artifact.name.split('_')[0],
    })
manifest_path = LAB_DIR / 'manifest.json'
manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('manifest:', manifest_path, '| artifacts:', len(manifest))
for entry in manifest:
    print(' -', entry['name'])
""",
)


def main() -> None:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells = nb["cells"]

    def has_marker(text: str) -> bool:
        return any(
            any(text in line for line in (c.get("source") or []))
            for c in cells
        )

    if not has_marker("IntelSight Workshop Lab"):
        cells[0] = WORKSHOP_HEADER
        print("replaced header cell")

    insert_at = None
    for i, c in enumerate(cells):
        src = c.get("source") or []
        if src and src[0].startswith("MISSION_DIR = ROOT"):
            insert_at = i + 1
            break
    if insert_at is not None and not has_marker("draw_pipeline_diagram"):
        cells[insert_at:insert_at] = [
            MODULE_MAP_CODE,
            MODULE1_MD,
            MODULE1_CODE,
            MODULE2_MD,
            MODULE2_CODE,
            MODULE3_MD,
        ]
        print("inserted module map + modules 1-3 at", insert_at)

    if not has_marker("## Module 4 · Integration"):
        insert_before = None
        for i, c in enumerate(cells):
            src = c.get("source") or []
            if src and src[0].startswith("## What To Look For"):
                insert_before = i
                break
        if insert_before is None:
            insert_before = len(cells)
        cells[insert_before:insert_before] = [
            MODULE4_MD,
            MODULE4_CODE,
            MODULE5_MD,
            MODULE5_CODE,
            EXPORT_MD,
            EXPORT_CODE,
        ]
        print("inserted modules 4-5 + export before cell", insert_before)

    NOTEBOOK.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", NOTEBOOK)


if __name__ == "__main__":
    main()
