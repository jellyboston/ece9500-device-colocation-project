"""Exercise the documented CLI as users run it, with isolated generated files."""

import csv
import json
from math import isfinite
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from colocation.cli import main


ANALYSIS = Path(__file__).parents[1]
REPOSITORY = ANALYSIS.parent
CONFIG = ANALYSIS / "config" / "report1.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_matplotlib_cache = None


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_cli(root, *arguments, expected=0):
    global _matplotlib_cache
    if _matplotlib_cache is None:
        # Reuse one isolated font cache across subprocesses; rebuilding it for
        # every rejection-path test would add unrelated startup work.
        _matplotlib_cache = root / "matplotlib"
    environment = os.environ.copy()
    environment.update(MPLBACKEND="Agg", MPLCONFIGDIR=str(_matplotlib_cache))
    result = subprocess.run(
        [sys.executable, "-m", "colocation.cli", *map(str, arguments)],
        cwd=ANALYSIS, env=environment, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == expected, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    if expected:
        assert "Error:" in result.stderr
        assert "Traceback" not in result.stderr
    return result


@pytest.fixture(scope="module")
def synthetic_workflow(tmp_path_factory):
    root = tmp_path_factory.mktemp("cli-synthetic")
    data, output = root / "data", root / "output"
    run_cli(root, "synthesize", "--config", CONFIG, "--seed", 9500, "--out", data)
    run_cli(root, "infer", "--input", data / "observations.jsonl", "--config", CONFIG, "--out", output)
    evaluation = run_cli(
        root, "evaluate", "--predictions", output / "groups.json",
        "--truth", data / "truth.json", "--out", output / "metrics.json",
    )
    return root, data, output, evaluation


def test_synthesize_infer_evaluate_cli_produces_report_artifacts(synthetic_workflow):
    _, data, output, evaluation = synthetic_workflow
    for filename in ("observations.jsonl", "devices.json", "poses.json", "truth.json", "config_used.json", "provenance.json"):
        assert (data / filename).is_file()
    for filename in ("groups.json", "observations_summary.json", "config_used.json", "device_similarity.csv", "metrics.json"):
        assert (output / filename).is_file()
    for filename in ("rssi_by_pose.png", "rssistate_graph.png", "similarity_heatmap.png", "device_similarity_graph.png"):
        assert (output / filename).read_bytes().startswith(PNG_SIGNATURE)
    predictions = read_json(output / "groups.json")
    assert predictions["groups"] == [["D1", "M1"], ["D2", "M2"]]
    metrics = read_json(output / "metrics.json")
    assert metrics["pairwise_f1"] == 1
    assert metrics["count_absolute_error"] == 0
    assert "pearson_baseline" in metrics
    assert metrics["graph_minus_baseline_pairwise_f1"] == metrics["pairwise_f1"] - metrics["pearson_baseline"]["pairwise_f1"]
    assert "Pearson baseline" in evaluation.stdout
    assert read_json(data / "provenance.json")["random_seed"] == 9500
    assert read_json(output / "provenance.json")["input_provenance"]["random_seed"] == 9500
    assert read_json(output / "config_used.json") == read_json(CONFIG)
    with (output / "device_similarity.csv").open(newline="", encoding="utf-8") as handle:
        scores = list(csv.DictReader(handle))
    assert {row["method"] for row in scores} == {"rwr", "pearson"}
    assert all(row["source_device_id"] != row["target_device_id"] for row in scores)
    assert all(isfinite(float(row["score"])) for row in scores)


def test_wisniff_cli_summarizes_real_ambient_data_without_identifying_strings(tmp_path):
    output = tmp_path / "wisniff"
    run_cli(tmp_path, "summarize-wisniff", "--input", REPOSITORY / "wisniff" / "data" / "wisniff_data.json", "--out", output)
    summary = read_json(output / "summary.json")
    assert summary["record_count"] == 40
    assert summary["unique_mac_count"] == 18
    assert summary["repeated_record_count"] == 22
    assert (summary["rssi_min_dbm"], summary["rssi_max_dbm"]) == (-93, -33)
    assert summary["limitations"]
    assert (output / "rssi_histogram.png").read_bytes().startswith(PNG_SIGNATURE)
    assert not re.search(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", (output / "summary.json").read_text())
    assert not (output / "groups.json").exists()


def test_legacy_csi_cli_keeps_unknown_positions_and_infer_refuses_them(tmp_path):
    canonical = tmp_path / "legacy.jsonl"
    run_cli(
        tmp_path, "ingest-csi", "--input", REPOSITORY / "wisniff" / "tools" / "csi_COM6_1794086754_useful.csv",
        "--trial-id", "legacy", "--receiver-id", "RX1", "--device-id", "T1", "--out", canonical,
    )
    observations = [json.loads(line) for line in canonical.read_text().splitlines()]
    assert len(observations) == 42
    assert all(row["pose_id"] is None and row["host_time_utc"] is None for row in observations)
    assert all(len(row["csi_magnitudes"]) == 57 for row in observations)
    assert observations[0]["csi_magnitudes"][0] == 14
    failed = run_cli(tmp_path, "infer", "--input", canonical, "--config", CONFIG, "--out", tmp_path / "invalid-inference", expected=2)
    assert "pose_id" in failed.stderr
    assert not (tmp_path / "invalid-inference" / "groups.json").exists()


@pytest.fixture
def staged_capture(tmp_path):
    samples, events, poses = [tmp_path / filename for filename in ("samples.csv", "events.csv", "poses.csv")]
    # The third pose is deliberately sparse: ingestion preserves attributable
    # rows and inference later applies the configured per-pose quality gate.
    sample_times = [100, 110, 120, 220, 320, 400, 410, 420, 600, 610]
    samples.write_text("".join(f"CSI,{timestamp},-45,6,3,0,12,15,14\n" for timestamp in sample_times), encoding="utf-8")
    events.write_text(
        "event_index,device_time_ms,pose_id,phase\n"
        "0,100,P1,CAPTURE_START\n1,200,P1,CAPTURE_END\n"
        "2,210,P1,MOVE_START\n3,300,P2,MOVE_END\n4,310,P2,SETTLE_START\n"
        "5,400,P2,CAPTURE_START\n6,500,P2,CAPTURE_END\n"
        "7,600,P3,CAPTURE_START\n8,700,P3,CAPTURE_END\n",
        encoding="utf-8",
    )
    poses.write_text("pose_id,pose_index,x_m,y_m\nP1,1,0,0\nP2,2,1,0\nP3,3,2,0\n", encoding="utf-8")
    return samples, events, poses


def capture_arguments(staged_capture, output):
    samples, events, poses = staged_capture
    return [
        "ingest-capture", "--input", samples, "--events", events, "--poses", poses,
        "--format", "csi-legacy", "--trial-id", "capture", "--receiver-id", "RX1",
        "--single-known-transmitter", "--device-id", "T1", "--config", CONFIG, "--out", output,
    ]


def test_capture_cli_excludes_movement_and_preserves_sparse_singleton(tmp_path, staged_capture):
    data, output = tmp_path / "data", tmp_path / "inferred"
    capture = run_cli(tmp_path, *capture_arguments(staged_capture, data))
    for filename in ("observations.jsonl", "devices.json", "poses.json", "ingest_report.json"):
        assert (data / filename).is_file()
    report = read_json(data / "ingest_report.json")
    assert report["status"] == "accepted"
    assert (report["total_rows"], report["accepted_rows"], report["excluded_rows"]) == (10, 8, 2)
    assert report["counts_by_reason"] == {"movement": 1, "settling": 1}
    assert report["coverage"]["T1"]["low_coverage"]
    assert "8/10 accepted" in capture.stdout
    inference = run_cli(tmp_path, "infer", "--input", data / "observations.jsonl", "--config", CONFIG, "--out", output)
    assert read_json(output / "groups.json")["groups"] == [["T1"]]
    summary = read_json(output / "observations_summary.json")
    assert summary["eligible_device_count"] == 0
    assert summary["quality"]["low_coverage_devices"] == ["T1"]
    assert "insufficient evidence" in inference.stdout
    assert "random_seed" not in read_json(output / "provenance.json")["input_provenance"]
    assert read_json(output / "ingest_report.json") == report


@pytest.mark.parametrize("failure", ["missing-events", "missing-poses", "unknown-pose", "wrong-channel"])
def test_capture_cli_errors_write_rejection_sidecar(tmp_path, staged_capture, failure):
    samples, events, poses = staged_capture
    if failure == "missing-events":
        events.unlink()
    elif failure == "missing-poses":
        poses.unlink()
    elif failure == "unknown-pose":
        events.write_text(events.read_text().replace("P3", "unlisted"), encoding="utf-8")
    else:
        samples.write_text(samples.read_text().replace(",-45,6,3,", ",-45,11,3,"), encoding="utf-8")
    output = tmp_path / "rejected"
    result = run_cli(tmp_path, *capture_arguments(staged_capture, output), expected=2)
    report = read_json(output / "ingest_report.json")
    assert report["status"] == "rejected"
    assert report["error"] in result.stderr
    assert report["counts_by_reason"]["invalid_input"] == 1
    assert not (output / "observations.jsonl").exists()


def test_observed_csv_cli_rejects_global_transmitter_attribution(tmp_path, staged_capture):
    samples = tmp_path / "observed.csv"
    samples.write_text("device_time_ms,device_id,rssi_dbm,channel\n100,per-row-ID,-45,6\n", encoding="utf-8")
    arguments = capture_arguments((samples, staged_capture[1], staged_capture[2]), tmp_path / "rejected")
    arguments[arguments.index("csi-legacy")] = "observed-csv"
    result = run_cli(tmp_path, *arguments, expected=2)
    assert "omit the global" in result.stderr
    assert read_json(tmp_path / "rejected" / "ingest_report.json")["status"] == "rejected"


@pytest.mark.parametrize("failure", ["missing-device-manifest", "wrong-device-trial", "wrong-pose-trial"])
def test_infer_cli_rejects_explicit_missing_or_wrong_manifest(synthetic_workflow, tmp_path, failure):
    _, source_data, _, _ = synthetic_workflow
    arguments = ["infer", "--input", source_data / "observations.jsonl", "--config", CONFIG, "--out", tmp_path / "output"]
    if failure == "wrong-pose-trial":
        data = tmp_path / "bad-data"
        data.mkdir()
        (data / "observations.jsonl").write_bytes((source_data / "observations.jsonl").read_bytes())
        poses = read_json(source_data / "poses.json")
        poses[0]["trial_id"] = "different-trial"
        (data / "poses.json").write_text(json.dumps(poses), encoding="utf-8")
        arguments[arguments.index(source_data / "observations.jsonl")] = data / "observations.jsonl"
    else:
        manifest = tmp_path / "devices.json"
        if failure == "wrong-device-trial":
            devices = read_json(source_data / "devices.json")
            devices[0]["trial_id"] = "different-trial"
            manifest.write_text(json.dumps(devices), encoding="utf-8")
        arguments.extend(["--devices", manifest])
    run_cli(tmp_path, *arguments, expected=2)
    assert not (tmp_path / "output" / "groups.json").exists()


def test_rejected_capture_report_blocks_inference_of_stale_canonical_rows(synthetic_workflow, tmp_path):
    _, source_data, _, _ = synthetic_workflow
    canonical = tmp_path / "observations.jsonl"
    canonical.write_bytes((source_data / "observations.jsonl").read_bytes())
    (tmp_path / "ingest_report.json").write_text(json.dumps({
        "status": "rejected", "error": "The latest ingestion failed validation",
    }), encoding="utf-8")
    result = run_cli(tmp_path, "infer", "--input", canonical, "--config", CONFIG, "--out", tmp_path / "output", expected=2)
    assert "rejected" in result.stderr
    assert not (tmp_path / "output" / "groups.json").exists()


@pytest.mark.parametrize("output_alias", ["same-path", "symlink", "hardlink"])
def test_csi_cli_refuses_to_overwrite_source_or_its_alias(tmp_path, capsys, output_alias):
    source = tmp_path / "capture.csv"
    original = b"CSI,100,-45,6,3,0,12,15,14\n"
    source.write_bytes(original)
    output = source
    if output_alias != "same-path":
        output = tmp_path / "alias.jsonl"
        if output_alias == "symlink":
            output.symlink_to(source)
        else:
            os.link(source, output)
    status = main([
        "ingest-csi", "--input", str(source), "--trial-id", "trial", "--receiver-id", "RX1",
        "--device-id", "T1", "--out", str(output),
    ])
    assert status == 2
    assert "overwrite input" in capsys.readouterr().err
    assert source.read_bytes() == original
    assert output.read_bytes() == original
    if output_alias == "symlink":
        assert output.is_symlink()


def test_evaluate_cli_refuses_to_overwrite_independent_truth(tmp_path, capsys):
    predictions, truth = tmp_path / "groups.json", tmp_path / "truth.json"
    predictions.write_text(json.dumps({"trial_id": "trial", "groups": [["D1"]]}), encoding="utf-8")
    original = b'[{"trial_id":"trial","device_id":"D1","group_id":"G1"}]\n'
    truth.write_bytes(original)
    status = main([
        "evaluate", "--predictions", str(predictions), "--truth", str(truth), "--out", str(truth),
    ])
    assert status == 2
    assert "overwrite input" in capsys.readouterr().err
    assert truth.read_bytes() == original


def test_capture_error_handler_cannot_overwrite_raw_input_with_rejection_report(tmp_path, staged_capture, capsys):
    source, events, poses = staged_capture
    output = tmp_path / "collision"
    output.mkdir()
    raw_input = output / "ingest_report.json"
    original = source.read_bytes()
    raw_input.write_bytes(original)
    arguments = capture_arguments((raw_input, events, poses), output)
    status = main(list(map(str, arguments)))
    assert status == 2
    assert "overwrite input" in capsys.readouterr().err
    assert raw_input.read_bytes() == original
    assert not (output / "observations.jsonl").exists()


def test_synthesize_cli_refuses_config_output_collision_before_any_writes(tmp_path, capsys):
    config_input = tmp_path / "config_used.json"
    original = b" " + CONFIG.read_bytes()
    config_input.write_bytes(original)
    status = main([
        "synthesize", "--config", str(config_input), "--seed", "9500", "--out", str(tmp_path),
    ])
    assert status == 2
    assert "overwrite input" in capsys.readouterr().err
    assert config_input.read_bytes() == original
    assert not (tmp_path / "observations.jsonl").exists()
