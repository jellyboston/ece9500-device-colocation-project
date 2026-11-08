"""A TCP reset must be logged as a disconnect, preserve saved rows, and allow reconnection."""

import socket
import struct
import unittest

from support import ROW, capture, wait_until


class AbruptDisconnectTest(unittest.TestCase):
    def test_reset_does_not_stop_listener(self):
        second = ROW.replace("1000", "1001")
        with capture() as run:
            sender = run.connect()
            try:
                sender.sendall((ROW + "\n").encode())
                run.wait_count("csi_rows", 1)
                sender.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            finally:
                sender.close()
            run.wait_count("disconnects", 1)
            with run.connect() as sender:
                sender.sendall((second + "\n").encode())
            run.wait_count("disconnects", 2)
            wait_until(lambda: run.rows() == [ROW, second], description="saved rows after TCP reset")
            self.assertEqual(run.rows(), [ROW, second])
            self.assertEqual(run.session.counters["connections"], 2)
