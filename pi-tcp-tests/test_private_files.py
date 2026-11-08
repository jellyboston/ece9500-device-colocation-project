"""A recording directory must be owner-only (0700) with capture files mode 0600 on POSIX."""

import os
import stat
import unittest

from support import ROW, capture, wait_until


@unittest.skipUnless(os.name == "posix", "POSIX capture permissions")
class PrivateFilesTest(unittest.TestCase):
    def test_capture_directory_and_files_are_private(self):
        with capture() as run:
            with run.connect() as sender:
                sender.sendall((ROW + "\n").encode())
            run.wait_count("disconnects", 1)
            wait_until(lambda: run.rows() == [ROW], description="capture saved before permission checks")
            self.assertEqual(stat.S_IMODE(run.directory.stat().st_mode), 0o700)
            for filename in ("csi.csv", "pose_events.csv", "session.json", "collector.log"):
                with self.subTest(filename=filename):
                    self.assertEqual(stat.S_IMODE((run.directory / filename).stat().st_mode), 0o600)
