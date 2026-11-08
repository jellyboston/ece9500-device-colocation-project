import json
from dataclasses import asdict
from pathlib import Path

import pytest

from colocation.synthetic import generate_synthetic


CONFIG = Path(__file__).resolve().parents[1] / "config" / "report1.json"


def default_config():
    return json.loads(CONFIG.read_text())


def test_seed_repeats_packets_manifests_and_truth():
    config = default_config()
    first = generate_synthetic(config, 9500)
    assert first == generate_synthetic(config, 9500)
    assert first != generate_synthetic(config, 9501)
    observations, devices, poses, truth = first
    assert len(observations) == 400
    assert len(devices) == len(truth) == 4
    assert len(poses) == 10
    assert [row.sample_index for row in observations] == list(range(400))
    assert [row.device_time_ms for row in observations] == sorted(row.device_time_ms for row in observations)
    assert all("group_id" not in asdict(row) for row in observations)
    assert all(row.csi_magnitudes is None for row in observations)


def test_generic_ids_and_manifest_preserved_with_zero_samples():
    config = default_config()
    del config["synthetic"]["device_ids"]
    config["synthetic"]["group_sizes"] = [3, 1, 2]
    config["synthetic"]["group_center_x_m"] = [1, 4, 8]
    config["synthetic"]["missing_observation_probability"] = 1 - 1e-12
    observations, devices, poses, truth = generate_synthetic(config, 9500)
    assert observations == []
    assert len(devices) == len(truth) == 6
    assert len(poses) == 10
    assert len({row.device_id for row in devices}) == 6
    assert {row.group_id for row in truth} == {"G1", "G2", "G3"}


def test_observations_have_explicit_simulated_capture_windows():
    observations, _, poses, _ = generate_synthetic(default_config(), 9500)
    by_id = {pose.pose_id: pose for pose in poses}
    for observation in observations:
        pose = by_id[observation.pose_id]
        assert pose.capture_start_ms <= observation.device_time_ms < pose.capture_end_ms
        assert observation.host_time_utc is None


@pytest.mark.parametrize("seed", [-1, True, 1.5])
def test_invalid_seed(seed):
    with pytest.raises(ValueError, match="seed"):
        generate_synthetic(default_config(), seed)


@pytest.mark.parametrize(
    "field,value",
    [("reference_rssi_dbm", float("nan")), ("shared_environment_sd_db", -1)],
)
def test_new_model_parameters_are_validated(field, value):
    config = default_config()
    config["synthetic"][field] = value
    with pytest.raises(ValueError, match=field):
        generate_synthetic(config, 9500)


def test_out_of_range_simulation_does_not_silently_clip():
    config = default_config()
    config["synthetic"]["reference_rssi_dbm"] = 0
    config["synthetic"]["noise_sd_db"] = 0
    config["synthetic"]["tx_power_offset_sd_db"] = 0
    config["synthetic"]["shared_environment_sd_db"] = 0
    with pytest.raises(ValueError, match="outside.*samples are not clipped"):
        generate_synthetic(config, 9500)
