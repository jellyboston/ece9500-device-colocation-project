"""Seeded toy propagation model, used to test software rather than RF accuracy."""

from math import log10

import numpy as np

from .config import validate_config
from .models import Device, Observation, Pose, Truth, finite, identifier, integer


def generate_synthetic(
    config: dict, seed: int
) -> tuple[list[Observation], list[Device], list[Pose], list[Truth]]:
    """Generate packets and manifests; return truth separately for evaluation.

    Receiver positions follow a one-dimensional path. Transmitters have uniform
    independent offsets within ``group_spread_m`` of their group center, normal
    persistent power offsets, normal group/pose environmental effects, and normal
    packet noise. The reference RSSI is measured at 1 m in this illustrative model.
    Measurements outside the canonical [-120, 0] dBm range cause a clear error;
    generated measurements are never silently clipped or adjusted after inference.
    """
    validate_config(config, synthetic=True)
    integer(seed, "seed")
    settings = config["synthetic"]
    reference = settings.get("reference_rssi_dbm", -40.0)
    shared_sd = settings.get("shared_environment_sd_db", 1.0)
    finite(reference, "reference_rssi_dbm")
    finite(shared_sd, "shared_environment_sd_db")
    if not -120 <= reference <= 0:
        raise ValueError("reference_rssi_dbm must be between -120 and 0 dBm")
    if shared_sd < 0:
        raise ValueError("shared_environment_sd_db must be nonnegative")
    trial_id = settings.get("trial_id", "synth001")
    identifier(trial_id, "trial_id")
    sizes = settings["group_sizes"]
    count = sum(sizes)
    device_ids = settings.get("device_ids", [f"D{index + 1:03d}" for index in range(count)])
    num_poses = settings["num_poses"]
    packets = settings["packets_per_device_pose"]
    rng = np.random.default_rng(seed)

    group_indices = np.repeat(np.arange(len(sizes)), sizes)
    centers = np.asarray(settings["group_center_x_m"], dtype=float)
    device_x = centers[group_indices] + rng.uniform(
        -settings["group_spread_m"], settings["group_spread_m"], count
    )
    power_offsets = rng.normal(0.0, settings["tx_power_offset_sd_db"], count)
    shared_effects = rng.normal(0.0, shared_sd, (num_poses, len(sizes)))
    noise = rng.normal(0.0, settings["noise_sd_db"], (num_poses, count, packets))
    missing = rng.random((num_poses, count, packets)) < settings["missing_observation_probability"]

    devices = [Device(trial_id=trial_id, device_id=device_id) for device_id in device_ids]
    truth = [
        Truth(trial_id=trial_id, device_id=device_id, group_id=f"G{group + 1}")
        for device_id, group in zip(device_ids, group_indices.tolist())
    ]
    # These are explicitly simulated receiver-clock windows, not measured time.
    duration_ms = max(1000, count * packets + 1)
    poses = [
        Pose(
            trial_id=trial_id,
            pose_id=f"P{index + 1:02d}",
            pose_index=index + 1,
            x_m=float(index * settings["pose_spacing_m"]),
            y_m=0.0,
            capture_start_ms=index * (duration_ms + 250),
            capture_end_ms=index * (duration_ms + 250) + duration_ms,
        )
        for index in range(num_poses)
    ]
    observations = []
    for pose_index, pose in enumerate(poses):
        for device_index, device_id in enumerate(device_ids):
            distance_m = max(abs(float(device_x[device_index]) - pose.x_m), 0.5)
            pose_rssi = (
                reference + power_offsets[device_index]
                - 10 * settings["path_loss_exponent"] * log10(distance_m)
                + shared_effects[pose_index, group_indices[device_index]]
            )
            for packet in range(packets):
                if missing[pose_index, device_index, packet]:
                    continue
                rssi = float(pose_rssi + noise[pose_index, device_index, packet])
                if not -120 <= rssi <= 0:
                    raise ValueError(
                        f"synthetic config/seed generated RSSI {rssi:.3f} dBm outside [-120, 0] "
                        f"at device {device_id}, pose {pose.pose_id}; revise the documented "
                        "reference/noise/power/geometry settings; samples are not clipped"
                    )
                observations.append(
                    Observation(
                        trial_id=trial_id,
                        receiver_id="RX1",
                        sample_index=len(observations),
                        device_id=device_id,
                        pose_id=pose.pose_id,
                        device_time_ms=pose.capture_start_ms + device_index * packets + packet,
                        rssi_dbm=rssi,
                        channel=6,
                    )
                )
    return observations, devices, poses, truth
