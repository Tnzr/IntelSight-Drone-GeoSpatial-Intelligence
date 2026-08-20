use std::fs;
use std::hash::{DefaultHasher, Hash, Hasher};
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Command, Stdio};

use serde::{Deserialize, Serialize};
use tauri::ipc::Channel;
use tauri::Manager;
use walkdir::WalkDir;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileCandidate {
    path: String,
    kind: String,
    name: String,
    size_bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MissionScanResult {
    trajectory: Vec<FileCandidate>,
    detections: Vec<FileCandidate>,
    summary: Vec<FileCandidate>,
    media: Vec<FileCandidate>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LabArtifact {
    name: String,
    path: String,
    module: String,
}

fn is_repo_root(dir: &Path) -> bool {
    dir.join("modules").join("cv-pipeline").is_dir() && dir.join("environment.yml").is_file()
}

fn resolve_repo_root() -> Result<std::path::PathBuf, String> {
    if let Ok(root) = std::env::var("INTELSIGHT_REPO_ROOT") {
        let path = std::path::PathBuf::from(&root);
        if path.is_dir() {
            return Ok(path);
        }
    }

    let mut current =
        std::env::current_dir().map_err(|err| format!("Could not resolve current directory: {err}"))?;
    loop {
        if is_repo_root(&current) {
            return Ok(current);
        }
        if !current.pop() {
            break;
        }
    }

    let fallback = std::path::PathBuf::from(
        "/media/tnzr/HDD11/PCC/PioneerInnovationsCollective/Ventures/PioneerInnovationsCollective_ventures/IntelSight-Drone-GeoSpatial-Intelligence",
    );
    if is_repo_root(&fallback) {
        return Ok(fallback);
    }

    Err(
        "Could not locate the IntelSight repository root. Set INTELSIGHT_REPO_ROOT or start the app with `make desktop`."
            .to_string(),
    )
}

#[tauri::command]
fn list_lab_artifacts() -> Result<Vec<LabArtifact>, String> {
    let repo_root = resolve_repo_root()?;
    let lab_dir = repo_root.join("output").join("lab-artifacts");
    if !lab_dir.is_dir() {
        return Ok(Vec::new());
    }
    let manifest_path = lab_dir.join("manifest.json");
    let mut artifacts: Vec<LabArtifact> = Vec::new();
    if manifest_path.is_file() {
        if let Ok(content) = fs::read_to_string(&manifest_path) {
            if let Ok(entries) = serde_json::from_str::<Vec<serde_json::Value>>(&content) {
                for entry in entries {
                    let name = entry
                        .get("name")
                        .and_then(|value| value.as_str())
                        .unwrap_or_default()
                        .to_string();
                    let relative = entry
                        .get("path")
                        .and_then(|value| value.as_str())
                        .unwrap_or_default();
                    let full = repo_root.join(relative);
                    if full.is_file() {
                        artifacts.push(LabArtifact {
                            name: name.clone(),
                            path: full.to_string_lossy().to_string(),
                            module: entry
                                .get("module")
                                .and_then(|value| value.as_str())
                                .unwrap_or("workshop")
                                .to_string(),
                        });
                    }
                }
            }
        }
    }
    if artifacts.is_empty() {
        if let Ok(read_dir) = fs::read_dir(&lab_dir) {
            for entry in read_dir.filter_map(Result::ok) {
                let path = entry.path();
                if path.extension().and_then(|ext| ext.to_str()).unwrap_or("") == "png" {
                    artifacts.push(LabArtifact {
                        name: path
                            .file_name()
                            .unwrap_or_default()
                            .to_string_lossy()
                            .to_string(),
                        path: path.to_string_lossy().to_string(),
                        module: "workshop".to_string(),
                    });
                }
            }
        }
    }
    artifacts.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(artifacts)
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CvPreviewOptions {
    video_path: String,
    telemetry_path: Option<String>,
    duration_seconds: f64,
    start_offset_seconds: f64,
    full_video: bool,
    frame_step: u32,
    confidence: f64,
    roi_padding: u32,
    detections: bool,
    optical_flow: bool,
    reid: bool,
    device: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProgressUpdate {
    phase: String,
    current: u64,
    total: u64,
    message: String,
}

fn report_progress(
    channel: &Channel<ProgressUpdate>,
    phase: &str,
    current: u64,
    total: u64,
    message: impl Into<String>,
) {
    let _ = channel.send(ProgressUpdate {
        phase: phase.to_string(),
        current,
        total,
        message: message.into(),
    });
}

fn classify_path(path: &Path) -> Option<&'static str> {
    let name = path.file_name()?.to_string_lossy().to_ascii_lowercase();
    if (name.contains("trajectory") || name.contains("srt") || name.contains("flight") || name.contains("geojson"))
        && (name.contains("trajectory") || name.contains("flight") || name.contains("geojson") || name.contains("srt"))
    {
        return Some("trajectory");
    }
    if name.contains("summary") || name.contains("report") {
        return Some("summary");
    }
    if name.contains("detection") || name.contains("fused") || name.contains("plate") || name.contains("vehicle") || name.contains("lp_") {
        return Some("detections");
    }
    if matches!(
        path.extension().and_then(|ext| ext.to_str()).unwrap_or("").to_ascii_lowercase().as_str(),
        "mp4" | "mov" | "m4v" | "avi" | "jpg" | "jpeg" | "png" | "webp"
    ) {
        return Some("media");
    }
    if name.ends_with(".geojson") || name.ends_with(".json") || name.ends_with(".csv") {
        return Some("detections");
    }
    None
}

#[tauri::command]
fn scan_directory(dir: &str, on_progress: Channel<ProgressUpdate>) -> Result<MissionScanResult, String> {
    scan_directory_impl(dir, Some(&on_progress))
}

fn scan_directory_impl(
    dir: &str,
    on_progress: Option<&Channel<ProgressUpdate>>,
) -> Result<MissionScanResult, String> {
    let root = Path::new(dir);
    if !root.exists() {
        return Err(format!("Directory does not exist: {dir}"));
    }
    if !root.is_dir() {
        return Err(format!("Mission root is not a directory: {dir}"));
    }

    let mut result = MissionScanResult {
        trajectory: Vec::new(),
        detections: Vec::new(),
        summary: Vec::new(),
        media: Vec::new(),
    };

    let files: Vec<_> = WalkDir::new(root)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| entry.file_type().is_file())
        .collect();
    let total = files.len() as u64;
    if let Some(channel) = on_progress {
        report_progress(channel, "discovering", 0, total, "Inspecting mission files");
    }

    for (index, entry) in files.into_iter().enumerate() {
        let path = entry.path();
        if let Some(channel) = on_progress {
            report_progress(
                channel,
                "classifying",
                index as u64 + 1,
                total,
                format!("Inspecting {}", path.file_name().unwrap_or_default().to_string_lossy()),
            );
        }
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        let kind = match ext.to_ascii_lowercase().as_str() {
            "geojson" | "json" | "csv" | "srt" | "txt" | "mp4" | "mov" | "m4v"
            | "avi" | "jpg" | "jpeg" | "png" | "webp" => {
                classify_path(path).unwrap_or("detections")
            }
            _ => continue,
        };

        let candidate = FileCandidate {
            path: path.to_string_lossy().to_string(),
            kind: kind.to_string(),
            name: path.file_name().unwrap_or_default().to_string_lossy().to_string(),
            size_bytes: fs::metadata(path).map(|meta| meta.len()).unwrap_or(0),
        };

        match kind {
            "trajectory" => result.trajectory.push(candidate),
            "summary" => result.summary.push(candidate),
                "media" => result.media.push(candidate),
            _ => result.detections.push(candidate),
        }

    }

    for list in [
        &mut result.trajectory,
        &mut result.detections,
        &mut result.summary,
        &mut result.media,
    ] {
        list.sort_by(|a, b| a.path.cmp(&b.path));
    }

    if let Some(channel) = on_progress {
        report_progress(channel, "complete", total, total, "Mission scan complete");
    }

    Ok(result)
}

fn parse_json_file(path: &Path) -> Result<Vec<serde_json::Value>, String> {
    let content = fs::read_to_string(path).map_err(|err| err.to_string())?;
    let parsed: serde_json::Value = serde_json::from_str(&content)
        .map_err(|err| format!("JSON parse failed for {path:?}: {err}"))?;

    match parsed {
        serde_json::Value::Array(items) => Ok(items),
        serde_json::Value::Object(obj) => Ok(vec![serde_json::Value::Object(obj)]),
        _ => Ok(vec![parsed]),
    }
}

fn parse_csv_file(path: &Path) -> Result<Vec<serde_json::Value>, String> {
    let mut rdr = csv::Reader::from_path(path).map_err(|err| err.to_string())?;
    let headers = rdr.headers().map_err(|err| err.to_string())?.clone();
    let mut records = Vec::new();

    for result in rdr.records() {
        let record = result.map_err(|err| err.to_string())?;
        let mut object = serde_json::Map::new();
        for (index, header) in headers.iter().enumerate() {
            let value = record.get(index).unwrap_or("");
            let json_value = if value.trim().is_empty() {
                serde_json::Value::Null
            } else {
                serde_json::Value::String(value.to_string())
            };
            object.insert(header.to_string(), json_value);
        }
        records.push(serde_json::Value::Object(object));
    }

    Ok(records)
}

fn bracket_value<'a>(line: &'a str, key: &str) -> Option<&'a str> {
    let start = line.find(key)? + key.len();
    let rest = line[start..].trim_start();
    let end = rest.find(|character: char| character == ']' || character.is_whitespace())?;
    Some(&rest[..end])
}

fn parse_srt_file(path: &Path) -> Result<Vec<serde_json::Value>, String> {
    let content = fs::read_to_string(path).map_err(|err| err.to_string())?;
    let mut records = Vec::new();

    for block in content.split("\n\n") {
        let lines: Vec<&str> = block.lines().collect();
        let telemetry = lines.iter().find(|line| line.contains("[latitude:"));
        let Some(telemetry) = telemetry else {
            continue;
        };

        let frame = lines
            .iter()
            .find_map(|line| line.trim().parse::<u64>().ok())
            .unwrap_or(records.len() as u64 + 1);
        let timestamp = lines
            .iter()
            .find(|line| line.contains(" --> "))
            .and_then(|line| line.split(" --> ").next())
            .unwrap_or("");
        let captured_at = lines
            .iter()
            .find(|line| line.len() >= 19 && line.chars().nth(4) == Some('-'))
            .map(|line| line.trim())
            .unwrap_or("");

        records.push(serde_json::json!({
            "frame": frame,
            "timestamp": timestamp,
            "captured_at": captured_at,
            "latitude": bracket_value(telemetry, "[latitude:").and_then(|value| value.parse::<f64>().ok()),
            "longitude": bracket_value(telemetry, "[longitude:").and_then(|value| value.parse::<f64>().ok()),
            "relative_altitude_m": bracket_value(telemetry, "[rel_alt:").and_then(|value| value.parse::<f64>().ok()),
            "absolute_altitude_m": bracket_value(telemetry, "abs_alt:").and_then(|value| value.parse::<f64>().ok()),
            "iso": bracket_value(telemetry, "[iso:").and_then(|value| value.parse::<u64>().ok()),
        }));
    }

    Ok(records)
}

fn describe_flight_record(path: &Path) -> Result<Vec<serde_json::Value>, String> {
    let metadata = fs::metadata(path).map_err(|err| err.to_string())?;
    Ok(vec![serde_json::json!({
        "file": path.file_name().unwrap_or_default().to_string_lossy(),
        "format": "DJI encoded flight record",
        "size_bytes": metadata.len(),
        "preview": "Binary flight log retained as source provenance; use SRT telemetry for mapped positions."
    })])
}

#[tauri::command]
fn read_annotation_file(path: &str) -> Result<Vec<serde_json::Value>, String> {
    let candidate = Path::new(path);
    if !candidate.exists() {
        return Err(format!("File not found: {path}"));
    }

    let ext = candidate
        .extension()
        .and_then(|ext| ext.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();

    match ext.as_str() {
        "json" | "geojson" => parse_json_file(candidate),
        "csv" => parse_csv_file(candidate),
        "srt" => parse_srt_file(candidate),
        "txt" => describe_flight_record(candidate),
        _ => Err(format!("Unsupported annotation format: {ext}")),
    }
}

#[tauri::command]
fn read_media_file(path: &str) -> Result<tauri::ipc::Response, String> {
    let candidate = Path::new(path);
    if !candidate.is_file() {
        return Err(format!("Media file not found: {path}"));
    }
    let extension = candidate
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    if !matches!(extension.as_str(), "mp4" | "jpg" | "jpeg" | "png" | "webp") {
        return Err(format!("Unsupported preview media format: {extension}"));
    }
    let bytes = fs::read(candidate).map_err(|err| format!("Could not read preview media: {err}"))?;
    Ok(tauri::ipc::Response::new(bytes))
}

#[tauri::command]
fn read_detections_jsonl(path: &str) -> Result<Vec<serde_json::Value>, String> {
    let candidate = Path::new(path);
    if !candidate.is_file() {
        return Err(format!("Detections file not found: {path}"));
    }
    let content = fs::read_to_string(candidate).map_err(|err| err.to_string())?;
    let mut records = Vec::new();
    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        match serde_json::from_str::<serde_json::Value>(line) {
            Ok(value) => records.push(value),
            Err(err) => return Err(format!("Invalid JSONL line: {err}")),
        }
    }
    Ok(records)
}

#[tauri::command]
async fn prepare_media_preview(
    app: tauri::AppHandle,
    path: String,
    start_seconds: Option<f64>,
    duration_seconds: Option<f64>,
    on_progress: Channel<ProgressUpdate>,
) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let source = Path::new(&path);
        if !source.is_file() {
            return Err(format!("Media file not found: {path}"));
        }

        let start_seconds = start_seconds.unwrap_or(0.0).max(0.0);
        let duration_seconds = duration_seconds.unwrap_or(10.0).clamp(2.0, 120.0);

        let metadata = fs::metadata(source).map_err(|err| err.to_string())?;
        let mut hasher = DefaultHasher::new();
        path.hash(&mut hasher);
        metadata.len().hash(&mut hasher);
        metadata.modified().ok().hash(&mut hasher);
        start_seconds.to_bits().hash(&mut hasher);
        duration_seconds.to_bits().hash(&mut hasher);

        let cache_dir = app
            .path()
            .app_cache_dir()
            .map_err(|err| format!("Could not resolve preview cache: {err}"))?
            .join("media-previews");
        fs::create_dir_all(&cache_dir).map_err(|err| err.to_string())?;
        let output = cache_dir.join(format!("{:016x}.mp4", hasher.finish()));

        if output.is_file() && fs::metadata(&output).map(|item| item.len() > 0).unwrap_or(false) {
            report_progress(&on_progress, "complete", 10_000, 10_000, "Using cached video preview");
            return Ok(output.to_string_lossy().to_string());
        }

        report_progress(&on_progress, "transcoding", 0, 10_000, "Starting H.264 preview conversion");
        let duration_label = format!("{:.1}", duration_seconds);
        let mut ffmpeg = Command::new("ffmpeg");
        ffmpeg
            .args(["-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats", "-y"])
            .args(["-ss", &start_seconds.to_string()])
            .args(["-i", &path])
            .args(["-t", &duration_label])
            .args([
                "-map",
                "0:v:0",
                "-vf",
                "scale=-2:1080,fps=30",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
            ])
            .arg(&output)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let mut ffmpeg = ffmpeg
            .spawn()
            .map_err(|err| format!("Could not start ffmpeg: {err}"))?;

        let total_ms = (duration_seconds * 1_000.0) as u64;
        if let Some(stdout) = ffmpeg.stdout.take() {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if let Some(value) = line.strip_prefix("out_time_ms=") {
                    if let Ok(microseconds) = value.parse::<u64>() {
                        let milliseconds = (microseconds / 1_000).min(total_ms);
                        report_progress(
                            &on_progress,
                            "transcoding",
                            milliseconds,
                            total_ms,
                            format!(
                                "Encoded {:.1} of {} seconds",
                                milliseconds as f64 / 1_000.0,
                                duration_label
                            ),
                        );
                    }
                }
            }
        }
        let ffmpeg = ffmpeg
            .wait_with_output()
            .map_err(|err| format!("Video preview conversion failed: {err}"))?;

        if !ffmpeg.status.success() {
            let _ = fs::remove_file(&output);
            return Err(format!(
                "Video preview conversion failed: {}",
                String::from_utf8_lossy(&ffmpeg.stderr).trim()
            ));
        }

        report_progress(&on_progress, "complete", total_ms, total_ms, "Video preview ready");
        Ok(output.to_string_lossy().to_string())
    })
    .await
    .map_err(|err| format!("Video preview task failed: {err}"))?
}

#[tauri::command]
async fn run_cv_preview(
    app: tauri::AppHandle,
    options: CvPreviewOptions,
    on_progress: Channel<ProgressUpdate>,
) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let repo_root = resolve_repo_root()?;
        let script = repo_root.join("modules/cv-pipeline/run_visualization_preview.py");
        let model = repo_root.join("models").join("yolov8n.pt");
        let python = Path::new("/home/tnzr/.local/share/mamba/envs/intelsight/bin/python");
        if !python.is_file() {
            return Err(format!("IntelSight Python environment not found: {}", python.display()));
        }
        if !script.is_file() || !model.is_file() {
            return Err("CV preview script or YOLO model is missing from the repository.".to_string());
        }

        let run_root = app
            .path()
            .app_data_dir()
            .map_err(|err| format!("Could not resolve CV output directory: {err}"))?
            .join("cv-runs");
        fs::create_dir_all(&run_root).map_err(|err| err.to_string())?;

        let video = Path::new(&options.video_path);
        let run_name = video.file_stem().unwrap_or_default().to_string_lossy();
        let output_dir = run_root.join(run_name.as_ref());
        fs::create_dir_all(&output_dir).map_err(|err| err.to_string())?;

        let mut command = Command::new(python);
        command
            .arg(&script)
            .args(["--video", &options.video_path])
            .args(["--output-dir", output_dir.to_string_lossy().as_ref()])
            .args(["--model", model.to_string_lossy().as_ref()])
            .args(["--duration", &options.duration_seconds.clamp(2.0, 3600.0).to_string()])
            .args(["--start-offset", &options.start_offset_seconds.clamp(0.0, 600.0).to_string()])
            .args(["--frame-step", &options.frame_step.clamp(1, 30).to_string()])
            .args(["--confidence", &options.confidence.clamp(0.05, 0.95).to_string()])
            .args(["--roi-padding", &options.roi_padding.clamp(0, 320).to_string()])
            .args(["--device", &options.device]);
        if let Some(telemetry_path) = options.telemetry_path.filter(|path| !path.is_empty()) {
            command.args(["--srt", &telemetry_path]);
        }
        command.arg(if options.detections { "--detections" } else { "--no-detections" });
        command.arg(if options.optical_flow { "--optical-flow" } else { "--no-optical-flow" });
        command.arg(if options.reid { "--reid" } else { "--no-reid" });
        if options.full_video {
            command.arg("--full-video");
        }

        report_progress(&on_progress, "initializing", 0, 100, "Loading model and video");
        let mut child = command
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|err| format!("Could not start CV preview: {err}"))?;
        let mut payload_line = None;
        if let Some(stdout) = child.stdout.take() {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) {
                    if let Some(progress) = value.get("progress") {
                        let current = progress.get("current").and_then(|item| item.as_u64()).unwrap_or(0);
                        let total = progress.get("total").and_then(|item| item.as_u64()).unwrap_or(100);
                        let phase = progress.get("phase").and_then(|item| item.as_str()).unwrap_or("processing");
                        let message = progress.get("message").and_then(|item| item.as_str()).unwrap_or("Processing preview");
                        report_progress(&on_progress, phase, current, total, message);
                    } else if value.is_object() {
                        payload_line = Some(line);
                    }
                }
            }
        }
        let output = child
            .wait_with_output()
            .map_err(|err| format!("CV preview process failed: {err}"))?;
        if !output.status.success() {
            return Err(format!(
                "CV preview failed: {}",
                String::from_utf8_lossy(&output.stderr).trim()
            ));
        }
        let payload_line = payload_line.ok_or_else(|| "CV preview returned no result".to_string())?;
        report_progress(&on_progress, "complete", 100, 100, "CV preview ready");
        serde_json::from_str(&payload_line).map_err(|err| format!("Invalid CV preview result: {err}"))
    })
    .await
    .map_err(|err| format!("CV preview task failed: {err}"))?
}

#[tauri::command]
fn load_cv_result(app: tauri::AppHandle, video_path: &str) -> Result<Option<serde_json::Value>, String> {
    let video = Path::new(video_path);
    let run_name = video.file_stem().unwrap_or_default().to_string_lossy();
    let result_path = app
        .path()
        .app_data_dir()
        .map_err(|err| format!("Could not resolve CV output directory: {err}"))?
        .join("cv-runs")
        .join(run_name.as_ref())
        .join(format!("{}.objects.json", run_name));
    if !result_path.is_file() {
        return Ok(None);
    }
    let content = fs::read_to_string(&result_path).map_err(|err| err.to_string())?;
    serde_json::from_str(&content)
        .map(Some)
        .map_err(|err| format!("Could not read saved CV result: {err}"))
}

#[cfg(test)]
mod tests {
    use super::{parse_srt_file, scan_directory_impl};
    use std::fs;

    #[test]
    fn scan_directory_includes_media_and_sorts_by_path() {
        let root = std::env::temp_dir().join(format!(
            "intelsight-scan-{}",
            std::process::id()
        ));
        let first_dir = root.join("a");
        let second_dir = root.join("b");
        fs::create_dir_all(&first_dir).expect("create first test directory");
        fs::create_dir_all(&second_dir).expect("create second test directory");
        fs::write(first_dir.join("frame.jpg"), []).expect("write first media file");
        fs::write(second_dir.join("frame.jpg"), []).expect("write second media file");
        fs::write(root.join("DJI_001.SRT"), "1\n00:00:00,000 --> 00:00:01,000\n")
            .expect("write SRT telemetry file");
        fs::write(root.join("FlightRecord_test.txt"), "flight data")
            .expect("write flight record");
        fs::write(root.join("detections.csv"), "id\n1\n").expect("write detection file");

        let result = scan_directory_impl(root.to_str().expect("utf-8 test path"), None)
            .expect("scan test mission");

        assert_eq!(result.media.len(), 2);
        assert_eq!(result.trajectory.len(), 2);
        assert_eq!(result.detections.len(), 1);
        assert!(result.media[0].path < result.media[1].path);

        fs::remove_dir_all(root).expect("remove test mission");
    }

    #[test]
    fn parses_dji_srt_positions() {
        let path = std::env::temp_dir().join(format!("intelsight-srt-{}.srt", std::process::id()));
        fs::write(
            &path,
            "1\n00:00:00,000 --> 00:00:00,016\n2026-08-14 18:38:56.311\n[iso: 140] [latitude: 25.769324] [longitude: -80.358293] [rel_alt: 1.300 abs_alt: -53.809]\n\n",
        )
        .expect("write SRT fixture");

        let records = parse_srt_file(&path).expect("parse SRT fixture");
        assert_eq!(records.len(), 1);
        assert_eq!(records[0]["latitude"], 25.769324);
        assert_eq!(records[0]["longitude"], -80.358293);
        assert_eq!(records[0]["relative_altitude_m"], 1.3);

        fs::remove_file(path).expect("remove SRT fixture");
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            scan_directory,
            read_annotation_file,
            read_media_file,
            read_detections_jsonl,
            prepare_media_preview,
            run_cv_preview,
            load_cv_result,
            list_lab_artifacts
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
