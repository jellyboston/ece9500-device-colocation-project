"""A second connection must collect valid rows without inheriting the first connection's tail."""

import unittest

from support import ROW, capture, wait_until


class ReconnectTest(unittest.TestCase):
    def test_reconnect_starts_with_empty_record_buffer(self):
        second = ROW.replace("1000", "1001")
        with capture() as run:
            with run.connect() as sender:
                sender.sendall((ROW + "\nCSI,broken").encode())
            run.wait_count("disconnects", 1)
            with run.connect() as sender:
                sender.sendall((second + "\n").encode())
            run.wait_count("disconnects", 2)
            wait_until(lambda: run.rows() == [ROW, second], description="rows across reconnect")
            self.assertEqual(run.rows(), [ROW, second])
            self.assertEqual(run.session.counters["connections"], 2)
            self.assertEqual(run.session.counters["incomplete_records"], 1)
            self.assertEqual(run.session.counters["malformed_records"], 0)
