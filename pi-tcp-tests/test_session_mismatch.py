"""Wrong receiver IDs or protocols must end that connection before its CSI rows are saved."""

import json
import unittest

from support import ROW, capture, wait_until


class SessionMismatchTest(unittest.TestCase):
    def test_receiver_or_protocol_mismatch_disconnects_and_recovery_works(self):
        advertisements = [
            {"receiver_id": "WRONG_RX", "protocol_version": "csi-legacy-v1"},
            {"receiver_id": "TEST_RX", "protocol_version": "unknown-v9"},
        ]
        with capture() as run:
            for index, advertised in enumerate(advertisements, 1):
                with run.connect() as sender:
                    sender.sendall(("# SESSION," + json.dumps(advertised) + "\n" + ROW + "\n").encode())
                    run.wait_count("disconnects", index)
                self.assertEqual(run.session.counters["csi_rows"], 0)
                self.assertEqual(run.session.counters["incomplete_records"], 0)
            with run.connect() as sender:
                sender.sendall((ROW + "\n").encode())
            run.wait_count("disconnects", 3)
            wait_until(lambda: run.rows() == [ROW], description="valid row after metadata rejections")
            self.assertEqual(run.rows(), [ROW])
            self.assertEqual(run.session.counters["malformed_records"], 2)
