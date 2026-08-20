import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Channel, convertFileSrc, invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import "leaflet/dist/leaflet.css";
import "./App.css";

type FileCandidate = {
  path: string;
  kind: string;
  name: string;
  size_bytes: number;
};

type ScanResult = {
  trajectory: FileCandidate[];
  detections: FileCandidate[];
  summary: FileCandidate[];
  media: FileCandidate[];
};

type ScanState = "idle" | "scanning" | "success" | "empty" | "error";
type DashboardTab = "overview" | "video" | "map" | "database" | "charts" | "lab" | "settings";

type LabArtifact = {
  name: string;
  path: string;
  module: string;
};

const LAB_MODULE_NAMES: Record<string, string> = {
  pipeline: "Integration · module map",
  module1: "Module 1 · flightrecord-parser (Rust)",
  module2: "Module 2 · flight-visualizer (SRT)",
  module3: "Module 3 · cv-pipeline (detection + plates)",
  module4: "Module 4 · sync + fused report",
  module5: "Module 5 · overlay motion",
};

type GeolocatedObject = {
  track_id: number;
  class_name: string;
  confidence: number;
  first_frame: number;
  last_frame: number;
  observations: number;
  latitude: number | null;
  longitude: number | null;
  geo_spread_m?: number | null;
  relative_altitude_m: number | null;
  geolocation_mode: string;
  representative_crop_path?: string | null;
  local_feature_matches_avg?: number;
  local_feature_matches_max?: number;
  identity_score_avg?: number;
  identity_method?: string;
  plate_status?: string;
  plate_text?: string | null;
};

type GeolocatedObservation = {
  frame: number;
  timestamp_sec: number;
  latitude: number | null;
  longitude: number | null;
  relative_altitude_m: number | null;
  confidence: number;
  class_name: string;
  geolocation_mode: string;
};

function hasPosition(
  item: GeolocatedObservation,
): item is GeolocatedObservation & { latitude: number; longitude: number } {
  return item.latitude !== null && item.longitude !== null;
}

type CvPreviewResult = {
  overlay_path: string;
  detections_path: string;
  database_path: string;
  processed_frames: number;
  observation_count: number;
  objects: GeolocatedObject[];
  track_history?: Record<string, GeolocatedObservation[]>;
  video_fps?: number;
  video_width?: number;
  video_height?: number;
  configuration?: {
    detections: boolean;
    optical_flow: boolean;
    reid: boolean;
    confidence: number;
    frame_step: number;
    duration_seconds: number;
    start_offset_seconds?: number;
    roi_padding: number;
    device: string;
  };
};

type FrameRecord = {
  frame: number;
  vehicle_boxes: Array<{
    xyxy: number[];
    class_name: string;
    confidence: number;
    track_id?: number;
  }>;
  optical_flow_mean_px: number;
  local_feature_matches?: Record<string, number>;
  telemetry?: Record<string, unknown>;
};

type CvConfiguration = {
  detections: boolean;
  opticalFlow: boolean;
  reid: boolean;
  confidence: number;
  frameStep: number;
  durationSeconds: number;
  startOffsetSeconds: number;
  roiPadding: number;
  device: string;
};

type ProgressUpdate = {
  phase: string;
  current: number;
  total: number;
  message: string;
};

const recentMissionsKey = "intelsight.recentMissions";
const settingsKey = "intelsight.settings";

type AppSettings = {
  device: string;
  confidence: number;
  frameStep: number;
  durationSeconds: number;
  startOffsetSeconds: number;
  roiPadding: number;
  rememberMissionRoot: boolean;
  lastMissionRoot: string;
  defaultHistoryMode: "latest" | "history";
};

const defaultSettings: AppSettings = {
  device: "0",
  confidence: 0.35,
  frameStep: 5,
  durationSeconds: 10,
  startOffsetSeconds: 10,
  roiPadding: 48,
  rememberMissionRoot: false,
  lastMissionRoot: "",
  defaultHistoryMode: "latest",
};

function readRecentMissions() {
  try {
    return JSON.parse(localStorage.getItem(recentMissionsKey) ?? "[]") as string[];
  } catch {
    return [];
  }
}

function readSettings(): AppSettings {
  try {
    const parsed = JSON.parse(localStorage.getItem(settingsKey) ?? "{}") as Partial<AppSettings>;
    return { ...defaultSettings, ...parsed };
  } catch {
    return { ...defaultSettings };
  }
}

function missionName(path: string) {
  return path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "Unselected mission";
}

function humanSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isMediaVideo(name: string) {
  return /\.(mp4|mov|m4v|avi)$/i.test(name);
}

function isMediaImage(name: string) {
  return /\.(jpg|jpeg|png|webp)$/i.test(name);
}

function OperationProgress({ progress }: { progress: ProgressUpdate }) {
  const total = Math.max(1, progress.total);
  const percent = Math.min(100, Math.max(0, Math.round((progress.current / total) * 100)));
  return (
    <div className="operation-progress" aria-live="polite">
      <div className="progress-heading">
        <span>{progress.message}</span>
        <strong>{percent}%</strong>
      </div>
      <progress value={progress.current} max={total} aria-label={progress.message}>{percent}%</progress>
    </div>
  );
}

function VideoPlayer({ path, label }: { path: string; label: string }) {
  const [source, setSource] = useState("");
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    setSource("");
    setPlaybackError(null);

    invoke<ArrayBuffer>("read_media_file", { path })
      .then((bytes) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(new Blob([bytes], { type: "video/mp4" }));
        setSource(objectUrl);
      })
      .catch((err) => {
        if (!cancelled) setPlaybackError(`Could not load ${label}: ${String(err)}`);
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [label, path]);

  useEffect(() => {
    if (!expanded) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [expanded]);

  if (playbackError) return <p className="media-error">{playbackError}</p>;
  if (!source) return <p className="media-loading">Loading {label}...</p>;
  return <div className={`video-player${expanded ? " expanded" : ""}`}>
    <button type="button" className="expand-video" onClick={() => setExpanded(!expanded)}>{expanded ? "Close expanded view" : "Expand video"}</button>
    <video
        controls
        preload="metadata"
        src={source}
        onError={(event) => {
          const mediaError = event.currentTarget.error;
          setPlaybackError(`${label} cannot be decoded (media error ${mediaError?.code ?? "unknown"}).`);
        }}
      />
  </div>;
}

function FitMapBounds({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(bounds, { padding: [28, 28], maxZoom: 19 });
  }, [bounds, map]);
  return null;
}

function LabImage({ artifact }: { artifact: LabArtifact }) {
  const [source, setSource] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    setSource("");
    setLoadError(null);

    invoke<ArrayBuffer>("read_media_file", { path: artifact.path })
      .then((bytes) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
        setSource(objectUrl);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(String(err));
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [artifact.path]);

  if (loadError) return <div className="lab-image-error" title={loadError}>Could not load {artifact.name}</div>;
  if (!source) return <div className="lab-image-loading">Loading {artifact.name}...</div>;
  return <img className="lab-artifact-image" src={source} alt={artifact.name} />;
}

type PositionedObservation = GeolocatedObservation & { latitude: number; longitude: number };

function IdentityProfile({
  identity,
  history,
  onBack,
  emptyHint,
}: {
  identity: (GeolocatedObject & { latitude: number; longitude: number }) | null;
  history: PositionedObservation[];
  onBack: () => void;
  emptyHint: string;
}) {
  if (!identity) {
    return <div className="identity-profile-empty"><strong>Select an identity</strong><span>{emptyHint}</span></div>;
  }
  return (
    <>
      <div className="identity-profile-heading"><span>Identity profile</span><strong>#{identity.track_id}</strong></div>
      {identity.representative_crop_path ? <img src={convertFileSrc(identity.representative_crop_path)} alt={`Representative ROI for identity ${identity.track_id}`} /> : <div className="identity-crop-empty">No representative ROI</div>}
      <h4>{identity.class_name}</h4>
      <dl>
        <div><dt>Sightings</dt><dd>{identity.observations}</dd></div>
        <div><dt>Frames</dt><dd>{identity.first_frame}–{identity.last_frame}</dd></div>
        <div><dt>Detection confidence</dt><dd>{Math.round(identity.confidence * 100)}%</dd></div>
        <div><dt>Re-ID score</dt><dd>{Math.round((identity.identity_score_avg ?? 0) * 100)}%</dd></div>
        <div><dt>ORB matches</dt><dd>{(identity.local_feature_matches_avg ?? 0).toFixed(1)} avg · {identity.local_feature_matches_max ?? 0} max</dd></div>
        <div><dt>Geo locality</dt><dd>{identity.latitude.toFixed(6)}, {identity.longitude.toFixed(6)}</dd></div>
        <div><dt>Position spread</dt><dd>{identity.geo_spread_m != null ? `${identity.geo_spread_m.toFixed(2)} m` : "--"}</dd></div>
        <div><dt>Position model</dt><dd>{identity.geolocation_mode.replace(/_/g, " ")}</dd></div>
        <div><dt>License plate</dt><dd>{identity.plate_text ?? (identity.plate_status === "not_run" ? "Not run" : "Unavailable")}</dd></div>
      </dl>
      <div className="identity-history-heading"><span>Observation history</span><button type="button" onClick={onBack}>Back to all</button></div>
      {history.length > 0 ? (
        <ul className="identity-history-list">
          {[...history].slice(-12).reverse().map((item) => (
            <li key={item.frame}>
              <span>frame {item.frame}</span>
              <span>{item.latitude.toFixed(6)}, {item.longitude.toFixed(6)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="identity-history-empty">No geotagged observations for this identity.</div>
      )}
    </>
  );
}

function InteractiveCvViewer({
  videoPath,
  detectionsPath,
  startOffsetSeconds,
  durationSeconds,
  videoFps,
  videoWidth,
  videoHeight,
  onUseFrameAsOffset,
}: {
  videoPath: string;
  detectionsPath: string;
  startOffsetSeconds: number;
  durationSeconds: number;
  videoFps: number;
  videoWidth: number;
  videoHeight: number;
  onUseFrameAsOffset: (offsetSeconds: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [records, setRecords] = useState<FrameRecord[]>([]);
  const [proxyPath, setProxyPath] = useState("");
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [currentFrame, setCurrentFrame] = useState<number | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [showLabels, setShowLabels] = useState(true);

  useEffect(() => {
    invoke<FrameRecord[]>("read_detections_jsonl", { path: detectionsPath })
      .then(setRecords)
      .catch((err) => setViewerError(String(err)));
  }, [detectionsPath]);

  useEffect(() => {
    let cancelled = false;
    const onProgress = new Channel<ProgressUpdate>();
    invoke<string>("prepare_media_preview", {
      path: videoPath,
      startSeconds: startOffsetSeconds,
      durationSeconds: durationSeconds,
      onProgress,
    })
      .then((path) => {
        if (!cancelled) setProxyPath(path);
      })
      .catch((err) => {
        if (!cancelled) setViewerError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [videoPath, startOffsetSeconds, durationSeconds]);

  const frameIndex = useMemo(() => {
    const map = new Map<number, FrameRecord>();
    for (const record of records) map.set(record.frame, record);
    return map;
  }, [records]);

  const frameNumbers = useMemo(
    () => records.map((record) => record.frame).sort((a, b) => a - b),
    [records],
  );

  const minFrame = frameNumbers[0] ?? 0;
  const maxFrame = frameNumbers[frameNumbers.length - 1] ?? 0;

  function drawOverlay() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    const displayWidth = video.clientWidth;
    const displayHeight = video.clientHeight;
    if (displayWidth === 0 || displayHeight === 0) return;
    if (canvas.width !== displayWidth) canvas.width = displayWidth;
    if (canvas.height !== displayHeight) canvas.height = displayHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, displayWidth, displayHeight);
    if (!showBoxes || currentFrame == null) return;
    const record = frameIndex.get(currentFrame);
    if (!record) return;
    const scaleX = displayWidth / (videoWidth || 1);
    const scaleY = displayHeight / (videoHeight || 1);
    for (const box of record.vehicle_boxes) {
      const [x1, y1, x2, y2] = box.xyxy;
      ctx.strokeStyle = "#00e6dc";
      ctx.lineWidth = 2;
      ctx.strokeRect(x1 * scaleX, y1 * scaleY, (x2 - x1) * scaleX, (y2 - y1) * scaleY);
      if (showLabels) {
        ctx.fillStyle = "#00e6dc";
        ctx.font = "13px sans-serif";
        const label = `${box.class_name} ${(box.confidence * 100).toFixed(0)}%${box.track_id != null ? ` #${box.track_id}` : ""}`;
        ctx.fillText(label, x1 * scaleX, Math.max(16, y1 * scaleY - 5));
      }
    }
  }

  function onTimeUpdate() {
    const video = videoRef.current;
    if (!video || frameNumbers.length === 0) return;
    const originalFrame = Math.round((startOffsetSeconds + video.currentTime) * videoFps);
    let nearest = frameNumbers[0];
    let best = Number.POSITIVE_INFINITY;
    for (const frame of frameNumbers) {
      const distance = Math.abs(frame - originalFrame);
      if (distance < best) {
        best = distance;
        nearest = frame;
      }
    }
    setCurrentFrame(nearest);
  }

  useEffect(() => {
    drawOverlay();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentFrame, showBoxes, showLabels, records, proxyPath]);

  function seekToFrame(frame: number) {
    const video = videoRef.current;
    if (!video || videoFps <= 0) return;
    const proxyTime = frame / videoFps - startOffsetSeconds;
    video.currentTime = Math.max(0, proxyTime);
    setCurrentFrame(frame);
  }

  function useCurrentFrameAsOffset() {
    const video = videoRef.current;
    if (!video) return;
    const absoluteSeconds = startOffsetSeconds + video.currentTime;
    onUseFrameAsOffset(Math.max(0, Math.round(absoluteSeconds)));
  }

  if (viewerError) return <div className="media-error">Interactive viewer error: {viewerError}</div>;
  if (!proxyPath) return <div className="media-loading">Preparing seekable preview for the CV window...</div>;

  return (
    <div className="interactive-viewer">
      <div className="interactive-stage">
        <video
          ref={videoRef}
          src={convertFileSrc(proxyPath)}
          controls
          preload="auto"
          onTimeUpdate={onTimeUpdate}
          onLoadedMetadata={drawOverlay}
          onSeeked={onTimeUpdate}
        />
        <canvas ref={canvasRef} className="interactive-canvas" />
      </div>
      <div className="interactive-controls">
        <label className="toggle-row compact">
          <input type="checkbox" checked={showBoxes} onChange={(event) => setShowBoxes(event.target.checked)} />
          <span>Boxes</span>
        </label>
        <label className="toggle-row compact">
          <input type="checkbox" checked={showLabels} onChange={(event) => setShowLabels(event.target.checked)} />
          <span>Labels</span>
        </label>
        <span className="interactive-frame-readout">Frame {currentFrame ?? "--"} · {frameNumbers.length} sampled frames</span>
      </div>
      <div className="interactive-scrubber">
        <input
          type="range"
          min={minFrame}
          max={maxFrame}
          step={1}
          value={currentFrame ?? minFrame}
          onChange={(event) => seekToFrame(Number(event.target.value))}
          aria-label="Frame scrubber"
        />
        <button type="button" onClick={useCurrentFrameAsOffset}>Use current frame as start offset</button>
      </div>
    </div>
  );
}

function App() {
  const [rootDir, setRootDir] = useState(() => readRecentMissions()[0] ?? "");
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [selectedTrajectory, setSelectedTrajectory] = useState<string>("");
  const [selectedDetection, setSelectedDetection] = useState<string>("");
  const [selectedMedia, setSelectedMedia] = useState<string>("");
  const [preview, setPreview] = useState<Array<Record<string, unknown>>>([]);
  const [status, setStatus] = useState("Ready to inspect a mission folder.");
  const [error, setError] = useState<string | null>(null);
  const [scanState, setScanState] = useState<ScanState>("idle");
  const [scannedRoot, setScannedRoot] = useState("");
  const [recentMissions, setRecentMissions] = useState<string[]>(readRecentMissions);
  const [playableMedia, setPlayableMedia] = useState("");
  const [mediaState, setMediaState] = useState<"idle" | "preparing" | "ready" | "error">("idle");
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DashboardTab>("overview");
  const [cvState, setCvState] = useState<"idle" | "running" | "ready" | "error">("idle");
  const [cvRunCount, setCvRunCount] = useState(0);
  const [cvError, setCvError] = useState<string | null>(null);
  const [cvResult, setCvResult] = useState<CvPreviewResult | null>(null);
  const [scanProgress, setScanProgress] = useState<ProgressUpdate | null>(null);
  const [mediaProgress, setMediaProgress] = useState<ProgressUpdate | null>(null);
  const [cvProgress, setCvProgress] = useState<ProgressUpdate | null>(null);
  const [selectedIdentityId, setSelectedIdentityId] = useState<number | null>(null);
  const [labArtifacts, setLabArtifacts] = useState<LabArtifact[]>([]);
  const [labError, setLabError] = useState<string | null>(null);
  const [settings, setSettings] = useState<AppSettings>(readSettings);
  const [historyMode, setHistoryMode] = useState<"latest" | "history">(readSettings().defaultHistoryMode);
  const [cvConfig, setCvConfig] = useState<CvConfiguration>(() => {
    const saved = readSettings();
    return {
      detections: true,
      opticalFlow: false,
      reid: true,
      confidence: saved.confidence,
      frameStep: saved.frameStep,
      durationSeconds: saved.durationSeconds,
      startOffsetSeconds: saved.startOffsetSeconds,
      roiPadding: saved.roiPadding,
      device: saved.device,
    };
  });

  const hasFiles = useMemo(
    () => !!scanResult && Object.values(scanResult).some((items) => items.length > 0),
    [scanResult],
  );

  const loadLabArtifacts = useCallback(() => {
    setLabError(null);
    invoke<LabArtifact[]>("list_lab_artifacts")
      .then((artifacts) => setLabArtifacts(artifacts))
      .catch((err) => setLabError(String(err)));
  }, []);

  useEffect(() => {
    loadLabArtifacts();
  }, [loadLabArtifacts]);

  useEffect(() => {
    if (settings.rememberMissionRoot && settings.lastMissionRoot && !rootDir) {
      setRootDir(settings.lastMissionRoot);
      setStatus(`Restored mission root from settings: ${settings.lastMissionRoot}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function persistSettings(next: AppSettings) {
    localStorage.setItem(settingsKey, JSON.stringify(next));
    setSettings(next);
  }

  function applySettingsToWorkbench(next: AppSettings) {
    setCvConfig((previous) => ({
      ...previous,
      device: next.device,
      confidence: next.confidence,
      frameStep: next.frameStep,
      durationSeconds: next.durationSeconds,
      startOffsetSeconds: next.startOffsetSeconds,
      roiPadding: next.roiPadding,
    }));
    setHistoryMode(next.defaultHistoryMode);
  }

  function saveSettings() {
    persistSettings(settings);
    applySettingsToWorkbench(settings);
    setStatus("Settings saved and applied to the workbench.");
  }

  function resetSettings() {
    const reset = { ...defaultSettings };
    persistSettings(reset);
    applySettingsToWorkbench(reset);
    setStatus("Settings reset to defaults.");
  }

  function clearRecentMissions() {
    localStorage.removeItem(recentMissionsKey);
    setRecentMissions([]);
    setStatus("Recent missions cleared.");
  }
  const canScan = rootDir.trim().length > 0 && scanState !== "scanning";
  const telemetryPoints = useMemo(
    () => preview
      .map((row) => ({
        latitude: Number(row.latitude),
        longitude: Number(row.longitude),
        altitude: Number(row.relative_altitude_m),
        frame: Number(row.frame),
      }))
      .filter((point) => Number.isFinite(point.latitude) && Number.isFinite(point.longitude)),
    [preview],
  );
  const mapPoints = useMemo(() => {
    if (telemetryPoints.length <= 400) return telemetryPoints;
    const stride = Math.ceil(telemetryPoints.length / 400);
    return telemetryPoints.filter((_, index) => index % stride === 0);
  }, [telemetryPoints]);
  const geolocatedObjects = useMemo(
    () => (cvResult?.objects ?? []).filter(
      (item): item is GeolocatedObject & { latitude: number; longitude: number } =>
        item.latitude !== null && item.longitude !== null,
    ),
    [cvResult],
  );
  const selectedIdentity = useMemo(
    () => geolocatedObjects.find((item) => item.track_id === selectedIdentityId) ?? null,
    [geolocatedObjects, selectedIdentityId],
  );
  const selectedIdentityHistory = useMemo(() => {
    if (selectedIdentityId == null || !cvResult?.track_history) return [];
    return (cvResult.track_history[String(selectedIdentityId)] ?? []).filter(hasPosition);
  }, [cvResult, selectedIdentityId]);
  const flattenedHistoryPoints = useMemo(() => {
    if (!cvResult?.track_history) return [];
    const points: Array<GeolocatedObservation & { trackId: number; latitude: number; longitude: number }> = [];
    for (const [trackId, items] of Object.entries(cvResult.track_history)) {
      for (const item of items) {
        if (hasPosition(item)) {
          points.push({ ...item, trackId: Number(trackId) });
        }
      }
    }
    return points;
  }, [cvResult]);
  const mapBounds = useMemo<LatLngBoundsExpression | null>(() => {
    const positions = [
      ...mapPoints.map((point) => [point.latitude, point.longitude] as [number, number]),
      ...geolocatedObjects.map((item) => [item.latitude, item.longitude] as [number, number]),
    ];
    return positions.length ? positions : null;
  }, [geolocatedObjects, mapPoints]);
  const chartBuckets = useMemo(() => {
    if (telemetryPoints.length === 0) return [];
    const bucketSize = Math.max(1, Math.ceil(telemetryPoints.length / 16));
    return Array.from({ length: Math.ceil(telemetryPoints.length / bucketSize) }, (_, index) => {
      const points = telemetryPoints.slice(index * bucketSize, (index + 1) * bucketSize);
      return points.reduce((sum, point) => sum + (Number.isFinite(point.altitude) ? point.altitude : 0), 0) / points.length;
    });
  }, [telemetryPoints]);

  useEffect(() => {
    let cancelled = false;

    async function prepareSelectedMedia() {
      setPlayableMedia("");
      setMediaError(null);
      setMediaProgress(null);

      if (!selectedMedia) {
        setMediaState("idle");
        return;
      }
      if (!isMediaVideo(selectedMedia)) {
        setPlayableMedia(selectedMedia);
        setMediaState("ready");
        return;
      }

      setMediaState("preparing");
      try {
        const onProgress = new Channel<ProgressUpdate>();
        onProgress.onmessage = (update) => {
          if (!cancelled) setMediaProgress(update);
        };
        const previewPath = await invoke<string>("prepare_media_preview", { path: selectedMedia, onProgress });
        if (!cancelled) {
          setPlayableMedia(previewPath);
          setMediaState("ready");
        }
      } catch (err) {
        if (!cancelled) {
          setMediaError(String(err));
          setMediaState("error");
        }
      }
    }

    prepareSelectedMedia();
    return () => {
      cancelled = true;
    };
  }, [selectedMedia]);

  useEffect(() => {
    let cancelled = false;
    setCvResult(null);
    setCvError(null);
    setCvState("idle");
    if (selectedMedia && isMediaVideo(selectedMedia)) {
      invoke<CvPreviewResult | null>("load_cv_result", { videoPath: selectedMedia })
        .then((result) => {
          if (!cancelled && result) {
            setCvResult(result);
            setCvState("ready");
          }
        })
        .catch((err) => {
          if (!cancelled) setCvError(`Saved CV result could not be loaded: ${String(err)}`);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [selectedMedia]);

  function rememberMission(path: string) {
    const updated = [path, ...recentMissions.filter((item) => item !== path)].slice(0, 5);
    setRecentMissions(updated);
    localStorage.setItem(recentMissionsKey, JSON.stringify(updated));
  }

  async function scanMissionFolder() {
    const targetRoot = rootDir.trim();
    if (!targetRoot) {
      setError("Select or enter a mission directory before scanning.");
      setStatus("Mission folder is required.");
      setScanState("error");
      return;
    }

    try {
      setError(null);
      setScanState("scanning");
      setScanProgress({ phase: "discovering", current: 0, total: 1, message: "Discovering mission files" });
      setStatus(`Scanning ${missionName(targetRoot)}...`);
      const onProgress = new Channel<ProgressUpdate>();
      onProgress.onmessage = setScanProgress;
      const result = (await invoke("scan_directory", { dir: targetRoot, onProgress })) as ScanResult;
      setScanResult(result);
      setSelectedTrajectory(result.trajectory[0]?.path ?? "");
      setSelectedDetection(result.detections[0]?.path ?? "");
      setSelectedMedia(result.media[0]?.path ?? "");
      setPreview([]);
      setScannedRoot(targetRoot);
      rememberMission(targetRoot);
      persistSettings({ ...settings, lastMissionRoot: targetRoot });
      setStatus(`Scanned ${result.trajectory.length} trajectory file(s), ${result.detections.length} detection file(s).`);
      setScanState("success");
      if (!Object.values(result).some((items) => items.length > 0)) {
        setStatus("The selected directory contains no supported mission artifacts.");
        setScanState("empty");
      } else if (result.trajectory[0]?.path) {
        await loadPreview(result.trajectory[0].path, false);
      }
    } catch (err) {
      setError(String(err));
      setStatus("Directory scan failed.");
      setScanState("error");
    }
  }

  async function loadPreview(path: string, announce = true) {
    if (!path) return;
    try {
      setError(null);
      const rows = (await invoke("read_annotation_file", { path })) as Array<Record<string, unknown>>;
      setPreview(rows);
      if (announce) {
        setStatus(`Previewing ${rows.length} record(s) from ${path.split(/[\\/]/).pop()}`);
      }
    } catch (err) {
      setError(String(err));
      setStatus("Preview failed to load the selected annotation file.");
    }
  }

  async function handleBrowseFolder() {
    try {
      const selected = await open({
        directory: true,
        multiple: false,
        defaultPath: rootDir || undefined,
        title: "Select mission folder",
      });

      if (typeof selected === "string" && selected.trim()) {
        setRootDir(selected);
        setStatus(`Selected ${missionName(selected)}. Ready to scan.`);
        setScanState("idle");
        setError(null);
      }
    } catch (err) {
      setError(String(err));
      setStatus("Folder selection failed.");
      setScanState("error");
    }
  }

  async function runCvVisualization() {
    if (!selectedMedia || !isMediaVideo(selectedMedia)) {
      setCvError("Select a mission video before running the CV preview.");
      setCvState("error");
      return;
    }
    const videoStem = selectedMedia.replace(/\.[^.]+$/, "").split(/[\\/]/).pop();
    const matchingTelemetry = scanResult?.trajectory.find((item) =>
      item.name.toLowerCase().endsWith(".srt") && item.name.replace(/\.[^.]+$/, "") === videoStem,
    )?.path ?? (selectedTrajectory.toLowerCase().endsWith(".srt") ? selectedTrajectory : "");

    setCvState("running");
    setCvError(null);
    setCvProgress({ phase: "initializing", current: 0, total: 100, message: "Starting CV preview" });
    setStatus(`Running CV preview on ${selectedMedia.split(/[\\/]/).pop()}...`);
    try {
      const onProgress = new Channel<ProgressUpdate>();
      onProgress.onmessage = setCvProgress;
      const result = await invoke<CvPreviewResult>("run_cv_preview", {
        options: {
          videoPath: selectedMedia,
          telemetryPath: matchingTelemetry || null,
          ...cvConfig,
        },
        onProgress,
      });
      setCvResult(result);
      setCvRunCount((count) => count + 1);
      setCvState("ready");
      setSelectedIdentityId(null);
      setActiveTab("video");
      setStatus(`CV preview ready: ${result.objects.length} tracked object(s), ${result.observation_count} observation(s).`);
    } catch (err) {
      setCvError(String(err));
      setCvState("error");
      setStatus("CV preview failed. Review the visible pipeline error.");
    }
  }

  function clearMission() {
    setRootDir("");
    setScannedRoot("");
    setScanResult(null);
    setSelectedTrajectory("");
    setSelectedDetection("");
    setSelectedMedia("");
    setPreview([]);
    setError(null);
    setScanState("idle");
    setScanProgress(null);
    setMediaProgress(null);
    setCvProgress(null);
    setStatus("Mission selection cleared.");
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <p className="eyebrow">IntelSight</p>
          <h1>Mission Explorer</h1>
        </div>

        <section className="panel">
          <label className="field-label">Data source</label>
          <input
            className="field-input"
            value={rootDir}
            onChange={(event) => {
              setRootDir(event.target.value);
              setScanState("idle");
              setError(null);
            }}
            placeholder="/path/to/mission/folder"
          />
          <button className="browse-button" type="button" onClick={handleBrowseFolder} disabled={scanState === "scanning"}>
            Browse folder
          </button>
          <button className="primary" onClick={scanMissionFolder} type="button" disabled={!canScan}>
            {scanState === "scanning" ? "Scanning mission..." : scanResult ? "Rescan mission" : "Scan mission folder"}
          </button>
          {scanState === "scanning" && scanProgress && <OperationProgress progress={scanProgress} />}
          <button className="secondary" onClick={clearMission} type="button" disabled={!rootDir && !scanResult}>
            Clear selection
          </button>
        </section>

        {recentMissions.length > 0 && (
          <section className="panel recent-panel">
            <span className="field-label">Recent missions</span>
            <ul>
              {recentMissions.map((path) => (
                <li key={path}>
                  <button
                    type="button"
                    onClick={() => {
                      setRootDir(path);
                      setScanState("idle");
                      setError(null);
                      setStatus(`Loaded ${missionName(path)}. Ready to scan.`);
                    }}
                    title={path}
                  >
                    {missionName(path)}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {scanResult && (
          <section className="panel">
            <label className="field-label">Trajectory file</label>
            <select
              value={selectedTrajectory}
              onChange={(event) => {
                setSelectedTrajectory(event.target.value);
                loadPreview(event.target.value);
              }}
            >
              {scanResult.trajectory.length === 0 ? (
                <option value="">No trajectory files</option>
              ) : (
                scanResult.trajectory.map((item) => (
                  <option key={item.path} value={item.path}>
                    {item.name}
                  </option>
                ))
              )}
            </select>

            <label className="field-label">Detection file</label>
            <select
              value={selectedDetection}
              onChange={(event) => {
                setSelectedDetection(event.target.value);
                loadPreview(event.target.value);
              }}
            >
              {scanResult.detections.length === 0 ? (
                <option value="">No detection files</option>
              ) : (
                scanResult.detections.map((item) => (
                  <option key={item.path} value={item.path}>
                    {item.name}
                  </option>
                ))
              )}
            </select>
          </section>
        )}
      </aside>

      <section className="content">
        <header className="toolbar">
          <div>
            <p className="eyebrow">Operations</p>
            <h2>{missionName(rootDir)}</h2>
            <p className="mission-root" title={rootDir}>{rootDir || "No mission root selected"}</p>
          </div>
          <span className={`status-pill status-${scanState}`} aria-live="polite">
            {scanState === "scanning" && <span className="spinner" aria-hidden="true" />}
            {status}
          </span>
        </header>

        <nav className="view-tabs" aria-label="Mission views">
          {(["overview", "video", "map", "database", "charts", "lab", "settings"] as DashboardTab[]).map((tab) => (
            <button
              key={tab}
              type="button"
              className={activeTab === tab ? "active" : ""}
              onClick={() => setActiveTab(tab)}
            >
              {tab === "lab" ? "Workshop Lab" : tab}
              {tab === "database" && cvResult ? ` (${cvResult.objects.length})` : ""}
            </button>
          ))}
        </nav>

        {scanResult && scannedRoot !== rootDir.trim() && (
          <div className="stale-banner">Displayed results belong to {missionName(scannedRoot)}. Scan the current mission root to refresh them.</div>
        )}

        {error && <div className="error-banner">{error}</div>}

        {!hasFiles && !error && (
          <div className="empty-state">
            <h3>No mission data loaded yet</h3>
            <p>Choose a mission folder, then scan it to surface any geojson/csv annotation files.</p>
          </div>
        )}

        {scanResult && activeTab === "overview" && (
          <div className="grid">
            <div className="stat-card">
              <span>Trajectory files</span>
              <strong>{scanResult.trajectory.length}</strong>
            </div>
            <div className="stat-card">
              <span>Detection files</span>
              <strong>{scanResult.detections.length}</strong>
            </div>
            <div className="stat-card">
              <span>Summary files</span>
              <strong>{scanResult.summary.length}</strong>
            </div>
            <div className="stat-card">
              <span>Media files</span>
              <strong>{scanResult.media.length}</strong>
            </div>
          </div>
        )}

        {scanResult && activeTab === "video" && (
          <section className="panel media-panel">
            <div className="panel-header-row">
              <div>
                <h3>Video review</h3>
                <p>Original and overlay playback controls for mission video assets.</p>
              </div>
              <label>
                Media asset
                <select
                  value={selectedMedia}
                  onChange={(event) => setSelectedMedia(event.target.value)}
                >
                  {scanResult.media.length === 0 ? (
                    <option value="">No media files detected</option>
                  ) : (
                    scanResult.media.map((item) => (
                      <option key={item.path} value={item.path}>
                        {item.name}
                      </option>
                    ))
                  )}
                </select>
              </label>
            </div>

            <div className="cv-workbench">
              <div className="cv-layer-controls">
                <span className="field-label">Visualization layers</span>
                <label className="toggle-row">
                  <input type="checkbox" checked={cvConfig.detections} onChange={(event) => setCvConfig({ ...cvConfig, detections: event.target.checked })} />
                  <span><strong>Object detections</strong><small>Vehicle class, confidence, and bounding box</small></span>
                </label>
                <label className="toggle-row">
                  <input type="checkbox" checked={cvConfig.opticalFlow} onChange={(event) => setCvConfig({ ...cvConfig, opticalFlow: event.target.checked })} />
                  <span><strong>Optical flow on ROI</strong><small>Motion heatmap restricted to detected-object regions</small></span>
                </label>
                <label className="toggle-row">
                  <input type="checkbox" checked={cvConfig.reid} onChange={(event) => setCvConfig({ ...cvConfig, reid: event.target.checked })} />
                  <span><strong>Local feature re-ID</strong><small>ORB correspondences and persistent IDs across sampled frames</small></span>
                </label>
              </div>
              <div className="cv-parameters">
                <label>Confidence <output>{cvConfig.confidence.toFixed(2)}</output><input type="range" min="0.1" max="0.9" step="0.05" value={cvConfig.confidence} onChange={(event) => setCvConfig({ ...cvConfig, confidence: Number(event.target.value) })} /></label>
                <label>Frame stride <input type="number" min="1" max="30" value={cvConfig.frameStep} onChange={(event) => setCvConfig({ ...cvConfig, frameStep: Number(event.target.value) })} /></label>
                <label>Clip duration <select value={cvConfig.durationSeconds} onChange={(event) => setCvConfig({ ...cvConfig, durationSeconds: Number(event.target.value) })}><option value="5">5 seconds</option><option value="10">10 seconds</option><option value="20">20 seconds</option><option value="30">30 seconds</option></select></label>
                <label>Start offset <input type="number" min="0" max="600" step="5" value={cvConfig.startOffsetSeconds} onChange={(event) => setCvConfig({ ...cvConfig, startOffsetSeconds: Number(event.target.value) })} title="Seconds to skip at the start of the mission (launch footage)" /></label>
                <label>ROI padding <input type="number" min="0" max="320" step="8" value={cvConfig.roiPadding} onChange={(event) => setCvConfig({ ...cvConfig, roiPadding: Number(event.target.value) })} /></label>
                <label>Compute device <select value={cvConfig.device} onChange={(event) => setCvConfig({ ...cvConfig, device: event.target.value })}><option value="0">GPU 0</option><option value="1">GPU 1</option><option value="cpu">CPU</option></select></label>
              </div>
              <div className="cv-run-row">
                <div><strong>{cvState === "running" ? "Processing selected clip" : "Preview-first inference"}</strong><small>{cvState === "running" ? "Detection, motion, tracking, and geolocation are running." : "Runs only the configured clip window and stores recognized objects."}</small></div>
                <button className="run-cv-button" type="button" onClick={runCvVisualization} disabled={cvState === "running" || !selectedMedia}>{cvState === "running" ? "Running CV preview..." : "Run CV preview"}</button>
              </div>
              {cvState === "running" && cvProgress && <OperationProgress progress={cvProgress} />}
              {cvState === "ready" && cvResult && (
                <div className="cv-result-actions">
                  <span>{cvResult.observation_count.toLocaleString()} observations written</span>
                  <button type="button" onClick={() => setActiveTab("map")}>View on map</button>
                  <button type="button" onClick={() => setActiveTab("database")}>View object database</button>
                </div>
              )}
              {cvError && <div className="cv-error">{cvError}</div>}
            </div>

            <div className="media-stage">
              <div className="media-screen original">
                <span>Original</span>
                <strong>{selectedMedia ? selectedMedia.split(/[\\/]/).pop() : "No media selected"}</strong>
                {mediaState === "preparing" && mediaProgress && <OperationProgress progress={mediaProgress} />}
                {mediaError && <p className="media-error">{mediaError}</p>}
                {playableMedia && (isMediaVideo(playableMedia) ? (
                  <VideoPlayer path={playableMedia} label="source preview" />
                ) : isMediaImage(selectedMedia) ? (
                  <img src={convertFileSrc(playableMedia)} alt="Mission media preview" />
                ) : (
                  <p>Selected media type is not previewable.</p>
                ))}
              </div>
              <div className="media-screen overlay">
                <span>Configured CV overlay</span>
                <strong>{cvResult ? cvResult.overlay_path.split(/[\\/]/).pop() : "No visualization run yet"}</strong>
                {cvState === "running" && <p>Generating the selected visualization layers...</p>}
                {cvResult ? <VideoPlayer key={`overlay-${cvRunCount}`} path={cvResult.overlay_path} label="CV overlay" /> : <p>Configure the pipeline above, then run a bounded preview.</p>}
              </div>
            </div>

            {cvResult && cvResult.video_fps && cvResult.detections_path && selectedMedia && (
              <div className="interactive-viewer-section">
                <div className="panel-header-row">
                  <div><h3>Interactive frame inspector</h3><p>Scrub through the processed window and overlay per-frame detections. Pick a frame to continue the next run from.</p></div>
                </div>
                <InteractiveCvViewer
                  key={`inspector-${cvRunCount}`}
                  videoPath={selectedMedia}
                  detectionsPath={cvResult.detections_path}
                  startOffsetSeconds={cvResult.configuration?.start_offset_seconds ?? 0}
                  durationSeconds={cvResult.configuration?.duration_seconds ?? 10}
                  videoFps={cvResult.video_fps}
                  videoWidth={cvResult.video_width ?? 3840}
                  videoHeight={cvResult.video_height ?? 2160}
                  onUseFrameAsOffset={(offsetSeconds) => {
                    setCvConfig((previous) => ({ ...previous, startOffsetSeconds: offsetSeconds }));
                    setStatus(`Start offset set to ${offsetSeconds}s. Run CV preview again to reprocess from this frame.`);
                    setActiveTab("video");
                  }}
                />
              </div>
            )}

            {cvResult && (
              <div className="run-manifest">
                <div><span>Rendered layers</span><strong>{[
                  cvResult.configuration?.detections && "boxes",
                  cvResult.configuration?.optical_flow && "ROI flow",
                  cvResult.configuration?.reid && "ORB feature matches",
                ].filter(Boolean).join(" · ") || (cvResult.configuration ? "metadata only" : "Legacy result; rerun to record configuration")}</strong></div>
                <div title={cvResult.detections_path}><span>Detections JSONL</span><strong>{cvResult.detections_path}</strong></div>
                <div title={cvResult.database_path}><span>Object database</span><strong>{cvResult.database_path}</strong></div>
              </div>
            )}

            <div className="panel-footer-grid">
              <div>
                <span>Playback rate</span>
                <strong>1.0x</strong>
              </div>
              <div>
                <span>Overlay mode</span>
                <strong>{cvResult ? `${cvResult.objects.length} tracked objects` : "Not generated"}</strong>
              </div>
              <div>
                <span>Selected asset size</span>
                <strong>{selectedMedia && scanResult.media.find((item) => item.path === selectedMedia) ? humanSize(scanResult.media.find((item) => item.path === selectedMedia)!.size_bytes) : "Unavailable"}</strong>
              </div>
            </div>
            <p className="preview-note">Source playback uses a cached 10-second H.264 proxy. CV runs create separate overlays and never modify mission media.</p>
          </section>
        )}

        {activeTab === "map" && (
          <section className="panel workspace-panel">
            <div className="panel-header-row">
              <div>
                <h3>Identity map</h3>
                <p>{telemetryPoints.length.toLocaleString()} geotagged SRT samples · zoom in to separate identity points meters apart</p>
              </div>
              <div className="map-controls-row">
                <select value={historyMode} onChange={(event) => setHistoryMode(event.target.value as "latest" | "history")} aria-label="Identity display mode">
                  <option value="latest">Latest positions</option>
                  <option value="history">Entire observation history</option>
                </select>
                <strong className="data-badge">{geolocatedObjects.length ? `${geolocatedObjects.length} distinguishable identities` : "Telemetry anchored"}</strong>
              </div>
            </div>
            {mapBounds ? (
              <div className="identity-map-layout">
                <div className="map-canvas">
                  <MapContainer center={[mapPoints[0]?.latitude ?? geolocatedObjects[0].latitude, mapPoints[0]?.longitude ?? geolocatedObjects[0].longitude]} zoom={18} maxZoom={22} scrollWheelZoom className="leaflet-map">
                    <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" maxNativeZoom={19} maxZoom={22} />
                    <FitMapBounds bounds={mapBounds} />
                    {mapPoints.length > 1 && <Polyline positions={mapPoints.map((point) => [point.latitude, point.longitude])} pathOptions={{ color: "#0284c7", weight: 4 }} />}
                    {selectedIdentityHistory.length > 1 && (
                      <Polyline positions={selectedIdentityHistory.map((item) => [item.latitude, item.longitude])} pathOptions={{ color: "#0ea5e9", weight: 3, dashArray: "6 4" }} />
                    )}
                    {(historyMode === "history" && !selectedIdentityId ? flattenedHistoryPoints : []).map((item) => (
                      <CircleMarker
                        key={`${item.trackId}-${item.frame}`}
                        center={[item.latitude, item.longitude]}
                        radius={3}
                        pathOptions={{ color: "#7c2d12", fillColor: "#f59e0b", fillOpacity: 0.55, weight: 1 }}
                      >
                        <Tooltip direction="top">Identity {item.trackId} · frame {item.frame} · {item.class_name}</Tooltip>
                      </CircleMarker>
                    ))}
                    {selectedIdentityHistory.map((item) => (
                      <CircleMarker
                        key={`sel-${item.frame}`}
                        center={[item.latitude, item.longitude]}
                        radius={4}
                        pathOptions={{ color: "#0c4a6e", fillColor: "#38bdf8", fillOpacity: 0.85, weight: 1 }}
                      >
                        <Tooltip direction="top">Identity {selectedIdentityId} · frame {item.frame}</Tooltip>
                      </CircleMarker>
                    ))}
                    {geolocatedObjects.map((item) => (
                      <CircleMarker
                        key={item.track_id}
                        center={[item.latitude, item.longitude]}
                        radius={selectedIdentityId === item.track_id ? 10 : 7}
                        pathOptions={{ color: "#fff1f2", fillColor: selectedIdentityId === item.track_id ? "#e11d48" : "#f43f5e", fillOpacity: 0.92, weight: 2 }}
                        eventHandlers={{ click: () => setSelectedIdentityId(item.track_id) }}
                      >
                        <Tooltip direction="top">Identity {item.track_id} · {item.class_name} · {item.observations} sightings{item.geo_spread_m != null ? ` · spread ${item.geo_spread_m.toFixed(2)} m` : ""}</Tooltip>
                      </CircleMarker>
                    ))}
                  </MapContainer>
                  <div className="map-legend"><span><i className="trajectory-line" /> GPS trajectory</span><span><i className="object-dot" /> Identity position (ground-ray)</span><span><i className="history-dot" /> Observation history</span></div>
                </div>
                <aside className="identity-profile" aria-live="polite">
                  <IdentityProfile
                    identity={selectedIdentity}
                    history={selectedIdentityHistory}
                    onBack={() => setSelectedIdentityId(null)}
                    emptyHint="Click a pink map point to inspect its registered ROI and matching evidence."
                  />
                </aside>
              </div>
            ) : (
              <div className="panel-empty">Select an SRT trajectory file to draw its geospatial path.</div>
            )}
          </section>
        )}

        {activeTab === "charts" && (
          <section className="panel workspace-panel">
            <div className="panel-header-row">
              <div>
                <h3>Altitude profile</h3>
                <p>Relative altitude sampled across the selected trajectory.</p>
              </div>
            </div>
            {chartBuckets.length > 0 ? (
              <div className="bar-chart" aria-label="Relative altitude chart">
                {chartBuckets.map((value, index) => {
                  const maximum = Math.max(...chartBuckets, 1);
                  return <div key={index} className="chart-bar" style={{ height: `${Math.max(3, (value / maximum) * 100)}%` }} title={`${value.toFixed(1)} m`} />;
                })}
              </div>
            ) : (
              <div className="panel-empty">Load an SRT trajectory to chart mission altitude.</div>
            )}
            <div className="chart-summary">
              <span>Samples <strong>{telemetryPoints.length.toLocaleString()}</strong></span>
              <span>Peak altitude <strong>{telemetryPoints.length ? `${Math.max(...telemetryPoints.map((point) => point.altitude)).toFixed(1)} m` : "--"}</strong></span>
              <span>Track points <strong>{mapPoints.length.toLocaleString()}</strong></span>
            </div>
          </section>
        )}

        {activeTab === "database" && (
          <section className="panel preview-panel">
            <div className="panel-header-row"><div><h3>Geolocated object database</h3><p>Recognized and tracked objects persisted from CV preview runs. Select a row to inspect its profile.</p></div>{cvResult && <strong className="data-badge">SQLite · {cvResult.objects.length} objects</strong>}</div>
            {cvResult?.objects.length ? (
              <div className="database-split">
                <div className="database-table-pane">
                  <div className="database-path" title={cvResult.database_path}>{cvResult.database_path}</div>
                  <div className="table-wrap"><table><thead><tr><th>Track</th><th>Class</th><th>Confidence</th><th>Frames</th><th>Observations</th><th>Latitude</th><th>Longitude</th><th>Altitude</th><th>Geolocation</th></tr></thead><tbody>
                    {cvResult.objects.map((item) => (
                      <tr
                        key={`${item.track_id}-${item.first_frame}`}
                        className={selectedIdentityId === item.track_id ? "selected" : ""}
                        onClick={() => setSelectedIdentityId(item.track_id)}
                        title={`Select identity ${item.track_id}`}
                      >
                        <td>#{item.track_id}</td><td>{item.class_name}</td><td>{(item.confidence * 100).toFixed(1)}%</td><td>{item.first_frame}–{item.last_frame}</td><td>{item.observations}</td><td>{item.latitude?.toFixed(6) ?? "--"}</td><td>{item.longitude?.toFixed(6) ?? "--"}</td><td>{item.relative_altitude_m?.toFixed(1) ?? "--"} m</td><td>{item.geolocation_mode.replace(/_/g, " ")}</td>
                      </tr>
                    ))}
                  </tbody></table></div>
                </div>
                <aside className="identity-profile database-profile" aria-live="polite">
                  <IdentityProfile
                    identity={selectedIdentity}
                    history={selectedIdentityHistory}
                    onBack={() => setSelectedIdentityId(null)}
                    emptyHint="Click a table row to inspect its profile photo and sighting history."
                  />
                </aside>
              </div>
            ) : <div className="panel-empty database-empty"><div><strong>No recognized objects stored for this session</strong><p>Open Video, configure the CV layers, and run a preview to populate the object database.</p><button type="button" onClick={() => setActiveTab("video")}>Open CV workbench</button></div></div>}
          </section>
        )}

        {activeTab === "lab" && (
          <section className="panel preview-panel">
            <div className="panel-header-row">
              <div><h3>IntelSight Workshop Lab</h3><p>Per-module demo visualizations generated from real mission artifacts.</p></div>
              <button type="button" onClick={loadLabArtifacts}>Refresh artifacts</button>
            </div>
            {labError && <div className="error-banner">{labError}</div>}
            {!labError && labArtifacts.length === 0 && (
              <div className="panel-empty">
                <div><strong>No lab artifacts found</strong>
                <p>Run <code>python modules/cv-pipeline/export_lab_artifacts.py</code> or open the Workshop Lab in the web dashboard to generate them under <code>output/lab-artifacts/</code>.</p></div>
              </div>
            )}
            {labArtifacts.length > 0 && (
              <div className="lab-gallery">
                {labArtifacts.map((artifact) => (
                  <figure key={artifact.path} className={artifact.name === "pipeline_dataflow.png" ? "lab-figure lab-figure-wide" : "lab-figure"}>
                    <LabImage artifact={artifact} />
                    <figcaption>
                      {artifact.name === "pipeline_dataflow.png" ? "Module integration data flow" : (LAB_MODULE_NAMES[artifact.module] ?? artifact.module)}
                      <small>{artifact.name}</small>
                    </figcaption>
                  </figure>
                ))}
              </div>
            )}
          </section>
        )}

        {activeTab === "settings" && (
          <section className="panel workspace-panel">
            <div className="panel-header-row">
              <div><h3>Settings</h3><p>Local preferences for the CV workbench, mission intake, and map display. Stored in this browser profile (localStorage), not sent anywhere.</p></div>
            </div>
            <div className="settings-grid">
              <div className="settings-group">
                <h4>CV workbench defaults</h4>
                <label>Compute device
                  <select value={settings.device} onChange={(event) => setSettings({ ...settings, device: event.target.value })}>
                    <option value="0">GPU 0</option>
                    <option value="1">GPU 1</option>
                    <option value="cpu">CPU</option>
                  </select>
                </label>
                <label>Confidence <output>{settings.confidence.toFixed(2)}</output>
                  <input type="range" min="0.1" max="0.9" step="0.05" value={settings.confidence} onChange={(event) => setSettings({ ...settings, confidence: Number(event.target.value) })} />
                </label>
                <label>Frame stride
                  <input type="number" min="1" max="30" value={settings.frameStep} onChange={(event) => setSettings({ ...settings, frameStep: Number(event.target.value) })} />
                </label>
                <label>Clip duration
                  <select value={settings.durationSeconds} onChange={(event) => setSettings({ ...settings, durationSeconds: Number(event.target.value) })}>
                    <option value="5">5 seconds</option><option value="10">10 seconds</option><option value="20">20 seconds</option><option value="30">30 seconds</option>
                  </select>
                </label>
                <label>Start offset
                  <input type="number" min="0" max="600" step="5" value={settings.startOffsetSeconds} onChange={(event) => setSettings({ ...settings, startOffsetSeconds: Number(event.target.value) })} title="Seconds to skip at the start of the mission (launch footage)" />
                </label>
                <label>ROI padding
                  <input type="number" min="0" max="320" step="8" value={settings.roiPadding} onChange={(event) => setSettings({ ...settings, roiPadding: Number(event.target.value) })} />
                </label>
              </div>
              <div className="settings-group">
                <h4>Mission and map</h4>
                <label className="settings-checkbox">
                  <input type="checkbox" checked={settings.rememberMissionRoot} onChange={(event) => setSettings({ ...settings, rememberMissionRoot: event.target.checked })} />
                  Remember last mission root on startup
                </label>
                <div className="settings-path" title={settings.lastMissionRoot || undefined}>{settings.lastMissionRoot || "No mission root remembered yet"}</div>
                <label>Default map display
                  <select value={settings.defaultHistoryMode} onChange={(event) => setSettings({ ...settings, defaultHistoryMode: event.target.value as "latest" | "history" })}>
                    <option value="latest">Latest positions</option>
                    <option value="history">Entire observation history</option>
                  </select>
                </label>
                <button type="button" onClick={clearRecentMissions}>Clear recent missions</button>
              </div>
            </div>
            <div className="settings-actions">
              <button type="button" className="primary" onClick={saveSettings}>Save settings</button>
              <button type="button" onClick={resetSettings}>Reset to defaults</button>
              <span className="settings-note">Changes apply to new workbench runs; the current session keeps its loaded mission.</span>
            </div>
          </section>
        )}

        {scanResult && activeTab === "overview" && (
          <div className="file-lists">
            <div className="panel">
              <h3>Trajectory candidates</h3>
              <ul>
                {scanResult.trajectory.length === 0 ? (
                  <li>No trajectory files detected</li>
                ) : (
                  scanResult.trajectory.map((item) => (
                    <li key={item.path}>
                      <span>{item.name}</span>
                      <small>{humanSize(item.size_bytes)}</small>
                    </li>
                  ))
                )}
              </ul>
            </div>
            <div className="panel">
              <h3>Detection candidates</h3>
              <ul>
                {scanResult.detections.length === 0 ? (
                  <li>No detection files detected</li>
                ) : (
                  scanResult.detections.map((item) => (
                    <li key={item.path}>
                      <span>{item.name}</span>
                      <small>{humanSize(item.size_bytes)}</small>
                    </li>
                  ))
                )}
              </ul>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}

export default App;
