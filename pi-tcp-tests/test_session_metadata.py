"""Valid receiver metadata must persist firmware/channel and the connection advertisement."""

import json
import unittest

from support import ROW, capture, wait_until


class SessionMetadataTest(unittest.TestCase):
    def test_optional_session_metadata_is_persisted(self):
        advertised = {
            "protocol_version": "csi-legacy-v1",
            "receiver_id": "TEST_RX",
            "firmware_version": "mock-firmware-1",
            "channel": 6,
        }
        with capture() as run:
            with run.connect() as sender:
                sender.sendall(("# SESSION," + json.dumps(advertised) + "\n" + ROW + "\n").encode())
            run.wait_count("disconnects", 1)
            wait_until(lambda: run.metadata()["counters"]["csi_rows"] == 1, description="metadata flushed")
            metadata = run.metadata()
            self.assertEqual(metadata["receiver_id"], "TEST_RX")
            self.assertEqual(metadata["firmware_version"], "mock-firmware-1")
            self.assertEqual(metadata["channel"], 6)
            self.assertEqual(metadata["connections"][0]["advertised_session"], advertised)
            self.assertEqual(run.rows(), [ROW])
