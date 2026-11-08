"""Collect newline-delimited ESP32 records over TCP or serial, with optional plots.

The collector needs only Python's standard library for headless TCP operation.
Legacy CSI validation is shared with the offline analysis, without assigning TX IDs.
"""

from __future__ import annotations

import argparse
import collections
import csv
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import signal
import socket
import sys
import threading
import time
import uuid

# Also support the historical `python wisniff/tools/csi_data.py ...` invocation.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis.colocation.ingest import parse_csi_record
from analysis.colocation.models import PHASES

PROTOCOL_VERSION = "csi-legacy-v1"
DEFAULT_OUTPUT = REPO_ROOT / "analysis" / "data" / "raw"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def private_file(path: Path):
    """Create a new capture file readable/writable only by its owner."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8", newline="")


class ReceiverMismatch(ValueError):
    """An advertised receiver/protocol must not contaminate this recording."""


class LineFramer:
    """Bounded byte framing; decode UTF-8 only after a complete newline arrives."""

    def __init__(self, session, max_record_bytes=16384):
        self.session = session
        self.limit = max_record_bytes
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, data: bytes):
        parts = data.split(b"\n")
        for index, part in enumerate(parts):
            complete = index < len(parts) - 1
            if not self.discarding:
                if len(self.buffer) + len(part) > self.limit:
                    self.session.counters["oversized_records"] += 1
                    self.session.log.warning("Oversized record (> %d bytes); discard through next newline", self.limit)
                    self.buffer.clear()
                    self.discarding = True
                else:
                    self.buffer.extend(part)
            if complete:
                record = None if self.discarding else bytes(self.buffer).removesuffix(b"\r")
                self.buffer.clear()
                self.discarding = False
                if record is not None:
                    yield record

    def finish(self):
        if self.buffer or self.discarding:
            self.session.counters["incomplete_records"] += 1
            self.session.log.warning("Incomplete record at disconnect/shutdown: %d buffered bytes, oversized=%s; discarded",
                                     len(self.buffer), self.discarding)
        self.buffer.clear()
        self.discarding = False


class CaptureSession:
    """Own the CSVs, metadata and diagnostics for one receiver recording."""

    def __init__(self, output_root: Path, receiver_id: str, *, channel=None,
                 firmware_version=None, flush_interval=1.0, plot=False):
        if not receiver_id.strip():
            raise ValueError("receiver_id must be nonempty")
        if not math.isfinite(flush_interval) or flush_interval <= 0:
            raise ValueError("flush_interval must be positive and finite")
        if channel is not None and not 1 <= channel <= 14:
            raise ValueError("channel must be between 1 and 14")
        output_root = Path(output_root).resolve()
        output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S.%fZ-") + uuid.uuid4().hex[:8]
        self.directory = output_root / name
        self.directory.mkdir(mode=0o700)
        self.receiver_id = receiver_id
        self.counters = dict.fromkeys(("csi_rows", "pose_events", "malformed_records", "incomplete_records",
                                      "oversized_records", "connections", "disconnects", "clock_resets",
                                      "bytes_received", "diagnostic_records"), 0)
        self.metadata = {
            "schema_version": 1, "receiver_id": receiver_id,
            "protocol_version": PROTOCOL_VERSION, "firmware_version": firmware_version,
            "channel": channel, "observed_channels": [], "started_at": utc_now(),
            "ended_at": None, "state": "collecting", "counters": self.counters,
            "connections": [], "clock_resets": [], "requires_clock_split": False,
            "transmitter_identity": "not provided by legacy CSI records",
        }
        self.log = logging.getLogger("csi-collector." + name)
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        self._log_file = private_file(self.directory / "collector.log")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        formatter.converter = time.gmtime
        for stream in (self._log_file, sys.stderr):
            handler = logging.StreamHandler(stream)
            handler.setFormatter(formatter)
            self.log.addHandler(handler)
        self._csi_file = private_file(self.directory / "csi.csv")
        self._pose_file = private_file(self.directory / "pose_events.csv")
        self._pose_writer = csv.writer(self._pose_file, lineterminator="\n")
        self._pose_writer.writerow(("event_index", "device_time_ms", "pose_id", "phase"))
        self._last_clock = {}
        self._connection = None
        self._flush_interval = flush_interval
        self._last_flush = time.monotonic()
        self._last_summary = self._last_flush
        self._closed = False
        self.plot_enabled = plot
        self.plot_rows = collections.deque(maxlen=300)
        self.plot_lock = threading.Lock()
        self.log.info("Capture directory: %s; receiver=%s; protocol=%s", self.directory, receiver_id, PROTOCOL_VERSION)
        self.flush()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close(failed=exc_type is not None)

    def connect(self, peer: str, transport: str) -> int:
        self.counters["connections"] += 1
        number = self.counters["connections"]
        self._connection = {
            "connection_id": number, "transport": transport, "peer": peer,
            "connected_at": utc_now(), "disconnected_at": None,
            "first_csi_row": self.counters["csi_rows"], "first_event_index": self.counters["pose_events"],
        }
        self.metadata["connections"].append(self._connection)
        self.log.info("Connected #%d via %s: %s", number, transport, peer)
        self.flush()
        return number

    def disconnect(self, reason: str):
        if self._connection is None:
            return
        self.counters["disconnects"] += 1
        self._connection.update(disconnected_at=utc_now(), reason=reason,
                                end_csi_row=self.counters["csi_rows"], end_event_index=self.counters["pose_events"])
        self.log.info("Disconnected #%d: %s", self._connection["connection_id"], reason)
        self._connection = None
        self.flush(sync=True)

    def _clock(self, kind: str, timestamp: int):
        previous = self._last_clock.get(kind)
        if previous is not None and timestamp < previous:
            self.counters["clock_resets"] += 1
            boundary = {"record_type": kind, "previous_ms": previous, "current_ms": timestamp,
                        "csi_row": self.counters["csi_rows"], "event_index": self.counters["pose_events"],
                        "connection_id": self._connection["connection_id"] if self._connection else None}
            self.metadata["clock_resets"].append(boundary)
            self.metadata["requires_clock_split"] = True
            self.log.warning("Possible receiver clock reset/wrap: %s; split recording before analysis", boundary)
        self._last_clock[kind] = timestamp

    def process_record(self, raw: bytes):
        """Validate then save. No host timestamp replaces ESP32 uptime."""
        try:
            line = raw.decode("utf-8", errors="strict")
            if not line.strip():
                return
            if line.startswith("CSI,"):
                record = parse_csi_record(next(csv.reader([line], strict=True)))
                self._clock("CSI", record.device_time_ms)
                self._csi_file.write(line + "\n")
                self.counters["csi_rows"] += 1
                if record.channel not in self.metadata["observed_channels"]:
                    self.metadata["observed_channels"].append(record.channel)
                    expected = self.metadata["channel"]
                    if expected is not None and record.channel != expected:
                        self.log.warning("Channel mismatch: configured=%s observed=%s", expected, record.channel)
                if self.plot_enabled:
                    with self.plot_lock:
                        self.plot_rows.append(record.csi_magnitudes)
            elif line.startswith("# POSE_EVENT"):
                fields = next(csv.reader([line], strict=True))
                if len(fields) != 4 or fields[0] != "# POSE_EVENT":
                    raise ValueError("expected # POSE_EVENT,<pose_id>,<phase>,<receiver_millis>")
                _, pose, phase, millis = fields
                if not pose.strip() or phase not in PHASES or not millis.isascii() or not millis.isdecimal():
                    raise ValueError("invalid pose label, phase or nonnegative receiver timestamp")
                timestamp = int(millis)
                self._clock("POSE_EVENT", timestamp)
                index = self.counters["pose_events"]
                self._pose_writer.writerow((index, timestamp, pose, phase))
                self.counters["pose_events"] += 1
                self.log.info("Pose event #%d: %s %s receiver_ms=%d", index, pose, phase, timestamp)
                self.flush(sync=True)
            elif line.startswith("# SESSION,"):
                self._session_record(line[len("# SESSION,"):])
            elif line.startswith("#"):
                self.counters["diagnostic_records"] += 1
                self.log.info("Firmware: %s", line)
            else:
                raise ValueError("unknown record type (expected CSI, # POSE_EVENT or # diagnostic)")
        except ReceiverMismatch:
            self.counters["malformed_records"] += 1
            raise
        except (UnicodeDecodeError, ValueError, csv.Error, RecursionError) as exc:
            self.counters["malformed_records"] += 1
            # Avoid echoing arbitrary measurement payloads or control characters.
            self.log.warning("Malformed record (%d bytes): %s", len(raw), exc)

    def _session_record(self, payload: str):
        def reject_constant(value):
            raise ValueError(f"SESSION contains non-JSON number {value}")

        advertised = json.loads(payload, parse_constant=reject_constant)
        if not isinstance(advertised, dict):
            raise ValueError("SESSION metadata must be a JSON object")
        if advertised.keys() - {"receiver_id", "protocol_version", "firmware_version", "channel"}:
            raise ValueError("SESSION supports only receiver_id, protocol_version, firmware_version and channel")
        if advertised.get("receiver_id") != self.receiver_id:
            raise ReceiverMismatch("SESSION receiver_id does not match configured receiver; disconnecting")
        if advertised.get("protocol_version") != PROTOCOL_VERSION:
            raise ReceiverMismatch("unsupported SESSION protocol_version; disconnecting")
        firmware = advertised.get("firmware_version")
        channel = advertised.get("channel")
        if firmware is not None and (not isinstance(firmware, str) or not firmware.strip()):
            raise ValueError("SESSION firmware_version must be a nonempty string when supplied")
        if channel is not None and (type(channel) is not int or not 1 <= channel <= 14):
            raise ValueError("SESSION channel must be an integer between 1 and 14")
        if self._connection is not None:
            self._connection["advertised_session"] = advertised
        if self.metadata["firmware_version"] is None:
            self.metadata["firmware_version"] = firmware
        if self.metadata["channel"] is None:
            self.metadata["channel"] = channel
        elif channel is not None and self.metadata["channel"] != channel:
            self.log.warning("SESSION channel differs from configured channel: %s", channel)
        self.log.info("Receiver session metadata: %s", advertised)
        self.flush(sync=True)

    def maybe_flush(self):
        now = time.monotonic()
        if now - self._last_summary >= 10:
            self.log.info("Collection counts: %s", self.counters)
            self._last_summary = now
        if now - self._last_flush >= self._flush_interval:
            self.flush()

    def flush(self, *, sync=False):
        for handle in (self._csi_file, self._pose_file, self._log_file):
            handle.flush()
            if sync:
                os.fsync(handle.fileno())
        # Atomic replacement leaves the previous complete metadata on interruption.
        temporary = self.directory / "session.json.tmp"
        try:
            with private_file(temporary) as handle:
                json.dump(self.metadata, handle, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                if sync:
                    os.fsync(handle.fileno())
            os.replace(temporary, self.directory / "session.json")
        finally:
            temporary.unlink(missing_ok=True)
        self._last_flush = time.monotonic()

    def close(self, *, failed=False):
        if self._closed:
            return
        self.disconnect("collector shutdown")
        self.metadata.update(ended_at=utc_now(), state="failed" if failed else "closed")
        self.log.info("Collection stopped: %s", self.counters)
        try:
            self.flush(sync=True)
        finally:
            self._closed = True
            for handle in (self._csi_file, self._pose_file):
                handle.close()
            for handler in list(self.log.handlers):
                handler.close()
                self.log.removeHandler(handler)
            self._log_file.close()


class TcpCollector:
    """Serve one receiver at a time; a reconnect starts a fresh byte buffer."""

    def __init__(self, session: CaptureSession, host="0.0.0.0", port=9000, *, stop_event=None,
                 max_record_bytes=16384):
        self.session = session
        self.host = host
        self.port = port
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self.max_record_bytes = max_record_bytes
        self.ready = threading.Event()
        self.address = None

    def serve_forever(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(1)
            server.settimeout(0.25)
            self.address = server.getsockname()
            self.session.log.info("TCP listening on %s:%d", *self.address)
            self.ready.set()
            while not self.stop_event.is_set():
                self.session.maybe_flush()
                try:
                    client, address = server.accept()
                except socket.timeout:
                    continue
                with client:
                    client.settimeout(0.25)
                    client.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    # Linux keepalive notices vanished devices even when no FIN arrives.
                    for option, value in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
                        if hasattr(socket, option):
                            client.setsockopt(socket.IPPROTO_TCP, getattr(socket, option), value)
                    self.session.connect(f"{address[0]}:{address[1]}", "tcp")
                    framer = LineFramer(self.session, self.max_record_bytes)
                    reason = "peer closed"
                    try:
                        while not self.stop_event.is_set():
                            self.session.maybe_flush()
                            try:
                                data = client.recv(65536)
                            except socket.timeout:
                                continue
                            if not data:
                                break
                            self.session.counters["bytes_received"] += len(data)
                            for record in framer.feed(data):
                                self.session.process_record(record)
                        if self.stop_event.is_set():
                            reason = "collector shutdown"
                    except (OSError, ReceiverMismatch) as exc:
                        reason = str(exc)
                        self.session.log.warning("Receiver connection error: %s", exc)
                    finally:
                        framer.finish()
                        self.session.disconnect(reason)


class SerialCollector:
    """Optional serial input uses the same framing, validation and capture files."""

    def __init__(self, session, port, baud, stop_event, max_record_bytes=16384):
        self.session, self.port, self.baud = session, port, baud
        self.stop_event, self.max_record_bytes = stop_event, max_record_bytes

    def serve_forever(self):
        import serial  # Optional dependency; headless TCP never imports it.

        while not self.stop_event.is_set():
            framer = LineFramer(self.session, self.max_record_bytes)
            reason = "collector shutdown"
            try:
                with serial.Serial(self.port, self.baud, timeout=0.25) as device:
                    self.session.connect(self.port, "serial")
                    while not self.stop_event.is_set():
                        data = device.read(min(device.in_waiting or 1, 65536))
                        self.session.counters["bytes_received"] += len(data)
                        for record in framer.feed(data):
                            self.session.process_record(record)
                        self.session.maybe_flush()
            except (serial.SerialException, OSError, ReceiverMismatch) as exc:
                reason = str(exc)
                self.session.log.warning("Serial connection error: %s; retrying in 1 second", exc)
            finally:
                framer.finish()
                self.session.disconnect(reason)
            self.stop_event.wait(1)


def show_plot(sessions, stop_event):
    """The GUI is only an observer: closing its window leaves workers collecting."""
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    fig, axes = plt.subplots(len(sessions), 1, figsize=(10, 3.5 * len(sessions)), squeeze=False)
    images = []
    for axis, session in zip(axes[:, 0], sessions):
        image = axis.imshow(np.zeros((64, 10)), aspect="auto", origin="lower", vmin=0, vmax=60)
        axis.set_title(session.receiver_id)
        axis.set_xlabel("frame")
        axis.set_ylabel("subcarrier")
        images.append(image)

    def update(_):
        if stop_event.is_set():
            plt.close(fig)
            return images
        for image, session in zip(images, sessions):
            with session.plot_lock:
                rows = list(session.plot_rows)
            if rows:
                rows = [row for row in rows if len(row) == len(rows[-1])]
                image.set_data(np.array(rows).T)
                image.set_extent((0, len(rows), 0, len(rows[-1])))
        return images

    animation = FuncAnimation(fig, update, interval=200, cache_frame_data=False)
    plt.tight_layout()
    plt.show()
    return animation


def positive_float(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial_ports", nargs="*", help="legacy serial ports; implies --transport serial")
    parser.add_argument("--transport", choices=("tcp", "serial"))
    parser.add_argument("--host", default="0.0.0.0", help="TCP bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=9000, help="TCP listen port (default: 9000)")
    parser.add_argument("--receiver-id", action="append", help="receiver label; repeat once per serial port (default: RX1, RX2, ...)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--channel", type=int, choices=range(1, 15), help="expected fixed Wi-Fi channel")
    parser.add_argument("--firmware-version", help="operator-supplied firmware revision when known")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--flush-interval", type=positive_float, default=1.0)
    parser.add_argument("--max-record-bytes", type=int, default=16384)
    plotting = parser.add_mutually_exclusive_group()
    plotting.add_argument("--plot", action="store_true", help="show a live plot; closing it keeps collection running")
    plotting.add_argument("--headless", action="store_true", help="collect without a GUI (the default)")
    args = parser.parse_args(argv)
    transport = args.transport or ("serial" if args.serial_ports else "tcp")
    if transport == "serial" and not args.serial_ports:
        parser.error("serial transport requires one or more positional serial ports")
    if transport == "tcp" and args.serial_ports:
        parser.error("serial ports cannot be used with TCP transport")
    if not 0 <= args.port <= 65535 or args.baud <= 0 or args.max_record_bytes <= 0:
        parser.error("port must be 0..65535; baud and max-record-bytes must be positive")
    count = len(args.serial_ports) if transport == "serial" else 1
    receiver_ids = args.receiver_id or [f"RX{index + 1}" for index in range(count)]
    if len(receiver_ids) != count or any(not label.strip() for label in receiver_ids) or len(set(receiver_ids)) != count:
        parser.error("provide one unique nonempty --receiver-id per input")

    stop_event = threading.Event()
    previous_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, lambda signum, frame: stop_event.set())
    sessions, workers, errors = [], [], []

    def collect(collector):
        try:
            collector.serve_forever()
        except Exception as exc:
            collector.session.log.exception("Collector failed")
            errors.append(exc)
            stop_event.set()

    try:
        for index, receiver in enumerate(receiver_ids):
            session = CaptureSession(args.output_dir, receiver, channel=args.channel,
                                     firmware_version=args.firmware_version, flush_interval=args.flush_interval,
                                     plot=args.plot)
            sessions.append(session)
            if transport == "tcp":
                collector = TcpCollector(session, args.host, args.port, stop_event=stop_event,
                                         max_record_bytes=args.max_record_bytes)
            else:
                collector = SerialCollector(session, args.serial_ports[index], args.baud, stop_event,
                                            args.max_record_bytes)
            worker = threading.Thread(target=collect, args=(collector,), name=f"collector-{index}")
            worker.start()
            workers.append(worker)
        if args.plot:
            try:
                show_plot(sessions, stop_event)
            except Exception:
                sessions[0].log.exception("Plot unavailable; continuing headlessly")
            sessions[0].log.info("Plot closed; collection continues. Press Ctrl+C to stop.")
        while not stop_event.wait(0.25):
            pass
    except Exception as exc:
        errors.append(exc)
        print(f"Collector startup failed: {exc}", file=sys.stderr)
    finally:
        stop_event.set()
        for worker in workers:
            worker.join()
        for session in sessions:
            session.close(failed=bool(errors))
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
