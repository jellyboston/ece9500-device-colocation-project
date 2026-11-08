"""Aggregate packets and encode shared, position-indexed relative RSSI states."""

from bisect import bisect_right
from collections import Counter, defaultdict
from statistics import fmean, median

from .config import validate_config
from .models import Observation, PoseRSSI, StateEdge


def aggregate_by_pose(observations: list[Observation], config: dict) -> tuple[list[PoseRSSI], dict]:
    validate_config(config)
    trial_ids = {row.trial_id for row in observations}
    if len(trial_ids) > 1:
        raise ValueError("infer accepts one trial at a time; mixed trial IDs are not allowed")
    packets: dict[tuple, list[float]] = defaultdict(list)
    keys = set()
    for row in observations:
        key = row.trial_id, row.receiver_id, row.sample_index
        if key in keys:
            raise ValueError(f"duplicate observation key: {key}")
        keys.add(key)
        if row.pose_id is None:
            raise ValueError("spatial inference requires pose_id on every observation; use ingest-capture with events")
        packets[row.trial_id, row.device_id, row.receiver_id, row.pose_id].append(row.rssi_dbm)

    settings = config["rssi"]
    retained = {
        key: (median(values), len(values))
        for key, values in packets.items()
        if len(values) >= settings["min_packets_per_device_pose"]
    }
    medians_by_device = defaultdict(list)
    poses_by_device = defaultdict(set)
    for (trial, device, receiver, pose), (value, _) in retained.items():
        medians_by_device[device].append(value)
        poses_by_device[device].add((receiver, pose))
    devices = sorted({row.device_id for row in observations})
    low_coverage = [device for device in devices if len(poses_by_device[device]) < settings["min_poses_per_device"]]
    low_set = set(low_coverage)
    rows = [
        PoseRSSI(
            trial_id=trial, device_id=device, receiver_id=receiver, pose_id=pose,
            rssi_median_dbm=value, packet_count=count,
            rssi_relative_db=value - fmean(medians_by_device[device]),
            eligible=device not in low_set,
        )
        for (trial, device, receiver, pose), (value, count) in sorted(retained.items())
    ]
    per_device = {
        device: {
            "packet_count": sum(row.device_id == device for row in observations),
            "retained_pose_count": len(poses_by_device[device]),
            "eligible": device not in low_set,
        }
        for device in devices
    }
    report = {
        "total_rows": len(observations),
        "aggregate_cell_count": len(packets),
        "retained_cell_count": len(retained),
        "dropped_weak_cell_count": len(packets) - len(retained),
        "dropped_weak_packet_count": sum(len(values) for key, values in packets.items() if key not in retained),
        "per_device": per_device,
        "per_pose_packet_counts": dict(sorted(Counter(row.pose_id for row in observations).items())),
        "low_coverage_devices": low_coverage,
        "warnings": [f"Low-coverage device {device}: emitted as a singleton" for device in low_coverage],
    }
    return rows, report


def encode_rssi_states(pose_rssi: list[PoseRSSI], config: dict) -> list[StateEdge]:
    validate_config(config)
    thresholds = config["rssi"]["relative_bin_thresholds_db"]
    cap = config["rssi"]["max_packets_weight"]
    edges = [
        StateEdge(
            trial_id=row.trial_id, device_id=row.device_id,
            receiver_id=row.receiver_id, pose_id=row.pose_id,
            bin_index=bisect_right(thresholds, row.rssi_relative_db),
            weight=float(min(row.packet_count, cap)),
        )
        for row in pose_rssi if row.eligible
    ]
    return sorted(edges, key=lambda row: (row.trial_id, row.device_id, row.receiver_id, row.pose_id, row.bin_index))
