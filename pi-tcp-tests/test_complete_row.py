"""One complete CSI line must produce exactly one unchanged CSV row."""

import unittest

from support import ROW, capture, wait_until


class CompleteRowTest(unittest.TestCase):
    def test_one_complete_row(self):
        with capture() as run:
            with run.connect() as sender:
                sender.sendall((ROW + "\n").encode())
            run.wait_count("csi_rows", 1)
            wait_until(lambda: run.rows() == [ROW], description="flushed single CSI row")
            self.assertEqual(run.rows(), [ROW])
            self.assertEqual(run.session.counters["malformed_records"], 0)
