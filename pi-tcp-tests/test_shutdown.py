"""Stopping with an active sender must close promptly and flush its complete CSI rows."""

import unittest

from support import ROW, capture, wait_until


class ShutdownTest(unittest.TestCase):
    def test_stop_with_connected_sender_preserves_complete_rows(self):
        with capture() as run:
            with run.connect() as sender:
                sender.sendall((ROW + "\n").encode())
                run.wait_count("csi_rows", 1)
                # Orderly stop must not depend on the sender first disconnecting.
                run.shutdown()
                self.assertFalse(run.thread.is_alive())
                self.assertEqual(run.session.counters["incomplete_records"], 0)
                wait_until(lambda: run.rows() == [ROW], description="complete row flushed at shutdown")
                self.assertEqual(run.rows(), [ROW])
