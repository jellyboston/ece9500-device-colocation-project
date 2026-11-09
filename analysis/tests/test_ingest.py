"""Acceptance checks for the supplied exploratory captures and strict adapters."""

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from colocation.ingest import load_csi_csv, load_wisniff


ROOT = Path(__file__).resolve().parents[2]


def test_supplied_wisniff_scan_preserves_counts_without_fabricating_metadata():
    rows = load_wisniff(ROOT / "wisniff/data/wisniff_data.json")
    assert len(rows) == 40
    assert len({row.device_id for row in rows}) == 18
    assert [row.sample_index for row in rows] == list(range(40))
    assert min(row.rssi_dbm for row in rows) == -93
    assert max(row.rssi_dbm for row in rows) == -33
    assert all(row.pose_id is None and row.device_time_ms is None and row.host_time_utc is None for row in rows)
    assert all(row.csi_magnitudes is None for row in rows)
    assert all(row.device_id.startswith("W") and ":" not in row.device_id for row in rows)
    assert "mac" not in asdict(rows[0])


def test_supplied_short_csi_capture_ignores_sentinel_and_retains_unknown_pose():
    rows = load_csi_csv(
        ROOT / "wisniff/tools/csi_COM6_1794086754_useful.csv", "singlelink001", "RX1", "T1"
    )
    assert len(rows) == 42
    assert all(len(row.csi_magnitudes) == 57 for row in rows)
    assert all(row.pose_id is None and row.host_time_utc is None for row in rows)
    assert all(row.device_id == "T1" and row.channel == 6 for row in rows)
    assert min(row.rssi_dbm for row in rows) == -40
    assert max(row.rssi_dbm for row in rows) == -36
    assert rows[0].csi_magnitudes[0] == 14
    assert rows[0].device_time_ms == 6605


def test_scan_aliases_are_stable_within_scan_and_hide_raw_source(tmp_path):
    path = tmp_path / "scan.json"
    records = [
        {"mac": "02:00:00:00:00:02", "rssi": -43, "channel": 6},
        {"mac": "02:00:00:00:00:01", "rssi": -44, "channel": 6},
        {"mac": "02:00:00:00:00:02", "rssi": -45, "channel": 6},
    ]
    path.write_text(json.dumps({"devices": records}))
    rows = load_wisniff(path)
    assert rows[0].device_id == rows[2].device_id != rows[1].device_id
    assert "02:00:" not in json.dumps([asdict(row) for row in rows])
    path.write_text(json.dumps({"devices": records[::-1]}))
    assert [row.device_id for row in load_wisniff(path)] == [row.device_id for row in rows[::-1]]


@pytest.mark.parametrize(
    ("field", "value"),
    [("rssi", float("nan")), ("rssi", float("inf")), ("rssi", -121), ("rssi", 1),
     ("rssi", True), ("rssi", "-42"), ("channel", 0), ("channel", 15),
     ("channel", 6.0), ("channel", True), ("mac", "invalid"), ("mac", None)],
)
def test_invalid_wisniff_values_are_rejected_without_echoing_identity(tmp_path, field, value):
    path = tmp_path / "scan.json"
    record = {"mac": "02:00:00:00:00:01", "rssi": -42, "channel": 6}
    record[field] = value
    path.write_text(json.dumps({"devices": [record]}))
    with pytest.raises(ValueError) as caught:
        load_wisniff(path)
    assert "02:00:00:00:00:01" not in str(caught.value)


@pytest.mark.parametrize("payload", [{}, [], {"devices": {}}, {"devices": [1]}])
def test_bad_wisniff_container_schema(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_wisniff(path)


@pytest.mark.parametrize(
    "row",
    ["CSI,10,-42,6,3,0,12,15", "CSI,10,-42,6,2,0,12,15,14", "CSI,10,-42,6,2,1,12,15",
     "CSI,10,-42,6,0,0", "CSI,10.5,-42,6,2,0,12,15", "CSI,-1,-42,6,2,0,12,15",
     "CSI,10,nan,6,2,0,12,15", "CSI,10,-42,6,2,0,-1,15", "CSI,10,-42,6,2,0,12.2,15",
     "BAD,10,-42,6,2,0,12,15", "CSI,10,-42,6,2,0,12,15,"],
)
def test_legacy_csi_rejects_malformed_wire_rows(tmp_path, row):
    path = tmp_path / "bad.csv"
    path.write_text(row + "\n")
    with pytest.raises(ValueError, match="line 1"):
        load_csi_csv(path, "trial", "RX1", "known-tx")


def test_csi_samples_allow_tied_uptime_but_reject_reset(tmp_path):
    path = tmp_path / "capture.csv"
    path.write_text("# status,ignored\nCSI,10,-42,6,2,0,12,15\n\nCSI,10,-43,6,2,0,13,15\n")
    rows = load_csi_csv(path, "trial", "RX1", "known-tx")
    assert [row.sample_index for row in rows] == [0, 1]
    assert rows[0].csi_magnitudes == [12, 15]
    path.write_text("CSI,10,-42,6,2,0,12,15\nCSI,1,-43,6,2,0,13,15\n")
    with pytest.raises(ValueError, match="reset/wrap"):
        load_csi_csv(path, "trial", "RX1", "known-tx")
