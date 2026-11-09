"""Controlled capture joins, exclusion accounting, and metadata failure paths."""

from dataclasses import replace
from pathlib import Path

import pytest

from colocation.capture import (
    build_capture_windows,
    ingest_capture,
    load_pose_events,
    load_pose_manifest,
    parse_capture_samples,
)
from colocation.models import Pose, PositionEvent, RawSample


CONFIG = {
    "capture": {"expected_channel": 6},
    "rssi": {"min_packets_per_device_pose": 3, "min_poses_per_device": 3},
}


def poses():
    return [Pose(trial_id="trial", pose_id=f"P{index}", pose_index=index) for index in (1, 2)]


def events():
    entries = [
        (10, "P1", "CAPTURE_START"),
        (20, "P1", "CAPTURE_END"),
        (21, "P1", "MOVE_START"),
        (28, "P2", "MOVE_END"),
        (29, "P2", "SETTLE_START"),
        (30, "P2", "CAPTURE_START"),
        (40, "P2", "CAPTURE_END"),
    ]
    return [PositionEvent(trial_id="trial", receiver_id="RX1", event_index=index,
                          device_time_ms=time, pose_id=pose, phase=phase)
            for index, (time, pose, phase) in enumerate(entries)]


def samples(times, ids=None):
    ids = ids or ["tx"] * len(times)
    return [RawSample(sample_index=index, device_time_ms=time, device_id=device,
                      rssi_dbm=-42.0, channel=6)
            for index, (time, device) in enumerate(zip(times, ids, strict=True))]


def test_capture_join_uses_half_open_windows_and_counts_movement_and_settling():
    raw = samples([9, 10, 19, 20, 21, 28, 29, 30, 39, 40])
    observations, report = ingest_capture(raw, events(), poses(), "trial", "RX1", CONFIG, source_file="capture.csv")
    assert [(row.device_time_ms, row.pose_id) for row in observations] == [(10, "P1"), (19, "P1"), (30, "P2"), (39, "P2")]
    assert [row.sample_index for row in observations] == [1, 2, 7, 8]
    assert all(row.trial_id == "trial" and row.receiver_id == "RX1" for row in observations)
    assert report["total_rows"] == 10
    assert report["accepted_rows"] == 4
    assert report["excluded_rows"] == 6
    assert report["counts_by_reason"] == {"outside_capture_window": 3, "movement": 1, "settling": 2}
    assert report["per_pose_counts"] == {"P1": 2, "P2": 2}
    assert report["source_file"] == "capture.csv"
    assert report["clock_provenance"]["independently_verified"] is False


def test_movement_only_device_is_preserved_for_manifest_and_singleton_warning():
    observations, report = ingest_capture(samples([10, 22, 31], ["good", "movement-only", "good"]),
                                           events(), poses(), "trial", "RX1", CONFIG)
    assert {row.device_id for row in observations} == {"good"}
    assert report["all_device_ids"] == ["good", "movement-only"]
    assert report["coverage"]["movement-only"] == {"usable_pose_count": 0, "low_coverage": True}
    assert report["per_device_pose_counts"]["movement-only"] == {"P1": 0, "P2": 0}


def test_real_schema_files_preserve_unknown_coordinates_and_csi_magnitudes(tmp_path):
    capture = tmp_path / "capture.csv"
    capture.write_text("CSI,10,-42,6,3,0,12,15,14\nCSI,30,-43,6,3,0,13,15,15\n")
    manifest = tmp_path / "poses.csv"
    manifest.write_text("pose_id,pose_index,x_m,y_m\nP1,1,,\nP2,2,1.0,0.0\n")
    event_file = tmp_path / "events.csv"
    event_file.write_text("event_index,device_time_ms,pose_id,phase\n0,10,P1,CAPTURE_START\n1,20,P1,CAPTURE_END\n2,30,P2,CAPTURE_START\n3,40,P2,CAPTURE_END\n")
    parsed_samples = parse_capture_samples(capture, "csi-legacy", device_id="T1", single_known_transmitter=True)
    parsed_events = load_pose_events(event_file, trial_id="trial", receiver_id="RX1")
    parsed_poses = load_pose_manifest(manifest, "trial")
    rows, report = ingest_capture(parsed_samples, parsed_events, parsed_poses, "trial", "RX1", CONFIG)
    assert len(rows) == 2
    assert rows[0].csi_magnitudes == [12, 15, 14]
    assert parsed_poses[0].x_m is None and parsed_poses[0].y_m is None
    assert parsed_poses[1].x_m == 1
    assert any("one attributed transmitter" in warning for warning in report["warnings"])


def test_observed_csv_reads_per_sample_identity_and_optional_magnitudes(tmp_path):
    capture = tmp_path / "capture.csv"
    capture.write_text('device_time_ms,device_id,rssi_dbm,channel,csi_magnitudes_json\n10,A,-42,6,"[12, 15]"\n10,B,-43,6,\n')
    parsed = parse_capture_samples(capture, "observed-csv")
    assert [row.device_id for row in parsed] == ["A", "B"]
    assert parsed[0].csi_magnitudes == [12, 15]
    assert parsed[1].csi_magnitudes is None


@pytest.mark.parametrize("kwargs", [{}, {"device_id": "T1"}, {"single_known_transmitter": True}])
def test_legacy_capture_requires_both_explicit_identity_assertions(tmp_path, kwargs):
    with pytest.raises(ValueError, match="requires both"):
        parse_capture_samples(tmp_path / "unused.csv", "csi-legacy", **kwargs)


@pytest.mark.parametrize("kwargs", [{"device_id": "T1"}, {"single_known_transmitter": True}])
def test_observed_csv_prohibits_global_identity(tmp_path, kwargs):
    with pytest.raises(ValueError, match="every row"):
        parse_capture_samples(tmp_path / "unused.csv", "observed-csv", **kwargs)


def test_unknown_input_format_errors_before_file_access(tmp_path):
    with pytest.raises(ValueError, match="unknown input format"):
        parse_capture_samples(tmp_path / "unused.csv", "unknown")


@pytest.mark.parametrize(
    "content",
    ["device_time_ms,rssi_dbm,channel\n10,-42,6\n",
     "device_time_ms,device_id,rssi_dbm,channel,extra\n10,A,-42,6,x\n",
     "device_time_ms,device_id,rssi_dbm,channel,channel\n10,A,-42,6,6\n",
     "device_time_ms,device_id,rssi_dbm,channel\n10,,-42,6\n",
     "device_time_ms,device_id,rssi_dbm,channel\n10,A,-42\n",
     "device_time_ms,device_id,rssi_dbm,channel\n10,A,-42,6,extra\n",
     "device_time_ms,device_id,rssi_dbm,channel\n10.0,A,-42,6\n",
     "device_time_ms,device_id,rssi_dbm,channel\n-1,A,-42,6\n",
     "device_time_ms,device_id,rssi_dbm,channel\n10,A,NaN,6\n",
     "device_time_ms,device_id,rssi_dbm,channel\n10,A,1,6\n",
     "device_time_ms,device_id,rssi_dbm,channel\n10,A,-42,15\n",
     "device_time_ms,device_id,rssi_dbm,channel\n10,A,-42,6\n1,A,-42,6\n",
     'device_time_ms,device_id,rssi_dbm,channel,csi_magnitudes_json\n10,A,-42,6,"[1.0]"\n',
     'device_time_ms,device_id,rssi_dbm,channel,csi_magnitudes_json\n10,A,-42,6,"[true]"\n',
     'device_time_ms,device_id,rssi_dbm,channel,csi_magnitudes_json\n10,A,-42,6,"[]"\n'],
)
def test_observed_csv_rejects_invalid_schema_values_and_clock(tmp_path, content):
    path = tmp_path / "capture.csv"
    path.write_text(content)
    with pytest.raises(ValueError):
        parse_capture_samples(path, "observed-csv")


@pytest.mark.parametrize(
    "content",
    ["pose_id,pose_index,x_m\nP1,1,0\n", "pose_id,pose_index,x_m,y_m\nP1,1,,\nP1,2,,\n",
     "pose_id,pose_index,x_m,y_m\nP1,1,,\nP2,1,,\n", "pose_id,pose_index,x_m,y_m\n,1,,\n",
     "pose_id,pose_index,x_m,y_m\nP1,1,NaN,0\n", "pose_id,pose_index,x_m,y_m\nP1,1.0,0,0\n",
     "pose_id,pose_index,x_m,y_m\n"],
)
def test_pose_manifest_rejects_missing_or_ambiguous_positions(tmp_path, content):
    path = tmp_path / "poses.csv"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_pose_manifest(path, "trial")


@pytest.mark.parametrize(
    "rows",
    ["0,10,P1,UNKNOWN\n", "0,10,P1,CAPTURE_START\n0,20,P1,CAPTURE_END\n",
     "1,10,P1,CAPTURE_START\n0,20,P1,CAPTURE_END\n", "0,20,P1,CAPTURE_START\n1,10,P1,CAPTURE_END\n",
     "0,10.0,P1,CAPTURE_START\n", "0,10,,CAPTURE_START\n"],
)
def test_pose_events_reject_unknown_phase_indices_and_clock_resets(tmp_path, rows):
    path = tmp_path / "events.csv"
    path.write_text("event_index,device_time_ms,pose_id,phase\n" + rows)
    with pytest.raises(ValueError):
        load_pose_events(path)


@pytest.mark.parametrize("case", ["unknown_pose", "overlap", "missing_end", "missing_start", "wrong_end_pose", "zero_duration", "movement_during_capture", "mixed_receiver", "mixed_trial"])
def test_ambiguous_capture_windows_are_rejected(case):
    source = events()
    if case == "unknown_pose":
        source[0] = replace(source[0], pose_id="unlisted")
    elif case == "overlap":
        source[1] = replace(source[1], phase="CAPTURE_START")
    elif case == "missing_end":
        source = source[:-1]
    elif case == "missing_start":
        source = source[1:]
    elif case == "wrong_end_pose":
        source[1] = replace(source[1], pose_id="P2")
    elif case == "zero_duration":
        source[1] = replace(source[1], device_time_ms=10)
    elif case == "movement_during_capture":
        source[1] = replace(source[1], phase="MOVE_START")
    elif case == "mixed_receiver":
        source[1] = replace(source[1], receiver_id="RX2")
    elif case == "mixed_trial":
        source[1] = replace(source[1], trial_id="other-trial")
    with pytest.raises(ValueError):
        build_capture_windows(source, poses())


def test_capture_channel_must_match_config():
    raw = [replace(samples([10])[0], channel=1)]
    with pytest.raises(ValueError, match="channel mismatch"):
        ingest_capture(raw, events(), poses(), "trial", "RX1", CONFIG)


def test_missing_manifest_and_all_samples_outside_windows_fail_without_guessing():
    with pytest.raises(ValueError, match="manifest"):
        ingest_capture(samples([10]), events(), [], "trial", "RX1", CONFIG)
    with pytest.raises(ValueError, match="no samples fall inside"):
        ingest_capture(samples([1, 2, 3]), events(), poses(), "trial", "RX1", CONFIG)


def test_capture_reports_unambiguous_singleton_quality_instead_of_dropping_sparse_data():
    rows, report = ingest_capture(samples([10, 11, 12, 30, 31, 32]), events(), poses(), "trial", "RX1", CONFIG)
    assert len(rows) == 6
    assert report["coverage"]["tx"] == {"usable_pose_count": 2, "low_coverage": True}
    assert any("low-coverage singleton" in warning for warning in report["warnings"])
    assert report["excluded_rows"] == 0
