"""Disconnect before a newline must save no sample and report one incomplete record."""

import unittest

from support import capture


class PartialDisconnectTest(unittest.TestCase):
    def test_unterminated_row_is_not_saved(self):
        with capture() as run:
            with run.connect() as sender:
                sender.sendall(b"CSI,1000,-45,6,3,0,1,")
            run.wait_count("disconnects", 1)
            self.assertEqual(run.session.counters["incomplete_records"], 1)
            self.assertEqual(run.session.counters["csi_rows"], 0)
            self.assertEqual(run.rows(), [])
            self.assertIn("incomplete", (run.directory / "collector.log").read_text().lower())
