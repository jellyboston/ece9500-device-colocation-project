"""Strict adapters for one receiver's explicitly positioned controlled capture."""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
import csv
import json
from pathlib import Path
from typing import Iterable

from .ingest import _channel, _identifier, _integer, _load_csi_samples, _magnitudes, _number, _rssi
from .models import PHASES, CaptureWindow, Observation, Pose, PositionEvent, RawSample


def _read_table(
    path: str | Path,
    required: set[str],
    *,
    optional: set[str] | None = None,
) -> Iterable[tuple[int, dict[str, str]]]:
    optional = optional or set()
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, strict=True)
        try:
            header = reader.fieldnames
            if (
                header is None
                or len(header) != len(set(header))
                or not required.issubset(header)
                or set(header) - required - optional
            ):
                suffix = f"; optional columns: {', '.join(sorted(optional))}" if optional else ""
                raise ValueError(f"invalid CSV header; required columns: {', '.join(sorted(required))}{suffix}")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"CSV line {reader.line_num}: row does not match the header column count")
                yield reader.line_num, row
        except csv.Error as exc:
            raise ValueError(f"CSV line {reader.line_num}: malformed CSV") from exc


def parse_capture_samples(
    path: str | Path,
    format: str,
    *,
    device_id: str | None = None,
    single_known_transmitter: bool = False,
) -> list[RawSample]:
    """Parse source samples, assigning 0-based indices in sample input order."""
    if format == "csi-legacy":
        if not single_known_transmitter or device_id is None:
            raise ValueError("csi-legacy requires both --single-known-transmitter and --device-id for a verified single TX")
        return _load_csi_samples(path, device_id)
    if format != "observed-csv":
        raise ValueError("unknown input format; use csi-legacy or observed-csv")
    if device_id is not None or single_known_transmitter:
        raise ValueError("observed-csv requires device_id on every row; omit the global --device-id and --single-known-transmitter")
    samples: list[RawSample] = []
    previous_time = -1
    for line_number, row in _read_table(
        path,
        {"device_time_ms", "device_id", "rssi_dbm", "channel"},
        optional={"csi_magnitudes_json"},
    ):
        try:
            magnitudes = None
            if row.get("csi_magnitudes_json", "").strip():
                try:
                    value = json.loads(row["csi_magnitudes_json"])
                except json.JSONDecodeError as exc:
                    raise ValueError("csi_magnitudes_json must contain a JSON array") from exc
                magnitudes = _magnitudes(value)
            timestamp = _integer(row["device_time_ms"], "device_time_ms")
            if timestamp < previous_time:
                raise ValueError("device_time_ms decreased: possible receiver clock reset/wrap; split the trial explicitly")
            samples.append(RawSample(
                sample_index=len(samples),
                device_time_ms=timestamp,
                device_id=_identifier(row["device_id"], "device_id"),
                rssi_dbm=_rssi(row["rssi_dbm"]),
                channel=_channel(row["channel"]),
                csi_magnitudes=magnitudes,
            ))
            previous_time = timestamp
        except ValueError as exc:
            raise ValueError(f"sample CSV line {line_number}: {exc}") from exc
    if not samples:
        raise ValueError("sample CSV contains no sample rows")
    return samples


def load_pose_manifest(path: str | Path, trial_id: str) -> list[Pose]:
    trial_id = _identifier(trial_id, "trial_id")
    poses: list[Pose] = []
    ids: set[str] = set()
    indices: set[int] = set()
    for line_number, row in _read_table(path, {"pose_id", "pose_index", "x_m", "y_m"}):
        try:
            pose_id = _identifier(row["pose_id"], "pose_id")
            index = _integer(row["pose_index"], "pose_index")
            if pose_id in ids:
                raise ValueError("duplicate pose_id in pose manifest")
            if index in indices:
                raise ValueError("duplicate pose_index in pose manifest")
            poses.append(Pose(
                trial_id=trial_id,
                pose_id=pose_id,
                pose_index=index,
                x_m=_number(row["x_m"], "x_m") if row["x_m"].strip() else None,
                y_m=_number(row["y_m"], "y_m") if row["y_m"].strip() else None,
            ))
            ids.add(pose_id)
            indices.add(index)
        except ValueError as exc:
            raise ValueError(f"pose manifest line {line_number}: {exc}") from exc
    if not poses:
        raise ValueError("pose manifest must contain at least one explicitly measured pose")
    return sorted(poses, key=lambda pose: pose.pose_index)


def load_pose_events(
    path: str | Path,
    *,
    trial_id: str = "capture001",
    receiver_id: str = "RX1",
) -> list[PositionEvent]:
    trial_id = _identifier(trial_id, "trial_id")
    receiver_id = _identifier(receiver_id, "receiver_id")
    events: list[PositionEvent] = []
    previous_index = -1
    previous_time = -1
    for line_number, row in _read_table(path, {"event_index", "device_time_ms", "pose_id", "phase"}):
        try:
            index = _integer(row["event_index"], "event_index")
            timestamp = _integer(row["device_time_ms"], "device_time_ms")
            if index <= previous_index:
                raise ValueError("event_index must be unique and strictly increasing in declared event order")
            if timestamp < previous_time:
                raise ValueError("event device_time_ms decreased: possible receiver clock reset/wrap")
            phase = row["phase"]
            if phase not in PHASES:
                raise ValueError("unknown phase; expected CAPTURE_START, CAPTURE_END, MOVE_START, MOVE_END or SETTLE_START")
            events.append(PositionEvent(
                trial_id=trial_id,
                receiver_id=receiver_id,
                event_index=index,
                device_time_ms=timestamp,
                pose_id=_identifier(row["pose_id"], "pose_id"),
                phase=phase,
            ))
            previous_index, previous_time = index, timestamp
        except ValueError as exc:
            raise ValueError(f"pose event line {line_number}: {exc}") from exc
    if not events:
        raise ValueError("pose event file must contain explicit CAPTURE_START/CAPTURE_END events")
    return events


def build_capture_windows(events: list[PositionEvent], poses: list[Pose]) -> list[CaptureWindow]:
    if not poses:
        raise ValueError("a nonempty explicit pose manifest is required")
    if len({pose.pose_id for pose in poses}) != len(poses) or len({pose.pose_index for pose in poses}) != len(poses):
        raise ValueError("pose manifest requires unique pose_id and pose_index values")
    pose_trials = {pose.trial_id for pose in poses}
    if len(pose_trials) != 1:
        raise ValueError("pose manifest must contain exactly one trial_id")
    if not events:
        raise ValueError("no pose events; explicit capture windows are required")
    if len({(event.trial_id, event.receiver_id) for event in events}) != 1:
        raise ValueError("events must belong to one trial and receiver clock")
    if {event.trial_id for event in events} != pose_trials:
        raise ValueError("pose manifest and events have mismatched trial IDs")
    known_poses = {pose.pose_id for pose in poses}
    previous_index = -1
    previous_time = -1
    active: PositionEvent | None = None
    windows: list[CaptureWindow] = []
    for event in events:
        index = _integer(event.event_index, "event_index")
        timestamp = _integer(event.device_time_ms, "event device_time_ms")
        if index <= previous_index:
            raise ValueError("event_index must be unique and strictly increasing in declared event order")
        if timestamp < previous_time:
            raise ValueError("event device_time_ms decreased: possible receiver clock reset/wrap")
        if event.pose_id not in known_poses:
            raise ValueError(f"event references unknown pose_id {event.pose_id!r}; supply it in the pose manifest")
        if event.phase not in PHASES:
            raise ValueError("unknown pose event phase")
        if event.phase == "CAPTURE_START":
            if active is not None:
                raise ValueError("overlapping capture windows: CAPTURE_START before the previous CAPTURE_END")
            active = event
        elif event.phase == "CAPTURE_END":
            if active is None:
                raise ValueError("unpaired CAPTURE_END without CAPTURE_START")
            if active.pose_id != event.pose_id:
                raise ValueError("CAPTURE_END pose_id does not match its CAPTURE_START")
            if timestamp <= active.device_time_ms:
                raise ValueError("capture window must have positive duration")
            windows.append(CaptureWindow(pose_id=event.pose_id, start_ms=active.device_time_ms, end_ms=timestamp))
            active = None
        elif active is not None:
            raise ValueError("movement/settling event inside an open capture window; emit CAPTURE_END before moving")
        previous_index, previous_time = index, timestamp
    if active is not None:
        raise ValueError("unpaired CAPTURE_START: missing CAPTURE_END")
    if not windows:
        raise ValueError("no complete CAPTURE_START/CAPTURE_END windows")
    return windows


def ingest_capture(
    samples: list[RawSample],
    events: list[PositionEvent],
    poses: list[Pose],
    trial_id: str,
    receiver_id: str,
    config: dict,
    *,
    source_file: str | Path | None = None,
) -> tuple[list[Observation], dict]:
    """Join only samples in complete stationary ``[start,end)`` windows.

    This checks the ordering and consistency available in the input schemas.
    Independent clock/session provenance must be supplied by the capture setup;
    coincident integer uptimes alone do not establish clock identity.
    """
    trial_id = _identifier(trial_id, "trial_id")
    receiver_id = _identifier(receiver_id, "receiver_id")
    if not samples:
        raise ValueError("capture contains no sample rows")
    if any(event.trial_id != trial_id or event.receiver_id != receiver_id for event in events):
        raise ValueError("event trial/receiver metadata does not match the requested capture clock")
    if any(pose.trial_id != trial_id for pose in poses):
        raise ValueError("pose manifest trial_id does not match the requested capture")
    windows = build_capture_windows(events, poses)
    expected_channel = config.get("capture", {}).get("expected_channel")
    if expected_channel is not None:
        expected_channel = _channel(expected_channel)
    previous_time = -1
    sample_indices: set[int] = set()
    for sample in samples:
        timestamp = _integer(sample.device_time_ms, "sample device_time_ms")
        sample_index = _integer(sample.sample_index, "sample_index")
        if timestamp < previous_time:
            raise ValueError("sample device_time_ms decreased: possible receiver clock reset/wrap; split the trial explicitly")
        if sample_index in sample_indices:
            raise ValueError("duplicate sample_index in capture")
        _identifier(sample.device_id, "device_id")
        _rssi(sample.rssi_dbm)
        if sample.channel is not None:
            _channel(sample.channel)
        if expected_channel is not None and sample.channel != expected_channel:
            raise ValueError(f"sample_index {sample_index}: channel mismatch; expected configured channel {expected_channel}")
        if sample.csi_magnitudes is not None:
            _magnitudes(sample.csi_magnitudes)
        sample_indices.add(sample_index)
        previous_time = timestamp
    starts = [window.start_ms for window in windows]
    event_times = [event.device_time_ms for event in events]
    counts: Counter[str] = Counter()
    all_devices = sorted({sample.device_id for sample in samples})
    per_pose_counts = {pose.pose_id: 0 for pose in poses}
    per_device_pose_counts = {device: {pose.pose_id: 0 for pose in poses} for device in all_devices}
    observations: list[Observation] = []
    for sample in samples:
        index = bisect_right(starts, sample.device_time_ms) - 1
        window = windows[index] if index >= 0 else None
        if window is None or not window.start_ms <= sample.device_time_ms < window.end_ms:
            event_index = bisect_right(event_times, sample.device_time_ms) - 1
            phase = events[event_index].phase if event_index >= 0 else None
            reason = "movement" if phase == "MOVE_START" else "settling" if phase in {"MOVE_END", "SETTLE_START"} else "outside_capture_window"
            counts[reason] += 1
            continue
        observations.append(Observation(
            trial_id=trial_id,
            receiver_id=receiver_id,
            sample_index=sample.sample_index,
            device_id=sample.device_id,
            pose_id=window.pose_id,
            device_time_ms=sample.device_time_ms,
            rssi_dbm=sample.rssi_dbm,
            channel=sample.channel,
            csi_magnitudes=sample.csi_magnitudes,
        ))
        per_pose_counts[window.pose_id] += 1
        per_device_pose_counts[sample.device_id][window.pose_id] += 1
    if not observations:
        raise ValueError("no samples fall inside complete capture windows; check same-receiver uptime clock/session and event timestamps")
    rssi_config = config.get("rssi", {})
    minimum_packets = _integer(rssi_config.get("min_packets_per_device_pose", 3), "min_packets_per_device_pose", minimum=1)
    minimum_poses = _integer(rssi_config.get("min_poses_per_device", 3), "min_poses_per_device", minimum=1)
    coverage = {}
    warnings: list[str] = [
        "Samples and pose events must come from the same ESP32 recording; "
        "matching uptime ranges cannot independently prove clock/session provenance."
    ]
    for device_id in all_devices:
        device_counts = per_device_pose_counts[device_id]
        retained = sum(count >= minimum_packets for count in device_counts.values())
        coverage[device_id] = {"usable_pose_count": retained, "low_coverage": retained < minimum_poses}
        if retained < minimum_poses:
            warnings.append(f"{device_id}: only {retained} usable poses; needs {minimum_poses}; inference will retain a low-coverage singleton")
        if any(count < minimum_packets for count in device_counts.values()):
            warnings.append(f"{device_id}: incomplete or sparse device-by-pose coverage")
    if len(all_devices) < 2:
        warnings.append("one attributed transmitter: useful for an RSSI trajectory, insufficient evidence to evaluate colocation grouping")
    report = {
        "trial_id": trial_id,
        "receiver_id": receiver_id,
        "source_file": str(source_file) if source_file is not None else None,
        "total_rows": len(samples),
        "accepted_rows": len(observations),
        "excluded_rows": len(samples) - len(observations),
        "counts_by_reason": dict(sorted(counts.items())),
        "per_pose_counts": per_pose_counts,
        "per_device_pose_counts": per_device_pose_counts,
        "all_device_ids": all_devices,
        "coverage": coverage,
        "warnings": warnings,
        "clock_provenance": {
            "requirement": "samples and events from the same ESP32 recording",
            "independently_verified": False,
            "checks": ["nondecreasing sample/event uptime", "single receiver metadata", "complete stationary windows"],
        },
        "capture_windows": [
            {"pose_id": window.pose_id, "start_ms": window.start_ms, "end_ms": window.end_ms}
            for window in windows
        ],
    }
    return observations, report
