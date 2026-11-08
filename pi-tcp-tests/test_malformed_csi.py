"""Bad CSI count and sentinel must be diagnosed and excluded; a later valid row survives."""

import unittest

from support import ROW, capture, wait_until


class MalformedCsiTest(unittest.TestCase):
    def test_bad_count_and_sentinel_are_rejected(self):
        invalid = ["CSI,1000,-45,6,4,0,1,2,3", "CSI,1000,-45,6,3,1,1,2,3"]
        with capture() as run:
            with run.connect() as sender:
                sender.sendall(("\n".join(invalid + [ROW]) + "\n").encode())
            run.wait_count("malformed_records", 2)
            run.wait_count("csi_rows", 1)
            wait_until(lambda: run.rows() == [ROW], description="only validated CSI saved")
            self.assertEqual(run.rows(), [ROW])
            self.assertEqual(run.session.counters["malformed_records"], 2)
            log = (run.directory / "collector.log").read_text(encoding="utf-8")
            self.assertIn("sentinel", log)
            self.assertIn("magnitudes", log)
