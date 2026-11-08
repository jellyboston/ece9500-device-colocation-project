"""Several newline records in one send must become separate ordered CSV rows."""

import unittest

from support import ROW, capture, wait_until


class CombinedRowsTest(unittest.TestCase):
    def test_several_rows_in_one_send(self):
        rows = [ROW.replace("1000", str(value)) for value in (1000, 1001, 1002)]
        with capture() as run:
            with run.connect() as sender:
                sender.sendall(("\n".join(rows) + "\n").encode())
            run.wait_count("csi_rows", 3)
            wait_until(lambda: len(run.rows()) == 3, description="three flushed CSI rows")
            self.assertEqual(run.rows(), rows)
