# Mission Dashboard Sprint Plan

This plan turns the dashboard checklist into a build order for making the IntelSight Tauri app the main mission aggregation and digestion console.

## Sprint 1: stabilize mission selection and scan flow

Goal: make folder selection, scan state, and mission switching reliable before adding more surfaces.

- Fix the Browse Folder -> active mission root flow end-to-end.
- Keep scan readiness visible and disable scanning when no mission root is present.
- Preserve selected mission state on failures.
- Add recent mission root and rescan behavior.
- Confirm deterministic artifact ordering after repeated scans.

Exit criteria:

- User can select a mission folder and the scan target updates immediately.
- Scan failures do not clear the current mission root.
- Repeated scans of the same folder behave consistently.

## Sprint 2: mission console shell and summary dashboard

Goal: give the app a coherent operator-console frame.

- Keep the tabbed Mission Explorer shell as the main navigation frame.
- Add overview KPI cards and mission digestion indicators.
- Add charts for artifact counts, preview row counts, and confidence trends.
- Add visible loading, empty, and error states for each dashboard panel.
- Add saved-panel-ready layout spacing for future growth.

Exit criteria:

- Overview shows mission-level summary without leaving the main shell.
- The user can understand mission state at a glance.

## Sprint 3: media player and CV preview workflow

Goal: inspect footage without processing whole videos repeatedly.

- Add original video playback controls.
- Add overlay playback controls for detection, segmentation, OCR, and motion views.
- Add synchronized frame scrubber and clip bookmarking.
- Add CV preview from cached frames instead of full pipeline reruns.
- Add side-by-side original vs overlay comparison mode.

Exit criteria:

- Operator can review original and overlay media in a single flow.
- CV previews can be inspected without forcing full mission reprocessing.

## Sprint 4: map, trajectory, and localization views

Goal: make the dashboard spatially useful.

- Add interactive map layers driven by the cumulative mission database.
- Plot 2D drone trajectory with object registrations.
- Add geofence and object clustering overlays.
- Add simplified 3D scatter plotting for estimated object localization.
- Distinguish telemetry-anchored, fused, and proxy-derived points.

Exit criteria:

- Mission objects are visible on a map and linked to trajectory context.
- Basic 3D localization is visible without waiting for advanced reconstruction.

## Sprint 5: perception overlays and review tooling

Goal: make model outputs inspectable and debuggable.

- Add technique overlays for detections, masks, OCR, optical flow, and heatmaps.
- Add confidence filters and object-class filtering.
- Add per-record drill-down from the data table to map and media contexts.
- Add provenance display for source file, backend, and processing stage.

Exit criteria:

- Operator can explain why a detection exists and how it was derived.

## Sprint 6: license plate reader restoration

Goal: restore plate review after the dashboard shell is stable.

- Add plate crop review and OCR confidence indicators.
- Add plate normalization and candidate text selection.
- Add plate review queue and evidence cards.
- Reintroduce plate history once validation is acceptable.

Exit criteria:

- Plate review works inside the dashboard and is part of the mission workflow.

## Sprint 7: aggregation, export, and expansion

Goal: make the app the long-term mission aggregation hub.

- Add saved missions, export actions, and report generation.
- Add cumulative database browsing and mission timeline views.
- Add additional artifact classes such as imagery, PDFs, and derived reports.
- Prepare the shell for future PX4 and live autonomy integration.

Exit criteria:

- The app can serve as the primary review and digestion surface for mission operations.

## Recommended order of implementation

1. Sprint 1
2. Sprint 2
3. Sprint 3
4. Sprint 4
5. Sprint 5
6. Sprint 6
7. Sprint 7