from copy import deepcopy
import csv
from dataclasses import replace
from pathlib import Path
import random

import pytest

from colocation.capture import ingest_capture, load_pose_events, load_pose_manifest, parse_capture_samples
from colocation.config import load_config
from colocation.evaluate import score_groups
from colocation.models import Device
from colocation.pipeline import infer_observations
from colocation.storage import load_observations, write_observations
from colocation.synthetic import generate_synthetic


@pytest.fixture
def config():
    return load_config(Path(__file__).parents[1] / "config" / "report1.json")


def test_default_synthetic_pipeline_recovers_two_pairs_and_reports_metrics(config):
    observations, devices, _, truth = generate_synthetic(config, 9500)
    result = infer_observations(observations, config, devices)
    assert result.groups == [["D1", "M1"], ["D2", "M2"]]
    metrics = score_groups({"trial_id": result.trial_id, "groups": result.groups}, truth)
    assert metrics["pairwise_f1"] == 1
    assert metrics["count_absolute_error"] == 0
    assert result.summary["eligible_device_count"] == 4
    assert result.summary["quality"]["low_coverage_devices"] == []
    assert len(result.rwr_scores) == 12
    assert all(source != target for source, target in result.rwr_scores)


def test_inference_ignores_synthetic_geometry_labels_and_row_order(config):
    observations, devices, _, _ = generate_synthetic(config, 9500)
    expected = infer_observations(observations, config, devices)
    config = deepcopy(config)
    config["synthetic"] = {"invalid_for_generation": "inference must never consult this"}
    shuffled = list(observations)
    random.Random(9500).shuffle(shuffled)
    actual = infer_observations(shuffled, config, list(reversed(devices)))
    assert actual.groups == expected.groups
    assert actual.rwr_scores == expected.rwr_scores
    assert actual.pearson_scores == expected.pearson_scores
    assert actual.summary == expected.summary


def test_synthetic_and_observed_csv_adapters_yield_identical_inference(tmp_path, config):
    observations, devices, poses, _ = generate_synthetic(config, 9500)
    sample_path, event_path, pose_path = [tmp_path / name for name in ("samples.csv", "events.csv", "poses.csv")]
    with sample_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["device_time_ms", "device_id", "rssi_dbm", "channel"])
        writer.writerows((row.device_time_ms, row.device_id, row.rssi_dbm, row.channel) for row in observations)
    with event_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["event_index", "device_time_ms", "pose_id", "phase"])
        for index, pose in enumerate(poses):
            writer.writerow([2 * index, pose.capture_start_ms, pose.pose_id, "CAPTURE_START"])
            writer.writerow([2 * index + 1, pose.capture_end_ms, pose.pose_id, "CAPTURE_END"])
    with pose_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["pose_id", "pose_index", "x_m", "y_m"])
        writer.writerows((pose.pose_id, pose.pose_index, pose.x_m, pose.y_m) for pose in poses)
    trial_id = observations[0].trial_id
    samples = parse_capture_samples(sample_path, "observed-csv")
    events = load_pose_events(event_path, trial_id=trial_id, receiver_id="RX1")
    manifest = load_pose_manifest(pose_path, trial_id)
    captured, quality = ingest_capture(samples, events, manifest, trial_id, "RX1", config)
    assert quality["accepted_rows"] == len(observations)
    assert quality["excluded_rows"] == 0
    assert captured == observations
    canonical_path = tmp_path / "observations.jsonl"
    write_observations(canonical_path, captured)
    captured = load_observations(canonical_path)
    random.Random(16).shuffle(captured)
    generated_result = infer_observations(observations, config, devices)
    captured_result = infer_observations(captured, config, devices)
    assert generated_result.groups == captured_result.groups
    assert generated_result.rwr_scores == captured_result.rwr_scores
    assert generated_result.pearson_scores == captured_result.pearson_scores
    assert generated_result.summary == captured_result.summary


def test_single_tx_and_zero_sample_manifest_devices_are_singletons(config):
    observations, devices, _, _ = generate_synthetic(config, 9500)
    trial = observations[0].trial_id
    selected = [row for row in observations if row.device_id == devices[0].device_id]
    manifest = [devices[0], Device(trial_id=trial, device_id="known-but-unheard")]
    result = infer_observations(selected, config, manifest)
    assert result.groups == [["M1"], ["known-but-unheard"]]
    assert result.summary["eligible_device_count"] == 1
    assert "known-but-unheard" in result.summary["quality"]["low_coverage_devices"]
    assert any("Fewer than two" in warning for warning in result.summary["quality"]["warnings"])
    assert result.rwr_scores == {}


def test_manifest_only_dataset_preserves_known_devices_with_diagnostics(config):
    result = infer_observations([], config, [Device(trial_id="empty", device_id="no-samples")])
    assert result.groups == [["no-samples"]]
    assert result.summary["quality"]["per_device"]["no-samples"]["packet_count"] == 0
    assert result.summary["eligible_device_count"] == 0


def test_missing_manifest_warns_and_manifest_trial_mismatches_fail(config):
    observations, devices, _, _ = generate_synthetic(config, 9500)
    result = infer_observations(observations, config)
    assert result.groups == [["D1", "M1"], ["D2", "M2"]]
    assert any("fully unseen" in warning for warning in result.summary["quality"]["warnings"])
    with pytest.raises(ValueError, match="exactly one trial"):
        infer_observations(observations, config, [replace(devices[0], trial_id="other")])
    with pytest.raises(ValueError, match="duplicate device"):
        infer_observations(observations, config, [devices[0], devices[0]])


def test_ambient_or_legacy_rows_without_positions_cannot_enter_inference(config):
    observations, devices, _, _ = generate_synthetic(config, 9500)
    unknown_pose = [replace(row, pose_id=None) for row in observations]
    with pytest.raises(ValueError, match="requires pose_id"):
        infer_observations(unknown_pose, config, devices)
