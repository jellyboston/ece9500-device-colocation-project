"""Compile and exercise the firmware's TCP transport on the host (C++ compiler needed)."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from support import ROOT


@unittest.skipUnless(shutil.which("c++"), "native C++ compiler not available; ESP32 build remains separate")
class FirmwareTransportTest(unittest.TestCase):
    def test_real_tcp_short_writes_and_reconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = str(Path(directory) / "tcp_sender")
            result = subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                     "-I", str(ROOT / "wisniff/include"),
                                     str(ROOT / "pi-tcp-tests/tcp_sender_native.cpp"), "-o", binary],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([binary], text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
