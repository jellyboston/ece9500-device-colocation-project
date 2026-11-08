from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from colocation.config import load_config, validate_config
from colocation.features import aggregate_by_pose, encode_rssi_states
from colocation.models import Observation, PoseRSSI
from colocation.storage import load_devices, load_observations, load_poses


@pytest.fixture
def config():
    return load_config(Path(__file__).parents[1] / "config" / "report1.json")


def packets(device, pose, center, count=3, *, start=0, receiver="RX1"):
    return [
        Observation(
            trial_id="test", receiver_id=receiver, sample_index=start + index,
            device_id=device, pose_id=pose, rssi_dbm=center + index - count // 2, channel=6,
        )
        for index in range(count)
    ]


def test_pose_medians_center_device_power_offsets_and_share_states(config):
    config["rssi"]["min_poses_per_device"] = 2
    observations = (
        packets("phone", "P1", -60, start=0)
        + packets("phone", "P2", -40, start=10)
        + packets("watch", "P1", -65, start=20)
        + packets("watch", "P2", -45, start=30)
    )
    rows, quality = aggregate_by_pose(observations, config)
    assert {row.rssi_relative_db for row in rows} == {-10, 10}
    assert quality["low_coverage_devices"] == []
    edges = encode_rssi_states(rows, config)
    per_pose = {}
    for edge in edges:
        per_pose.setdefault(edge.pose_id, set()).add((edge.receiver_id, edge.pose_id, edge.bin_index))
    assert len(per_pose["P1"]) == len(per_pose["P2"]) == 1
    assert per_pose["P1"] != per_pose["P2"]
    assert {edge.weight for edge in edges} == {3}


def test_weak_cells_are_dropped_and_sparse_devices_do_not_gain_graph_edges(config):
    observations = (
        packets("strong", "P1", -60, start=0)
        + packets("strong", "P2", -50, start=10)
        + packets("strong", "P3", -40, start=20)
        + packets("sparse", "P1", -62, start=30)
        + packets("sparse", "P2", -52, count=2, start=40)
    )
    rows, quality = aggregate_by_pose(observations, config)
    assert quality["retained_cell_count"] == 4
    assert quality["dropped_weak_cell_count"] == 1
    assert quality["dropped_weak_packet_count"] == 2
    assert quality["low_coverage_devices"] == ["sparse"]
    assert quality["per_device"]["sparse"]["retained_pose_count"] == 1
    assert any(row.device_id == "sparse" and not row.eligible for row in rows)
    assert {edge.device_id for edge in encode_rssi_states(rows, config)} == {"strong"}


def test_device_mean_is_unweighted_mean_of_pose_medians(config):
    config["rssi"]["min_poses_per_device"] = 2
    observations = packets("device", "P1", -60, count=3) + packets("device", "P2", -40, count=9, start=100)
    rows, _ = aggregate_by_pose(observations, config)
    assert [row.rssi_median_dbm for row in rows] == [-60, -40]
    assert [row.rssi_relative_db for row in rows] == [-10, 10]
    config["rssi"]["max_packets_weight"] = 5
    assert [edge.weight for edge in encode_rssi_states(rows, config)] == [3, 5]


def test_threshold_boundaries_use_upper_bin_and_bin_count_is_configurable(config):
    relative = [-8.0001, -8, -3, 3, 8, 8.0001]
    rows = [
        PoseRSSI(
            trial_id="test", receiver_id="RX1", device_id="device", pose_id=f"P{index}",
            rssi_median_dbm=-60 + value, rssi_relative_db=value, packet_count=20,
        )
        for index, value in enumerate(relative)
    ]
    assert [edge.bin_index for edge in encode_rssi_states(rows, config)] == [0, 1, 2, 3, 4, 4]
    config["rssi"]["relative_bin_thresholds_db"] = [-8, 8]
    assert [edge.bin_index for edge in encode_rssi_states(rows, config)] == [0, 1, 1, 1, 2, 2]
    config["rssi"]["relative_bin_thresholds_db"] = []
    assert {edge.bin_index for edge in encode_rssi_states(rows, config)} == {0}


def test_input_order_is_irrelevant_and_observation_keys_are_receiver_scoped(config):
    config["rssi"]["min_poses_per_device"] = 1
    observations = packets("D", "P1", -60) + packets("D", "P2", -40, receiver="RX2")
    assert aggregate_by_pose(observations, config) == aggregate_by_pose(list(reversed(observations)), config)
    with pytest.raises(ValueError, match="duplicate observation"):
        aggregate_by_pose(observations + [observations[0]], config)


def test_unknown_pose_and_mixed_trials_are_rejected(config):
    observation = packets("D", "P1", -60)[0]
    with pytest.raises(ValueError, match="requires pose_id"):
        aggregate_by_pose([replace(observation, pose_id=None)], config)
    with pytest.raises(ValueError, match="mixed trial"):
        aggregate_by_pose([observation, replace(observation, trial_id="other")], config)


@pytest.mark.parametrize("updates", [
    {"rssi_dbm": float("nan")}, {"rssi_dbm": float("inf")}, {"rssi_dbm": -121},
    {"rssi_dbm": 1}, {"rssi_dbm": True}, {"sample_index": True},
    {"sample_index": -1}, {"channel": 15}, {"channel": 0}, {"channel": True},
    {"device_time_ms": -1}, {"device_id": ""}, {"pose_id": ""},
    {"csi_magnitudes": [1, -1]}, {"csi_magnitudes": [True]}, {"csi_magnitudes": []},
    {"host_time_utc": "2026-11-09T12:00:00"}, {"host_time_utc": "2026-11-09T12:00:00-05:00"},
])
def test_observation_schema_rejects_invalid_values(updates):
    record = asdict(packets("D", "P1", -60)[0])
    record.update(updates)
    with pytest.raises(ValueError):
        Observation(**record)


def test_jsonl_errors_identify_source_line_and_do_not_accept_truth_fields(tmp_path):
    path = tmp_path / "observations.jsonl"
    record = asdict(packets("D", "P1", -60)[0])
    record["group_id"] = "not-an-inference-field"
    path.write_text("\n" + json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_observations(path)


def test_manifest_parsers_reject_duplicates_and_wrong_shapes(tmp_path):
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps([{"trial_id": "test", "device_id": "D"}] * 2), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate manifest key"):
        load_devices(devices)
    poses = tmp_path / "poses.json"
    poses.write_text(json.dumps([
        {"trial_id": "test", "pose_id": "A", "pose_index": 1},
        {"trial_id": "test", "pose_id": "B", "pose_index": 1},
    ]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate pose_index"):
        load_poses(poses)
    devices.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="array"):
        load_devices(devices)


@pytest.mark.parametrize("section,key,value", [
    ("rssi", "relative_bin_thresholds_db", [0, 0]),
    ("rssi", "relative_bin_thresholds_db", [1, -1]),
    ("rssi", "relative_bin_thresholds_db", [float("nan")]),
    ("rssi", "min_packets_per_device_pose", 0),
    ("rssi", "min_poses_per_device", True),
    ("rssi", "min_shared_poses", 1),
    ("rwr", "restart_probability", 0),
    ("rwr", "tolerance", 0),
    ("grouping", "max_devices_per_group", 1),
    ("capture", "expected_channel", 15),
])
def test_invalid_configuration_is_rejected_before_aggregation(config, section, key, value):
    bad = deepcopy(config)
    bad[section][key] = value
    with pytest.raises(ValueError):
        validate_config(bad)
