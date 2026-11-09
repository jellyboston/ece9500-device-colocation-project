"""Labeled RF and autonomous Uno events share one CSV without mixing clocks."""

import csv
import json
from pathlib import Path
import tempfile
import threading
import unittest

from support import ROOT, wait_until
from wisniff.tools.csi_data import CaptureSession, LABELED_PROTOCOL, parse_labeled_record, TcpCollector
from analysis.colocation.capture import parse_capture_samples


class LabeledRobotCaptureTest(unittest.TestCase):
    def test_rf_export_and_robot_clocks(self):
        with tempfile.TemporaryDirectory() as directory:
            with CaptureSession(Path(directory), "RX1", protocol=LABELED_PROTOCOL) as session:
                session.process_record(b"CSI,1103,-38,1,3,ESP,10,20,30", received_ns=100)
                session.process_robot_record(b"ROBOT,0,90000,START", received_ns=200)
                session.process_record(b"PKT,1110,-48,1,LAP1", received_ns=300)
                session.process_robot_record(b"STOP", received_ns=400)
                session.process_record(b"PKT,1111,-50,1,MOCK1", received_ns=500)
                session.process_record(b"PKT,1112,-51,1,LAP2", received_ns=600)
                session.flush()
                with (session.directory / "capture.csv").open() as stream:
                    master = list(csv.DictReader(stream))
                self.assertEqual([row["record_type"] for row in master], ["CSI", "ROBOT", "PKT", "ROBOT", "PKT", "PKT"])
                self.assertEqual([int(row["pi_received_monotonic_ns"]) for row in master], [100, 200, 300, 400, 500, 600])
                self.assertEqual(master[1]["source_time_ms"], "90000")
                self.assertEqual(master[3]["source_time_ms"], "")
                self.assertEqual(master[1]["event"], "START")
                self.assertEqual(master[3]["event"], "STOP")
                self.assertEqual(json.loads(master[0]["csi_magnitudes_json"]), [10, 20, 30])
                samples = parse_capture_samples(session.directory / "observations.csv", "observed-csv")
                self.assertEqual([row.device_id for row in samples], ["ESP", "LAP1", "MOCK1", "LAP2"])
                self.assertEqual(samples[0].csi_magnitudes, [10, 20, 30])
                self.assertEqual(session.counters["robot_events"], 2)
                self.assertEqual(session.counters["clock_resets"], 0)
                self.assertFalse(session.metadata["robot_clock_synchronized"])
                self.assertEqual((session.directory / "pose_events.csv").read_text().count("\n"), 1)

    def test_unsupported_uno_lines_preserved_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            with CaptureSession(Path(directory), "RX1") as session:
                session.process_robot_record(b"moving now")
                session.process_robot_record(b"STARP", start_token="STARP")
                session.process_robot_record(b"ROBOT,0,100,STOP")
                session.process_robot_record(b"ROBOT,1,10,START")
                session.process_robot_record(b"ROBOT,2,-1,STOP")
                session.flush()
                self.assertEqual(session.counters["robot_unknown_records"], 1)
                self.assertEqual(session.counters["robot_events"], 3)
                self.assertEqual(session.counters["robot_clock_resets"], 1)
                self.assertEqual(session.counters["robot_malformed_records"], 1)
                self.assertFalse(session.metadata["requires_clock_split"])
                with (session.directory / "capture.csv").open() as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(rows[0]["raw_record"], "moving now")

    def test_labeled_validation(self):
        for line in ("CSI,100,-40,1,4,ESP,1,2,3", "CSI,100,-40,1,3,0,1,2,3",
                     "PKT,100,nan,1,LAP1", "PKT,100,-45,1,", "PKT,100,-45,99,LAP1"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_labeled_record(line)

    def test_concurrent_tcp_and_uno_writes(self):
        import socket
        with tempfile.TemporaryDirectory() as directory:
            with CaptureSession(Path(directory), "RX1", protocol=LABELED_PROTOCOL) as session:
                stop = threading.Event()
                collector = TcpCollector(session, "127.0.0.1", 0, stop_event=stop)
                worker = threading.Thread(target=collector.serve_forever)
                worker.start()
                self.assertTrue(collector.ready.wait(3))
                def robot():
                    for index in range(20):
                        session.process_robot_record(f"ROBOT,{index},{index * 100},STOP".encode())
                uno = threading.Thread(target=robot)
                try:
                    uno.start()
                    with socket.create_connection(collector.address, timeout=3) as sender:
                        sender.sendall(b'# SESSION,{"receiver_id":"RX1","protocol_version":"rssi-labeled-v1","channel":1}\n')
                        for index in range(100):
                            line = f"PKT,{index},-45,1,LAP1\n".encode()
                            sender.sendall(line[:3]); sender.sendall(line[3:])
                    uno.join(3)
                    wait_until(lambda: session.counters["pkt_rows"] == 100)
                    self.assertEqual(session.counters["robot_events"], 20)
                finally:
                    stop.set(); worker.join(3); uno.join(3)
                session.flush()
                with (session.directory / "capture.csv").open() as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 120)
                self.assertEqual([int(row["record_index"]) for row in rows], list(range(120)))
                self.assertEqual(session.counters["malformed_records"], 0)


if __name__ == "__main__":
    unittest.main()
