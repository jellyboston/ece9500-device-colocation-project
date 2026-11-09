"""Real pseudo-serial Uno input and loopback TCP RF input through the same CLI."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

from support import ROOT, wait_until


@unittest.skipUnless(os.name == "posix" and importlib.util.find_spec("serial"), "needs POSIX pseudo-terminal and pyserial")
class UnoSerialTest(unittest.TestCase):
    def test_uno_and_rf_share_one_master_file(self):
        import pty
        master, slave = pty.openpty()
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.Popen([
                sys.executable, str(ROOT / "wisniff/tools/csi_data.py"),
                "--protocol", "rssi-labeled-v1", "--host", "127.0.0.1", "--port", "0",
                "--output-dir", directory, "--uno-port", os.ttyname(slave), "--flush-interval", "0.05",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            diagnostics, addresses, uno_ready = [], [], threading.Event()
            def read_log():
                for line in process.stderr:
                    diagnostics.append(line)
                    if "TCP listening on " in line:
                        port = int(line.rsplit(":", 1)[-1])
                        addresses.append(("127.0.0.1", port))
                    if "Uno connected on " in line:
                        uno_ready.set()
            reader = threading.Thread(target=read_log, daemon=True)
            reader.start()
            try:
                wait_until(lambda: addresses or process.poll() is not None)
                self.assertTrue(addresses, "".join(diagnostics))
                self.assertTrue(uno_ready.wait(3), "".join(diagnostics))
                capture = next(Path(directory).glob("run-*"))
                def metadata():
                    return json.loads((capture / "session.json").read_text())
                with socket.create_connection(addresses[0], timeout=3) as sender:
                    os.write(master, b"START\n")
                    sender.sendall(b"PKT,1000,-45,1,LAP1\nCSI,1001,-40,1,3,ESP,1,2,3\n")
                    os.write(master, b"ROBOT,1,90000,STOP\n")
                    wait_until(lambda: metadata()["counters"]["robot_events"] == 2 and metadata()["counters"]["pkt_rows"] == 1)
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(4), 0)
                reader.join(2)
                with (capture / "capture.csv").open() as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 4)
                self.assertEqual({row["source"] for row in rows}, {"ESP32", "UNO"})
                self.assertEqual([row["event"] for row in rows if row["source"] == "UNO"], ["START", "STOP"])
                self.assertEqual([row["source_time_ms"] for row in rows if row["source"] == "UNO"], ["", "90000"])
                self.assertFalse(metadata()["robot_clock_synchronized"])
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(4)
                reader.join(2)
                process.stderr.close()
                os.close(master); os.close(slave)


if __name__ == "__main__":
    unittest.main()
