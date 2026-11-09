"""Load JSON experiment configuration and reject invalid settings early."""

import json
from pathlib import Path

from .models import channel_number, finite, identifier, integer


def validate_config(config: dict, *, synthetic: bool = False) -> dict:
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")
    try:
        rssi, rwr, grouping, capture = (config[key] for key in ("rssi", "rwr", "grouping", "capture"))
        if not all(isinstance(section, dict) for section in (rssi, rwr, grouping, capture)):
            raise ValueError("configuration sections must be JSON objects")
        bins = rssi["relative_bin_thresholds_db"]
        if not isinstance(bins, list):
            raise ValueError("relative_bin_thresholds_db must be a list")
        for threshold in bins:
            finite(threshold, "relative_bin_thresholds_db")
        if any(left >= right for left, right in zip(bins, bins[1:])):
            raise ValueError("relative_bin_thresholds_db must be strictly increasing")
        for name in ("max_packets_weight", "min_packets_per_device_pose", "min_poses_per_device", "min_shared_poses"):
            integer(rssi[name], f"rssi.{name}", 1)
        if rssi["min_shared_poses"] < 2:
            raise ValueError("min_shared_poses must be >= 2 for Pearson correlation")
        finite(rwr["restart_probability"], "restart_probability")
        if not 0 < rwr["restart_probability"] <= 1:
            raise ValueError("restart_probability must be in (0, 1]")
        finite(rwr["tolerance"], "tolerance")
        if rwr["tolerance"] <= 0:
            raise ValueError("tolerance must be positive")
        integer(rwr["max_iterations"], "max_iterations", 1)
        integer(grouping["max_devices_per_group"], "max_devices_per_group", 2)
        finite(grouping["min_directional_similarity"], "min_directional_similarity")
        if not 0 <= grouping["min_directional_similarity"] <= 1:
            raise ValueError("min_directional_similarity must be between 0 and 1")
        channel_number(capture["expected_channel"])
        if synthetic:
            _validate_synthetic(config["synthetic"])
    except KeyError as exc:
        raise ValueError(f"missing configuration setting: {exc.args[0]}") from exc
    return config


def _validate_synthetic(settings: dict) -> None:
    if not isinstance(settings, dict):
        raise ValueError("synthetic configuration must be an object")
    sizes = settings["group_sizes"]
    if not isinstance(sizes, list) or not sizes:
        raise ValueError("synthetic.group_sizes must be a nonempty list")
    for size in sizes:
        integer(size, "group size", 1)
    if "device_ids" in settings:
        ids = settings["device_ids"]
        if not isinstance(ids, list) or len(ids) != sum(sizes):
            raise ValueError("synthetic.device_ids must match sum(group_sizes); omit it for generated IDs")
        for device_id in ids:
            identifier(device_id, "device_id")
        if len(set(ids)) != len(ids):
            raise ValueError("synthetic.device_ids must be unique")
    centers = settings["group_center_x_m"]
    if not isinstance(centers, list) or len(centers) != len(sizes):
        raise ValueError("synthetic.group_center_x_m must contain one center per group")
    for value in centers:
        finite(value, "group_center_x_m")
    integer(settings["num_poses"], "num_poses", 3)
    integer(settings["packets_per_device_pose"], "packets_per_device_pose", 1)
    for name in ("pose_spacing_m", "path_loss_exponent"):
        finite(settings[name], name)
        if settings[name] <= 0:
            raise ValueError(f"synthetic.{name} must be positive")
    for name in ("group_spread_m", "tx_power_offset_sd_db", "noise_sd_db", "shared_environment_sd_db"):
        finite(settings[name], name)
        if settings[name] < 0:
            raise ValueError(f"synthetic.{name} must be nonnegative")
    finite(settings["reference_rssi_dbm"], "reference_rssi_dbm")
    if not -120 <= settings["reference_rssi_dbm"] <= 0:
        raise ValueError("synthetic.reference_rssi_dbm must be between -120 and 0")
    if "trial_id" in settings:
        identifier(settings["trial_id"], "synthetic.trial_id")
    probability = settings["missing_observation_probability"]
    finite(probability, "missing_observation_probability")
    if not 0 <= probability < 1:
        raise ValueError("missing_observation_probability must be in [0, 1)")


def load_config(path: str | Path, *, synthetic: bool = False) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        config = json.load(stream)
    return validate_config(config, synthetic=synthetic)
