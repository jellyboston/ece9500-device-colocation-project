"""The real headless CLI must persist TCP captures and exit cleanly on SIGTERM with a sender connected."""

import csv
import json
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

from support import ROOT, ROW, wait_until


class CliShutdownTest(unittest.TestCase):
    def test_headless_cli_reconnect_and_sigterm(self):
        second = ROW.replace("1000", "1200")
        with tempfile.TemporaryDirectory(prefix="pi-tcp-cli-test-") as root:
            output_root = Path(root)
            process = subprocess.Popen(
                [
                    sys.executable, str(ROOT / "wisniff" / "tools" / "csi_data.py"),
                    "--headless", "--host", "127.0.0.1", "--port", "0",
                    "--output-dir", str(output_root), "--receiver-id", "TEST_RX",
                    "--flush-interval", "0.05",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            diagnostics = []
            addresses = []

            def read_diagnostics():
                for line in process.stderr:
                    diagnostics.append(line)
                    match = re.search(r"TCP listening on (127\.0\.0\.1):(\d+)", line)
                    if match:
                        addresses.append((match.group(1), int(match.group(2))))

            reader = threading.Thread(target=read_diagnostics, daemon=True)
            reader.start()
            try:
                wait_until(
                    lambda: addresses or process.poll() is not None,
                    description="headless CLI listener startup",
                )
                self.assertTrue(addresses, "CLI exited before listening: " + "".join(diagnostics))
                directories = list(output_root.glob("run-*"))
                self.assertEqual(len(directories), 1)
                directory = directories[0]

                def metadata():
                    return json.loads((directory / "session.json").read_text(encoding="utf-8"))

                first_connection = [
                    "# POSE_EVENT,P01,CAPTURE_START,900",
                    ROW,
                    "# POSE_EVENT,P01,CAPTURE_END,1100",
                    "CSI,unfinished",
                ]
                with socket.create_connection(addresses[0], timeout=3) as sender:
                    # The final partial row deliberately has no terminating newline.
                    sender.sendall("\n".join(first_connection).encode())
                wait_until(
                    lambda: metadata()["counters"]["disconnects"] == 1,
                    description="CLI first disconnect persisted",
                )
                with socket.create_connection(addresses[0], timeout=3) as sender:
                    sender.sendall((second + "\n").encode())
                    wait_until(
                        lambda: metadata()["counters"]["csi_rows"] == 2,
                        description="CLI second connection CSI saved",
                    )
                    # Keep the sender connected while exercising main's signal handler.
                    process.send_signal(signal.SIGTERM)
                    exit_code = process.wait(timeout=4)
                reader.join(timeout=2)
                self.assertEqual(exit_code, 0, "".join(diagnostics))
                final = metadata()
                self.assertEqual(final["state"], "closed")
                self.assertIsNotNone(final["ended_at"])
                self.assertEqual(final["receiver_id"], "TEST_RX")
                for key, expected in {
                    "csi_rows": 2, "pose_events": 2, "connections": 2,
                    "disconnects": 2, "incomplete_records": 1, "malformed_records": 0,
                }.items():
                    with self.subTest(counter=key):
                        self.assertEqual(final["counters"][key], expected)
                self.assertEqual((directory / "csi.csv").read_text().splitlines(), [ROW, second])
                with (directory / "pose_events.csv").open(newline="") as handle:
                    events = list(csv.DictReader(handle))
                self.assertEqual([row["event_index"] for row in events], ["0", "1"])
                self.assertEqual([row["device_time_ms"] for row in events], ["900", "1100"])
                self.assertEqual([row["phase"] for row in events], ["CAPTURE_START", "CAPTURE_END"])
                self.assertIn("incomplete", (directory / "collector.log").read_text().lower())
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=4)
                reader.join(timeout=2)
                process.stderr.close()
