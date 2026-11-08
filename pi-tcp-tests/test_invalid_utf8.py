"""Invalid UTF-8 must be rejected as one malformed line; the next valid line must be saved."""

import unittest

from support import ROW, capture, wait_until


class InvalidUtf8Test(unittest.TestCase):
    def test_invalid_utf8_does_not_corrupt_following_record(self):
        with capture() as run:
            with run.connect() as sender:
                sender.sendall(b"CSI,1000,-45,6,1,0,\xff\n" + (ROW + "\n").encode())
            run.wait_count("malformed_records", 1)
            run.wait_count("csi_rows", 1)
            wait_until(lambda: run.rows() == [ROW], description="valid row after UTF-8 rejection")
            self.assertEqual(run.rows(), [ROW])
            self.assertEqual(run.session.counters["malformed_records"], 1)
