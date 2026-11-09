"""Credential macro aliases compile without real credentials or Arduino tooling."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from support import ROOT


@unittest.skipUnless(shutil.which("c++"), "needs native C++ compiler")
class PrivateFlagAliasesTest(unittest.TestCase):
    def test_lowercase_and_uppercase_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "flags.cpp"
            source.write_text('#include "rx_network_config.h"\nconst char *ssid = WIFI_SSID;\n'
                              'const char *password = WIFI_PASSWORD;\nconst char *host = PI_TCP_HOST;\n')
            for ssid, password in [("wifi_ssid", "wifi_pass"), ("WIFI_SSID", "WIFI_PASS"),
                                   ("WIFI_SSID", "WIFI_PASSWORD")]:
                with self.subTest(ssid=ssid, password=password):
                    result = subprocess.run([
                        "c++", "-std=c++17", "-fsyntax-only", "-I", str(ROOT / "wisniff/include"),
                        f'-D{ssid}="test-ssid"', f'-D{password}="test-password"',
                        '-DPI_TCP_HOST="127.0.0.1"', str(source),
                    ], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_pi_host_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "flags.cpp"
            source.write_text('#include "rx_network_config.h"\n')
            result = subprocess.run([
                "c++", "-std=c++17", "-fsyntax-only", "-I", str(ROOT / "wisniff/include"),
                '-Dwifi_ssid="test"', '-Dwifi_pass="test"', str(source),
            ], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PI_TCP_HOST", result.stderr)
