from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean


def load_metrics(metrics_dir: Path):
    rows = []
    for path in sorted(metrics_dir.glob("*.metrics.json")):
        if path.name.endswith(".viz.metrics.json"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data["file"] = path.name
        rows.append(data)
    return rows


def summarize(rows):
    if not rows:
        return {
            "status": "no_metrics_found",
            "message": "No parser metrics files were found.",
        }

    status_counts = {}
    for r in rows:
        status = r.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    parse_ms = [r.get("parse_ms", 0) for r in rows]
    total_ms = [r.get("total_ms", 0) for r in rows]

    decoded = [r for r in rows if r.get("status") == "decoded"]
    blocked = [r for r in rows if r.get("status") != "decoded"]

    summary = {
        "status": "ok",
        "files_processed": len(rows),
        "decoded_files": len(decoded),
        "blocked_files": len(blocked),
        "status_counts": status_counts,
        "avg_parse_ms": round(mean(parse_ms), 2),
        "avg_total_ms": round(mean(total_ms), 2),
        "max_parse_ms": max(parse_ms),
        "max_total_ms": max(total_ms),
    }

    top_bottlenecks = []
    if blocked:
        top_bottlenecks.append(
            "Encrypted logs require DJI keychains; frame decode is blocked until --api-key or cached keychains are provided."
        )
    if summary["avg_parse_ms"] > 500:
        top_bottlenecks.append(
            "Parser initialization is above 500 ms average. Consider parallel ingest and warm binary execution for larger batches."
        )

    if not top_bottlenecks:
        top_bottlenecks.append("No critical bottlenecks detected in current metric set.")

    summary["top_bottlenecks"] = top_bottlenecks
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize parser performance bottlenecks")
    parser.add_argument("--metrics-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    rows = load_metrics(args.metrics_dir)
    summary = summarize(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
