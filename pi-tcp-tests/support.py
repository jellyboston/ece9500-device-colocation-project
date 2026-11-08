"""Loopback sender and bounded collection helpers shared by the TCP tests."""

from contextlib import contextmanager
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wisniff.tools.csi_data import CaptureSession, TcpCollector


ROW = "CSI,1000,-45,6,3,0,1,2,3"


def wait_until(predicate, *, timeout=4.0, description="collector condition"):
    """Wait for observable state instead of assuming the receiver thread is fast."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError(f"Timed out waiting for {description}")


class RunningCapture:
    def __init__(self, session, collector, thread, errors, stop):
        self.session = session
        self.collector = collector
        self.thread = thread
        self.errors = errors
        self.stop = stop

    @property
    def directory(self):
        return self.session.directory

    def connect(self):
        return socket.create_connection(self.collector.address, timeout=3)

    def wait_count(self, name, count):
        wait_until(
            lambda: self.session.counters[name] >= count or bool(self.errors),
            description=f"{name} >= {count}",
        )
        if self.errors:
            raise AssertionError(f"Receiver failed: {self.errors!r}")

    def rows(self):
        return (self.directory / "csi.csv").read_text(encoding="utf-8").splitlines()

    def metadata(self):
        return json.loads((self.directory / "session.json").read_text(encoding="utf-8"))

    def shutdown(self):
        self.stop.set()
        self.thread.join(timeout=4)
        if self.thread.is_alive():
            raise AssertionError("TCP receiver did not stop within four seconds")


@contextmanager
def capture():
    """Start an actual TCP listener with isolated files and stop it on every exit."""
    with tempfile.TemporaryDirectory(prefix="pi-tcp-test-") as root:
        with CaptureSession(Path(root), "TEST_RX", flush_interval=0.05) as session:
            stop = threading.Event()
            collector = TcpCollector(session, host="127.0.0.1", port=0, stop_event=stop)
            errors = []

            def serve():
                try:
                    collector.serve_forever()
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            try:
                if not collector.ready.wait(4):
                    raise AssertionError(f"TCP listener did not start: {errors!r}")
                if errors:
                    raise AssertionError(f"TCP listener failed: {errors!r}")
                yield RunningCapture(session, collector, thread, errors, stop)
            finally:
                stop.set()
                thread.join(timeout=4)
                if thread.is_alive():
                    raise AssertionError("TCP receiver did not stop within four seconds")
                if errors:
                    raise AssertionError(f"TCP receiver failed: {errors!r}")
        final_metadata = json.loads((session.directory / "session.json").read_text(encoding="utf-8"))
        if final_metadata["counters"] != session.counters:
            raise AssertionError("Final session metadata does not contain the final counters")
