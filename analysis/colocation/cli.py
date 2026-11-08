"""Run from analysis/: python -m colocation.cli --help."""

import argparse
from collections import Counter
import csv
from dataclasses import replace
from pathlib import Path
import sys

from .capture import ingest_capture, load_pose_events, load_pose_manifest, parse_capture_samples
from .config import load_config
from .evaluate import score_groups
from .ingest import load_csi_csv, load_wisniff
from .models import Device, Truth, Trial
from .pipeline import infer_observations
from .plots import plot_rssi_histogram, save_inference_figures
from .storage import load_devices, load_observations, load_poses, read_json, write_json, write_observations
from .synthetic import generate_synthetic


def _check_output_paths(args) -> None:
    """Protect explicit inputs and discovered sidecars before any output write."""
    input_paths = [getattr(args, name, None) for name in ("input", "config", "predictions", "truth", "events", "poses", "devices")]
    if args.command == "infer":
        input_paths.extend(path for name in ("devices.json", "poses.json", "provenance.json", "ingest_report.json") if (path := args.input.parent / name).exists())
    inputs = [Path(path).resolve() for path in input_paths if path is not None]
    files_by_command = {
        "synthesize": ["observations.jsonl", "devices.json", "poses.json", "truth.json", "trial.json", "config_used.json", "provenance.json"],
        "infer": ["groups.json", "observations_summary.json", "config_used.json", "provenance.json", "ingest_report.json", "device_similarity.csv", "rssi_by_pose.png", "rssistate_graph.png", "similarity_heatmap.png", "device_similarity_graph.png"],
        "summarize-wisniff": ["summary.json", "rssi_histogram.png"],
        "ingest-capture": ["observations.jsonl", "devices.json", "poses.json", "ingest_report.json", "trial.json", "provenance.json"],
    }
    outputs = [args.out / name for name in files_by_command[args.command]] if args.command in files_by_command else [args.out]
    for output in outputs:
        resolved = output.resolve()
        if resolved in inputs or (output.exists() and any(path.exists() and output.samefile(path) for path in inputs)):
            raise ValueError(f"output would overwrite input {output}; choose a separate output path")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline RSSI colocation prototype; ground truth is used only by evaluate.")
    actions = parser.add_subparsers(dest="command", required=True)
    synth = actions.add_parser("synthesize", help="Generate seeded toy RSSI data and separate evaluation truth")
    synth.add_argument("--config", required=True, type=Path)
    synth.add_argument("--seed", required=True, type=int)
    synth.add_argument("--out", required=True, type=Path)
    infer = actions.add_parser("infer", help="Infer groups from canonical pose-labeled observations")
    infer.add_argument("--input", required=True, type=Path)
    infer.add_argument("--config", required=True, type=Path)
    infer.add_argument("--devices", type=Path, help="Override automatic sibling devices.json discovery")
    infer.add_argument("--out", required=True, type=Path)
    evaluate = actions.add_parser("evaluate", help="Score a prediction against independently recorded truth")
    evaluate.add_argument("--predictions", required=True, type=Path)
    evaluate.add_argument("--truth", required=True, type=Path)
    evaluate.add_argument("--out", required=True, type=Path)
    summary = actions.add_parser("summarize-wisniff", help="Summarize ambient RSSI; no colocation inference")
    summary.add_argument("--input", required=True, type=Path)
    summary.add_argument("--out", required=True, type=Path)
    csi = actions.add_parser("ingest-csi", help="Exploratory single-known-TX CSI adapter; positions remain unknown")
    csi.add_argument("--input", required=True, type=Path)
    csi.add_argument("--trial-id", required=True)
    csi.add_argument("--receiver-id", required=True)
    csi.add_argument("--device-id", required=True, help="Operator assertion of one known controlled transmitter")
    csi.add_argument("--out", required=True, type=Path)
    capture = actions.add_parser("ingest-capture", help="Join samples and stationary pose events from one ESP32 recording")
    capture.add_argument("--input", required=True, type=Path)
    capture.add_argument("--events", required=True, type=Path)
    capture.add_argument("--poses", required=True, type=Path)
    capture.add_argument("--format", required=True, choices=["csi-legacy", "observed-csv"])
    capture.add_argument("--trial-id", required=True)
    capture.add_argument("--receiver-id", required=True)
    capture.add_argument("--single-known-transmitter", action="store_true")
    capture.add_argument("--device-id")
    capture.add_argument("--config", required=True, type=Path)
    capture.add_argument("--out", required=True, type=Path)
    return parser


def _synthesize(args) -> None:
    config = load_config(args.config, synthetic=True)
    observations, devices, poses, truth = generate_synthetic(config, args.seed)
    write_observations(args.out / "observations.jsonl", observations)
    for name, value in (("devices", devices), ("poses", poses), ("truth", truth)):
        write_json(args.out / f"{name}.json", value)
    trial_id = devices[0].trial_id
    write_json(args.out / "trial.json", Trial(trial_id=trial_id, source="synthetic", channel=6, notes="Illustrative toy model; no measured RF validation"))
    write_json(args.out / "config_used.json", config)
    write_json(args.out / "provenance.json", {"source": "synthetic", "random_seed": args.seed, "trial_id": trial_id})
    print(f"Generated {len(observations)} synthetic packets, {len(devices)} devices, {len(poses)} poses; seed={args.seed}.")
    print(f"Truth is separate: {args.out / 'truth.json'} (evaluation only).")


def _infer(args) -> None:
    config = load_config(args.config)
    quality_path = args.input.parent / "ingest_report.json"
    capture_quality = read_json(quality_path) if quality_path.exists() else None
    if capture_quality is not None:
        if not isinstance(capture_quality, dict):
            raise ValueError("ingest_report.json must contain a capture-quality object")
        if capture_quality.get("status") == "rejected":
            raise ValueError("capture ingestion was rejected; fix the inputs and rerun ingest-capture before infer")
    observations = load_observations(args.input)
    device_path = args.devices if args.devices is not None else args.input.parent / "devices.json"
    devices = load_devices(device_path) if args.devices is not None or device_path.exists() else None
    result = infer_observations(observations, config, devices)
    pose_path = args.input.parent / "poses.json"
    poses = load_poses(pose_path) if pose_path.exists() else None
    if poses is not None:
        if any(pose.trial_id != result.trial_id for pose in poses):
            raise ValueError("pose manifest and observation trial IDs do not match")
        unknown = {row.pose_id for row in observations} - {pose.pose_id for pose in poses}
        if unknown:
            raise ValueError(f"observation pose IDs absent from poses.json: {sorted(unknown)}")
    write_json(args.out / "groups.json", {
        "trial_id": result.trial_id, "groups": result.groups,
        "baseline_groups": result.baseline_groups, "metadata": result.summary["grouping"],
    })
    write_json(args.out / "observations_summary.json", result.summary)
    write_json(args.out / "config_used.json", config)
    provenance = {"input_file": str(args.input), "devices_file": str(device_path) if devices is not None else None}
    source_provenance = args.input.parent / "provenance.json"
    if source_provenance.exists():
        provenance["input_provenance"] = read_json(source_provenance)
    if capture_quality is not None:
        write_json(args.out / "ingest_report.json", capture_quality)
    write_json(args.out / "provenance.json", provenance)
    with (args.out / "device_similarity.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["trial_id", "source_device_id", "target_device_id", "method", "score"])
        for method, scores in (("rwr", result.rwr_scores), ("pearson", result.pearson_scores)):
            for (source, target), score in sorted(scores.items()):
                writer.writerow([result.trial_id, source, target, method, repr(score)])
    save_inference_figures(result, args.out, poses)
    print(f"Predicted {len(result.groups)} groups from {len(result.devices)} devices: {result.groups}")
    for warning in result.summary["quality"]["warnings"]:
        print(f"Warning: {warning}")


def _evaluate(args) -> None:
    predictions, raw_truth = read_json(args.predictions), read_json(args.truth)
    truth_rows = raw_truth.get("truth") if isinstance(raw_truth, dict) else raw_truth
    if not isinstance(truth_rows, list):
        raise ValueError("truth must be an array of {trial_id,device_id,group_id} records")
    truth = [Truth(**row) for row in truth_rows]
    metrics = score_groups(predictions, truth)
    if isinstance(predictions, dict) and "baseline_groups" in predictions:
        baseline = score_groups({"groups": predictions["baseline_groups"], "trial_id": predictions.get("trial_id")}, truth)
        metrics["pearson_baseline"] = baseline
        difference = metrics["pairwise_f1"] - baseline["pairwise_f1"]
        metrics["graph_minus_baseline_pairwise_f1"] = difference
        metrics["graph_improved_pairwise_f1"] = difference > 0
        print(f"Pearson baseline F1={baseline['pairwise_f1']:.3f}; graph F1 {'improved' if difference > 0 else 'did not improve'}.")
    write_json(args.out, metrics)
    print(f"Pairwise F1={metrics['pairwise_f1']:.3f}; count absolute error={metrics['count_absolute_error']}.")


def _summarize_wisniff(args) -> None:
    observations = load_wisniff(args.input)
    if not observations:
        raise ValueError("WiSniff scan contains no observation records")
    counts = Counter(row.device_id for row in observations)
    summary = {
        "record_count": len(observations), "unique_mac_count": len(counts),
        "repeated_record_count": len(observations) - len(counts),
        "devices_with_repeated_records": sum(count > 1 for count in counts.values()),
        "records_per_scan_alias": dict(sorted(counts.items())),
        "rssi_min_dbm": min(row.rssi_dbm for row in observations),
        "rssi_max_dbm": max(row.rssi_dbm for row in observations),
        "channel_counts": dict(sorted(Counter(str(row.channel) for row in observations).items())),
        "limitations": ["No synchronized receiver poses or per-record timestamps", "No known ownership or colocation labels", "Observed MAC count is not a person count", "Aliases apply only within this scan; raw MAC strings are omitted"],
    }
    write_json(args.out / "summary.json", summary)
    plot_rssi_histogram(observations, args.out / "rssi_histogram.png")
    print(f"WiSniff: {len(observations)} records, {len(counts)} distinct observed MAC strings; no spatial inference.")


def _ingest_csi(args) -> None:
    observations = load_csi_csv(args.input, args.trial_id, args.receiver_id, args.device_id)
    write_observations(args.out, observations)
    print(f"Wrote {len(observations)} exploratory single-TX rows; pose_id remains null and spatial infer will reject them.")


def _ingest_capture(args) -> None:
    config = load_config(args.config)
    samples = parse_capture_samples(args.input, args.format, device_id=args.device_id, single_known_transmitter=args.single_known_transmitter)
    events = load_pose_events(args.events, trial_id=args.trial_id, receiver_id=args.receiver_id)
    poses = load_pose_manifest(args.poses, args.trial_id)
    observations, report = ingest_capture(samples, events, poses, args.trial_id, args.receiver_id, config, source_file=args.input)
    devices = [Device(trial_id=args.trial_id, device_id=device) for device in report["all_device_ids"]]
    # A pose can be revisited; scalar boundaries are recorded only for one window.
    by_pose = {pose.pose_id: [window for window in report["capture_windows"] if window["pose_id"] == pose.pose_id] for pose in poses}
    poses = [replace(pose, capture_start_ms=by_pose[pose.pose_id][0]["start_ms"], capture_end_ms=by_pose[pose.pose_id][0]["end_ms"]) if len(by_pose[pose.pose_id]) == 1 else pose for pose in poses]
    report.update({"status": "accepted", "input_format": args.format, "single_known_transmitter": args.single_known_transmitter})
    write_observations(args.out / "observations.jsonl", observations)
    write_json(args.out / "devices.json", devices)
    write_json(args.out / "poses.json", poses)
    write_json(args.out / "ingest_report.json", report)
    write_json(args.out / "trial.json", Trial(trial_id=args.trial_id, source="serial", channel=config["capture"]["expected_channel"]))
    write_json(args.out / "provenance.json", {"source": "serial", "samples_file": str(args.input), "events_file": str(args.events), "poses_file": str(args.poses), "clock_provenance": report["clock_provenance"]})
    print(f"Capture: {report['accepted_rows']}/{report['total_rows']} accepted; {report['excluded_rows']} excluded: {report['counts_by_reason']}")
    for warning in report["warnings"]:
        print(f"Warning: {warning}")


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    commands = {"synthesize": _synthesize, "infer": _infer, "evaluate": _evaluate, "summarize-wisniff": _summarize_wisniff, "ingest-csi": _ingest_csi, "ingest-capture": _ingest_capture}
    paths_checked = False
    try:
        _check_output_paths(args)
        paths_checked = True
        commands[args.command](args)
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        if args.command == "ingest-capture" and paths_checked:
            try:
                write_json(args.out / "ingest_report.json", {"status": "rejected", "trial_id": args.trial_id, "source_file": str(args.input), "error": str(exc), "counts_by_reason": {"invalid_input": 1}, "note": "Ingestion stopped at the first validation error; invalid_input counts failures, not sample rows."})
            except OSError:
                pass
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
