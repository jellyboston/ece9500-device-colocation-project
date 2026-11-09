"""Acceptance cases vary device counts and evidence without truth-aware inference."""

import json
import random
from dataclasses import replace
from pathlib import Path

import pytest

from colocation.evaluate import score_groups
from colocation.models import Device, Truth
from colocation.pipeline import infer_observations
from colocation.synthetic import generate_synthetic


CONFIG = Path(__file__).resolve().parents[1] / "config" / "report1.json"


def config_for(sizes, centers, *, max_devices=2, ids=None):
    config = json.loads(CONFIG.read_text())
    config["synthetic"]["group_sizes"] = sizes
    config["synthetic"]["group_center_x_m"] = centers
    config["synthetic"].pop("device_ids")
    if ids is not None:
        config["synthetic"]["device_ids"] = ids
    config["grouping"]["max_devices_per_group"] = max_devices
    return config


def assert_partition(groups, devices, max_devices):
    actual = [device_id for group in groups for device_id in group]
    expected = {device.device_id for device in devices}
    assert set(actual) == expected
    assert len(actual) == len(set(actual)) == len(expected)
    assert all(1 <= len(group) <= max_devices for group in groups)
    assert groups == sorted([sorted(group) for group in groups])


def report_metrics(record_property, result, truth):
    metrics = score_groups(result.groups, truth)
    record_property("rwr_metrics", json.dumps(metrics, sort_keys=True))
    record_property("pearson_metrics", json.dumps(score_groups(result.baseline_groups, truth), sort_keys=True))
    assert 0 <= metrics["pairwise_f1"] <= 1
    assert metrics["count_absolute_error"] >= 0
    return metrics


def test_default_four_device_acceptance(record_property):
    config = json.loads(CONFIG.read_text())
    observations, devices, _, truth = generate_synthetic(config, 9500)
    result = infer_observations(observations, config, devices)
    assert result.groups == [["D1", "M1"], ["D2", "M2"]]
    assert_partition(result.groups, devices, 2)
    metrics = report_metrics(record_property, result, truth)
    assert metrics["pairwise_f1"] == 1
    assert metrics["count_absolute_error"] == 0


def test_six_devices_three_pairs_arbitrary_ids_and_shuffled_rows(record_property):
    config = config_for(
        [2, 2, 2], [1.0, 4.5, 8.0],
        ids=["zeta:phone", "alpha%watch", "device/9", "Ω laptop", "left", "unfamiliar"],
    )
    observations, devices, _, truth = generate_synthetic(config, 9500)
    result = infer_observations(observations, config, devices)
    shuffled = list(observations)
    random.Random(42).shuffle(shuffled)
    again = infer_observations(shuffled, config, list(reversed(devices)))
    assert result.groups == again.groups
    assert result.rwr_scores == again.rwr_scores
    assert_partition(result.groups, devices, 2)
    report_metrics(record_property, result, truth)


def test_five_devices_two_pairs_and_true_singleton(record_property):
    config = config_for([2, 2, 1], [1.0, 4.5, 8.0])
    # Prespecified before inspecting the generated truth or scores.
    config["grouping"]["min_directional_similarity"] = 0.05
    observations, devices, _, truth = generate_synthetic(config, 9500)
    result = infer_observations(observations, config, devices)
    assert_partition(result.groups, devices, 2)
    report_metrics(record_property, result, truth)


def test_two_groups_of_three_use_configurable_k(record_property):
    config = config_for([3, 3], [2.0, 8.0], max_devices=3)
    observations, devices, _, truth = generate_synthetic(config, 9500)
    result = infer_observations(observations, config, devices)
    assert_partition(result.groups, devices, 3)
    assert all(len(candidates) <= 2 for candidates in result.similarity_graph.graph["candidate_lists"].values())
    report_metrics(record_property, result, truth)


def test_incomplete_and_uneven_samples_preserve_sparse_and_unseen_devices(record_property):
    config = json.loads(CONFIG.read_text())
    observations, devices, _, truth = generate_synthetic(config, 9500)
    observations = [
        row for row in observations
        if not (row.device_id == "M1" and row.pose_id not in {"P01", "P02"})
        and not (row.device_id == "D1" and row.pose_id in {"P03", "P05"})
        and not (row.device_id == "D2" and row.sample_index % 2)
    ]
    devices.append(Device(trial_id="synth001", device_id="silent-transmitter"))
    truth.append(Truth(trial_id="synth001", device_id="silent-transmitter", group_id="G3"))
    result = infer_observations(observations, config, devices)
    assert_partition(result.groups, devices, 2)
    assert ["M1"] in result.groups
    assert ["silent-transmitter"] in result.groups
    report_metrics(record_property, result, truth)


def test_zero_observations_with_manifest_returns_singletons():
    config = json.loads(CONFIG.read_text())
    _, devices, _, _ = generate_synthetic(config, 9500)
    result = infer_observations([], config, devices)
    assert result.groups == [[device_id] for device_id in sorted(device.device_id for device in devices)]


def test_noisy_negative_control_records_outcome_without_retuning(record_property):
    config = json.loads(CONFIG.read_text())
    config["synthetic"]["noise_sd_db"] = 12.0
    observations, devices, _, truth = generate_synthetic(config, 9500)
    result = infer_observations(observations, config, devices)
    assert_partition(result.groups, devices, 2)
    record_property("negative_control_noise_sd_db", 12.0)
    report_metrics(record_property, result, truth)


def test_inference_does_not_depend_on_generator_geometry_or_group_config():
    config = json.loads(CONFIG.read_text())
    observations, devices, _, _ = generate_synthetic(config, 9500)
    result = infer_observations(observations, config, devices)
    config["synthetic"] = {"group_sizes": [999], "group_center_x_m": [9999]}
    assert infer_observations(observations, config, devices).groups == result.groups


def test_mixed_trials_and_unknown_poses_are_not_guessed():
    config = json.loads(CONFIG.read_text())
    observations, devices, _, _ = generate_synthetic(config, 9500)
    with pytest.raises(ValueError, match="trial"):
        infer_observations([replace(observations[0], trial_id="other"), *observations[1:]], config, devices)
    with pytest.raises(ValueError, match="pose"):
        infer_observations([replace(observations[0], pose_id=None), *observations[1:]], config, devices)
