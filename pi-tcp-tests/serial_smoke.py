"""Optional Linux PTY smoke: legacy serial CLI must save CSI/pose events and close on SIGTERM."""

import importlib.util
import json
import os
from pathlib import Path
import pty
import signal
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, ROW, wait_until


@unittest.skipUnless(importlib.util.find_spec("serial"), "optional smoke requires pyserial")
class SerialSmokeTest(unittest.TestCase):
    def test_legacy_serial_cli_uses_same_record_handler(self):
        with tempfile.TemporaryDirectory(prefix="pi-serial-smoke-") as root:
            master, slave = pty.openpty()
            process = None
            try:
                # Positional serial-port invocation retains the old command shape.
                process = subprocess.Popen(
                    [sys.executable, str(ROOT / "wisniff" / "tools" / "csi_data.py"),
                     os.ttyname(slave), "--headless", "--output-dir", root,
                     "--receiver-id", "TEST_RX", "--flush-interval", "0.05"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                output_root = Path(root)

                def metadata():
                    files = list(output_root.glob("run-*/session.json"))
                    return json.loads(files[0].read_text()) if files else {"counters": {"connections": 0}}

                wait_until(
                    lambda: metadata()["counters"]["connections"] == 1 or process.poll() is not None,
                    description="serial CLI PTY opened",
                )
                self.assertIsNone(process.poll(), "serial CLI exited before PTY collection")
                os.write(master, b"# POSE_EVENT,P01,CAPTURE_START,900\n")
                os.write(master, (ROW[:10]).encode())
                os.write(master, (ROW[10:] + "\n# POSE_EVENT,P01,CAPTURE_END,1100\n").encode())
                wait_until(
                    lambda: metadata()["counters"].get("pose_events", 0) == 2,
                    description="serial CSV and pose events persisted",
                )
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=4), 0)
                directory = next(output_root.glob("run-*"))
                final = metadata()
                self.assertEqual(final["state"], "closed")
                self.assertEqual(final["counters"]["csi_rows"], 1)
                self.assertEqual(final["counters"]["pose_events"], 2)
                self.assertEqual(final["counters"]["disconnects"], 1)
                self.assertEqual((directory / "csi.csv").read_text().splitlines(), [ROW])
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=4)
                os.close(master)
                os.close(slave)


if __name__ == "__main__":
    unittest.main(verbosity=2)
