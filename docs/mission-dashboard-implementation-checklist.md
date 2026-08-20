# Mission Dashboard Implementation Checklist

This checklist defines the work required to make the IntelSight Tauri app the primary dashboard for mission data aggregation, digestion, review, and future operator workflows.

Execution order: [docs/mission-dashboard-sprint-plan.md](docs/mission-dashboard-sprint-plan.md)

## 1. Mission shell and navigation

- [ ] Keep the current IntelSight mission explorer shell as the top-level frame.
- [ ] Add a persistent mission header with mission name, mission root, dataset type, and scan state.
- [ ] Add a left-side control rail or tab strip for source, map, video, perception, timeline, analytics, and exports.
- [ ] Preserve a stable layout so panels can change without moving the primary mission context.
- [ ] Add recent missions, saved missions, and reload-last-mission shortcuts.

## 2. Source selection and scan control

- [ ] Make Browse Folder update the active mission root every time.
- [ ] Show the selected mission path immediately in the data source control.
- [ ] Add validation feedback when the selected folder is invalid or empty.
- [ ] Add scan progress, scan completion, and scan failure states.
- [ ] Add rescan, refresh, and clear-selection actions.
- [ ] Allow scanning the mission root without requiring app restart.

## 3. Mission summary and control dashboard

- [ ] Add KPI cards for frames, detections, plates, OCR hits, geotagged records, fused objects, and geofence matches.
- [ ] Add charts for confidence distribution, detection counts over time, OCR success rate, and geolocation spread.
- [ ] Add mission-level throughput and processing-health indicators.
- [ ] Add a quality panel for missing telemetry, skipped frames, low-confidence detections, and failed parse events.

## 4. Video player and media review

- [ ] Add a video player with original media playback controls.
- [ ] Add overlay playback controls for detection overlays, tracking overlays, and motion overlays.
- [ ] Add synchronized scrubber, play/pause, step frame, speed, loop, and seek-to-detection controls.
- [ ] Add side-by-side or stacked comparison for original vs overlay playback.
- [ ] Add clip extraction and bookmarked evidence frame controls.
- [ ] Add preview-first review so operators can inspect CV results without processing entire videos repeatedly.

## 5. Computer vision preview and perception overlays

- [ ] Add a CV preview panel for detections, masks, OCR boxes, track IDs, and confidence thresholds.
- [ ] Add technique toggles for YOLO boxes, segmentation masks, OCR regions, optical flow, and motion heatmaps.
- [ ] Add a perception-technique visualization legend so operators know what each overlay means.
- [ ] Add controls to filter by class, confidence, time span, and object track.
- [ ] Add a fast preview mode that reuses cached frames and avoids full video reprocessing.

## 6. Mapping and geospatial visualization

- [ ] Add an interactive map tied to the cumulative mission database.
- [ ] Plot drone trajectory as a 2D path with time scrub and mission segments.
- [ ] Plot registered objects at their estimated 2D ground positions.
- [ ] Add geofence overlays, heatmaps, and cluster layers.
- [ ] Add a 3D mapping view starting with a simplified scatter plot of estimated object localization.
- [ ] Distinguish telemetry-anchored points, fused object estimates, and review-only approximations.

## 7. Objects, localization, and evidence review

- [ ] Add a registered-object table with search, filter, sort, and row focus.
- [ ] Show object identity, class, confidence, time span, geolocation mode, and spread.
- [ ] Add drill-down from object rows to map, video, and annotation preview.
- [ ] Add export actions for GeoJSON, CSV, and future database-backed records.
- [ ] Add provenance metadata for source frame, telemetry source, and inference backend.

## 8. Charts and analytics

- [ ] Add mission charts for detections over time, OCR hit rate, geolocation spread, and confidence trends.
- [ ] Add cumulative object counts by type, geofence, and time window.
- [ ] Add quality charts for motion stability, frame quality, and overlay health.
- [ ] Add analyst-friendly breakdowns for parking-lot review, facility review, and recurring-object review.

## 9. Data aggregation and digestion

- [ ] Make the dashboard the central aggregation surface for raw logs, derived outputs, and review artifacts.
- [ ] Support mission data ingestion from flight logs, geotagged frames, detections, OCR outputs, and geospatial summaries.
- [ ] Add artifact grouping by mission, run, backend, and processing stage.
- [ ] Add filters for raw, normalized, fused, and map-ready outputs.
- [ ] Maintain deterministic ordering across repeated scans.

## 10. License plate reader integration

- [ ] Restore and validate the license plate reader after the dashboard shell is stable.
- [ ] Add plate crop preview, plate confidence, normalization, and OCR text quality indicators.
- [ ] Add plate review queue and per-frame plate evidence cards.
- [ ] Add plate-history association once provenance and validation are stable.
- [ ] Keep plate workflows gated by lawful, privacy-aware, mission-scoped controls.

## 11. Reliability, state, and operator ergonomics

- [ ] Preserve selected mission state on failures.
- [ ] Show clear empty, loading, success, and error states.
- [ ] Keep all backend errors visible and recoverable.
- [ ] Add keyboard reachability and high-contrast focus states.
- [ ] Keep controls usable at laptop and workstation resolutions.
- [ ] Make scan and playback actions cancelable where practical.

## 12. Future expansion

- [ ] Reserve space for timeline, exports, saved views, and model switching.
- [ ] Keep the UI extensible for future PX4 and live-autonomy integration.
- [ ] Keep the layout compatible with future multi-panel analysis and fleet-level data aggregation.

## Delivery order

1. Fix mission folder selection and scan state flow.
2. Add the mission dashboard shell, summary cards, and charts.
3. Add video playback with original and overlay controls.
4. Add CV preview overlays and fast frame-review mode.
5. Add interactive map, 2D trajectory view, and simplified 3D scatter plot.
6. Re-enable and harden the license plate reader workflow.