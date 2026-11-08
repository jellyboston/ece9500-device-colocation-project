"""Nonfinite and deeply nested SESSION JSON must be rejected without poisoning later saves."""

import unittest

from support import ROW, capture, wait_until


class MalformedMetadataTest(unittest.TestCase):
    def test_bad_json_values_do_not_crash_collector(self):
        base = '"receiver_id":"TEST_RX","protocol_version":"csi-legacy-v1",'
        malformed = [
            "# SESSION,{" + base + '"extra":NaN}',
            "# SESSION,{" + base + '"extra":1e999}',
            "# SESSION,{" + base + '"extra":' + "[" * 1100 + "0" + "]" * 1100 + "}",
        ]
        with capture() as run:
            with run.connect() as sender:
                sender.sendall(("\n".join(malformed + [ROW]) + "\n").encode())
                run.wait_count("malformed_records", 3)
                run.wait_count("csi_rows", 1)
                wait_until(lambda: run.rows() == [ROW], description="valid row after malformed metadata")
                # Check after a periodic flush as well as the immediate parser path.
                wait_until(lambda: run.metadata()["counters"]["csi_rows"] == 1, description="healthy metadata flush")
                self.assertEqual(run.rows(), [ROW])
                self.assertEqual(run.session.counters["malformed_records"], 3)
