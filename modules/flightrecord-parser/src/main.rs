use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{Context, Result};
use clap::Parser;
use dji_log_parser::keychain::KeychainFeaturePoint;
use dji_log_parser::DJILog;
use geojson::{Feature, FeatureCollection, GeoJson, Geometry, Value};
use serde::Serialize;
use serde_json::json;

#[derive(Parser, Debug)]
#[command(author, version, about)]
struct Cli {
    /// Input DJI flight record .txt file
    #[arg(short, long)]
    input: PathBuf,

    /// Output directory for csv/geojson/metrics
    #[arg(short = 'o', long)]
    out_dir: PathBuf,

    /// Optional DJI api key for encrypted logs (v13+)
    #[arg(long)]
    api_key: Option<String>,

    /// Optional path to previously fetched keychains JSON
    #[arg(long)]
    keychains_file: Option<PathBuf>,
}

#[derive(Serialize)]
struct PerfMetrics {
    input_file: String,
    log_version: u8,
    status: String,
    frame_count: usize,
    parse_ms: u128,
    frames_ms: u128,
    csv_ms: u128,
    geojson_ms: u128,
    total_ms: u128,
    frames_per_second: f64,
}

fn main() -> Result<()> {
    let total_start = Instant::now();
    let args = Cli::parse();
    fs::create_dir_all(&args.out_dir).context("creating output directory")?;

    let parse_start = Instant::now();
    let bytes = fs::read(&args.input).context("reading input log")?;
    let parser = DJILog::from_bytes(bytes).context("parsing DJI log bytes")?;
    let parse_ms = parse_start.elapsed().as_millis();

    let stem = args
        .input
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("flightrecord");
    let csv_path = args.out_dir.join(format!("{stem}.frames.csv"));
    let geojson_path = args.out_dir.join(format!("{stem}.trajectory.geojson"));
    let metrics_path = args.out_dir.join(format!("{stem}.metrics.json"));

    let keychains = if parser.version >= 13 {
        if let Some(keychains_file) = &args.keychains_file {
            let raw = fs::read_to_string(keychains_file).with_context(|| {
                format!("reading keychains file: {}", keychains_file.display())
            })?;
            let keychains: Vec<Vec<KeychainFeaturePoint>> =
                serde_json::from_str(&raw).context("parsing keychains json")?;
            Some(keychains)
        } else if let Some(api_key) = &args.api_key {
            let req = parser
                .keychains_request_with_custom_params(None, None)
                .context("building keychain request")?;

            let keychains = req.fetch(api_key, None).context("fetching keychains")?;
            let cache_path = args.out_dir.join(format!("{stem}.keychains-cache.json"));
            fs::write(&cache_path, serde_json::to_string_pretty(&keychains)?)
                .context("writing keychains cache")?;
            Some(keychains)
        } else {
            let req = parser
                .keychains_request_with_custom_params(None, None)
                .context("building keychain request")?;

            let req_path = args.out_dir.join(format!("{stem}.keychains-request.json"));
            let details_path = args.out_dir.join(format!("{stem}.details.json"));

            fs::write(&req_path, serde_json::to_string_pretty(&req)?)
                .context("writing keychain request json")?;
            fs::write(&details_path, serde_json::to_string_pretty(&parser.details)?)
                .context("writing details json")?;

            let total_ms = total_start.elapsed().as_millis();
            let metrics = PerfMetrics {
                input_file: args.input.to_string_lossy().to_string(),
                log_version: parser.version,
                status: "requires_api_key_or_keychain_cache".to_string(),
                frame_count: 0,
                parse_ms,
                frames_ms: 0,
                csv_ms: 0,
                geojson_ms: 0,
                total_ms,
                frames_per_second: 0.0,
            };

            fs::write(&metrics_path, serde_json::to_string_pretty(&metrics)?)
                .context("writing metrics json")?;

            println!("input      : {}", args.input.display());
            println!("version    : {}", parser.version);
            println!("status     : requires API key for frame decode");
            println!("details    : {}", details_path.display());
            println!("keychains  : {}", req_path.display());
            println!("metrics    : {}", metrics_path.display());
            println!(
                "hint       : rerun with --api-key or --keychains-file <cached-json>"
            );
            return Ok(());
        }
    } else {
        None
    };

    let frames_start = Instant::now();
    let frames = parser
        .frames(keychains)
        .context("decoding frames from DJI log")?;
    let frames_ms = frames_start.elapsed().as_millis();

    let csv_start = Instant::now();
    write_csv(&csv_path, &frames)?;
    let csv_ms = csv_start.elapsed().as_millis();

    let geojson_start = Instant::now();
    write_geojson(&geojson_path, &frames, &parser.details.aircraft_name)?;
    let geojson_ms = geojson_start.elapsed().as_millis();

    let total_ms = total_start.elapsed().as_millis();
    let fps = if total_ms == 0 {
        0.0
    } else {
        (frames.len() as f64) / ((total_ms as f64) / 1000.0)
    };

    let metrics = PerfMetrics {
        input_file: args.input.to_string_lossy().to_string(),
        log_version: parser.version,
        status: "decoded".to_string(),
        frame_count: frames.len(),
        parse_ms,
        frames_ms,
        csv_ms,
        geojson_ms,
        total_ms,
        frames_per_second: fps,
    };

    fs::write(&metrics_path, serde_json::to_string_pretty(&metrics)?)
        .context("writing metrics json")?;

    println!("input      : {}", args.input.display());
    println!("version    : {}", parser.version);
    println!("status     : decoded");
    println!("frames     : {}", frames.len());
    println!("csv        : {}", csv_path.display());
    println!("geojson    : {}", geojson_path.display());
    println!("metrics    : {}", metrics_path.display());
    println!("total(ms)  : {}", total_ms);
    println!("throughput : {:.2} frames/s", fps);

    Ok(())
}

fn write_csv(path: &Path, frames: &[dji_log_parser::frame::Frame]) -> Result<()> {
    let mut writer = csv::Writer::from_path(path).context("opening csv writer")?;

    writer.write_record([
        "customDateTime",
        "flyTime",
        "latitude",
        "longitude",
        "height",
        "altitude",
        "xSpeed",
        "ySpeed",
        "zSpeed",
        "pitch",
        "roll",
        "yaw",
        "gpsNum",
        "gpsLevel",
        "isGPSUsed",
    ])?;

    for frame in frames {
        writer.write_record([
            frame.custom.date_time.to_string(),
            frame.osd.fly_time.to_string(),
            frame.osd.latitude.to_string(),
            frame.osd.longitude.to_string(),
            frame.osd.height.to_string(),
            frame.osd.altitude.to_string(),
            frame.osd.x_speed.to_string(),
            frame.osd.y_speed.to_string(),
            frame.osd.z_speed.to_string(),
            frame.osd.pitch.to_string(),
            frame.osd.roll.to_string(),
            frame.osd.yaw.to_string(),
            frame.osd.gps_num.to_string(),
            frame.osd.gps_level.to_string(),
            frame.osd.is_gpd_used.to_string(),
        ])?;
    }

    writer.flush()?;
    Ok(())
}

fn write_geojson(
    path: &Path,
    frames: &[dji_log_parser::frame::Frame],
    aircraft_name: &str,
) -> Result<()> {
    let mut coords: Vec<Vec<f64>> = Vec::new();
    let mut sample_features: Vec<Feature> = Vec::new();

    let sample_interval = usize::max(frames.len() / 50, 1);

    for (idx, frame) in frames.iter().enumerate() {
        coords.push(vec![
            frame.osd.longitude,
            frame.osd.latitude,
            frame.osd.altitude as f64,
        ]);

        if idx % sample_interval == 0 {
            let mut props: BTreeMap<String, serde_json::Value> = BTreeMap::new();
            props.insert("index".to_owned(), json!(idx));
            props.insert("flyTime".to_owned(), json!(frame.osd.fly_time));
            props.insert("height".to_owned(), json!(frame.osd.height));
            props.insert("altitude".to_owned(), json!(frame.osd.altitude));
            props.insert("xSpeed".to_owned(), json!(frame.osd.x_speed));
            props.insert("ySpeed".to_owned(), json!(frame.osd.y_speed));
            props.insert("zSpeed".to_owned(), json!(frame.osd.z_speed));
            props.insert("yaw".to_owned(), json!(frame.osd.yaw));
            props.insert("pitch".to_owned(), json!(frame.osd.pitch));
            props.insert("roll".to_owned(), json!(frame.osd.roll));
            props.insert("gpsNum".to_owned(), json!(frame.osd.gps_num));

            sample_features.push(Feature {
                bbox: None,
                geometry: Some(Geometry::new(Value::Point(vec![
                    frame.osd.longitude,
                    frame.osd.latitude,
                    frame.osd.altitude as f64,
                ]))),
                id: None,
                properties: Some(props.into_iter().collect()),
                foreign_members: None,
            });
        }
    }

    let line_feature = Feature {
        bbox: None,
        geometry: Some(Geometry::new(Value::LineString(coords))),
        id: None,
        properties: Some(
            [
                ("type".to_owned(), json!("trajectory")),
                ("aircraftName".to_owned(), json!(aircraft_name)),
                ("frameCount".to_owned(), json!(frames.len())),
            ]
            .into_iter()
            .collect(),
        ),
        foreign_members: None,
    };

    let mut features = vec![line_feature];
    features.extend(sample_features);

    let fc = FeatureCollection {
        bbox: None,
        features,
        foreign_members: None,
    };

    fs::write(path, GeoJson::FeatureCollection(fc).to_string()).context("writing geojson")?;
    Ok(())
}
