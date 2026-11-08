"""Pose markers must flush analysis-compatible events while retaining CSI during movement."""

import csv
import unittest

from support import ROW, capture, wait_until
from analysis.colocation.capture import load_pose_events


class PoseEventsTest(unittest.TestCase):
    def test_pose_events_are_saved_and_flushed_while_connected(self):
        movement_row = ROW.replace("1000", "1200")
        records = [
            "# POSE_EVENT,P01,CAPTURE_START,900",
            ROW,
            "# POSE_EVENT,P01,CAPTURE_END,1100",
            "# POSE_EVENT,P01,MOVE_START,1101",
            movement_row,
        ]
        with capture() as run:
            with run.connect() as sender:
                sender.sendall(("\n".join(records) + "\n").encode())
                run.wait_count("pose_events", 3)

                def saved_events():
                    with (run.directory / "pose_events.csv").open(newline="") as handle:
                        return list(csv.DictReader(handle))

                wait_until(lambda: len(saved_events()) == 3, description="pose events flushed before disconnect")
                self.assertEqual(saved_events(), [
                    {"event_index": "0", "device_time_ms": "900", "pose_id": "P01", "phase": "CAPTURE_START"},
                    {"event_index": "1", "device_time_ms": "1100", "pose_id": "P01", "phase": "CAPTURE_END"},
                    {"event_index": "2", "device_time_ms": "1101", "pose_id": "P01", "phase": "MOVE_START"},
                ])
                events = load_pose_events(run.directory / "pose_events.csv", receiver_id="TEST_RX")
                self.assertEqual([event.device_time_ms for event in events], [900, 1100, 1101])
                run.wait_count("csi_rows", 2)
                wait_until(lambda: len(run.rows()) == 2, description="stationary and movement rows flushed")
                self.assertEqual(run.rows(), [ROW, movement_row])
