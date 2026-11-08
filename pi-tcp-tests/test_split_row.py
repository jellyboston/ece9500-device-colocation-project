"""One record split across many TCP writes must be saved once after its newline."""

import unittest

from support import ROW, capture, wait_until


class SplitRowTest(unittest.TestCase):
    def test_partial_writes_form_one_row(self):
        with capture() as run:
            with run.connect() as sender:
                for fragment in (b"C", b"SI,10", b"00,-45,6,3,0,1,", b"2,3", b"\r", b"\n"):
                    sender.sendall(fragment)
            run.wait_count("csi_rows", 1)
            wait_until(lambda: run.rows() == [ROW], description="reassembled CSI row")
            self.assertEqual(run.rows(), [ROW])
            self.assertEqual(run.session.counters["malformed_records"], 0)
