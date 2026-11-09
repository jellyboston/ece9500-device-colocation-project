"""An oversized line must be discarded without blocking recovery at the next newline."""

import unittest

from support import ROW, capture, wait_until


class OversizedRecordTest(unittest.TestCase):
    def test_oversized_unterminated_record_is_bounded(self):
        with capture() as run:
            with run.connect() as sender:
                sender.sendall(b"x" * 100_000 + b"\n" + (ROW + "\n").encode())
            run.wait_count("oversized_records", 1)
            run.wait_count("csi_rows", 1)
            wait_until(lambda: run.rows() == [ROW], description="valid row after oversized line")
            self.assertEqual(run.rows(), [ROW])
            self.assertEqual(run.session.counters["oversized_records"], 1)
