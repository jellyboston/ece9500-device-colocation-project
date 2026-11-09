"""A lower receiver uptime must preserve both raw rows and record a possible clock reset."""

import unittest

from support import ROW, capture, wait_until


class ClockResetTest(unittest.TestCase):
    def test_reset_is_reported_without_rewriting_timestamps(self):
        reset_row = ROW.replace("1000", "12")
        with capture() as run:
            with run.connect() as sender:
                sender.sendall((ROW + "\n").encode())
            run.wait_count("disconnects", 1)
            with run.connect() as sender:
                sender.sendall((reset_row + "\n").encode())
            run.wait_count("clock_resets", 1)
            wait_until(lambda: run.rows() == [ROW, reset_row], description="unchanged reset timestamps")
            self.assertEqual(run.rows(), [ROW, reset_row])
            self.assertIn("clock", (run.directory / "collector.log").read_text().lower())
