"""Validated transport records; group truth is separate from observations."""

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from typing import Any


def identifier(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def integer(value: Any, name: str, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def finite(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be finite and numeric")


def channel_number(value: Any) -> None:
    if value is not None:
        integer(value, "channel", 1)
        if value > 14:
            raise ValueError("channel must be between 1 and 14")


def signal(rssi: Any, channel: Any, magnitudes: Any) -> None:
    finite(rssi, "rssi_dbm")
    if not -120 <= rssi <= 0:
        raise ValueError("rssi_dbm must be between -120 and 0 dBm")
    channel_number(channel)
    if magnitudes is not None:
        if not isinstance(magnitudes, list) or not magnitudes:
            raise ValueError("csi_magnitudes must be a nonempty list of nonnegative integers")
        for value in magnitudes:
            integer(value, "CSI magnitude")


@dataclass(frozen=True, kw_only=True)
class Trial:
    trial_id: str
    source: str
    channel: int | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        identifier(self.trial_id, "trial_id")
        if not isinstance(self.source, str) or self.source not in {"synthetic", "serial", "wisniff"}:
            raise ValueError("source must be synthetic, serial, or wisniff")
        channel_number(self.channel)
        if self.notes is not None and not isinstance(self.notes, str):
            raise ValueError("notes must be a string or null")


@dataclass(frozen=True, kw_only=True)
class Device:
    trial_id: str
    device_id: str
    mac: str | None = None
    device_kind: str | None = None

    def __post_init__(self) -> None:
        identifier(self.trial_id, "trial_id")
        identifier(self.device_id, "device_id")
        for name in ("mac", "device_kind"):
            if getattr(self, name) is not None:
                identifier(getattr(self, name), name)


@dataclass(frozen=True, kw_only=True)
class Pose:
    trial_id: str
    pose_id: str
    pose_index: int
    x_m: float | None = None
    y_m: float | None = None
    capture_start_ms: int | None = None
    capture_end_ms: int | None = None

    def __post_init__(self) -> None:
        identifier(self.trial_id, "trial_id")
        identifier(self.pose_id, "pose_id")
        integer(self.pose_index, "pose_index")
        for name in ("x_m", "y_m"):
            if getattr(self, name) is not None:
                finite(getattr(self, name), name)
        for name in ("capture_start_ms", "capture_end_ms"):
            if getattr(self, name) is not None:
                integer(getattr(self, name), name)
        if (self.capture_start_ms is None) != (self.capture_end_ms is None):
            raise ValueError("pose capture boundaries must both be present or both null")
        if self.capture_start_ms is not None and self.capture_end_ms <= self.capture_start_ms:
            raise ValueError("pose capture_end_ms must follow capture_start_ms")


@dataclass(frozen=True, kw_only=True)
class Observation:
    trial_id: str
    receiver_id: str
    sample_index: int
    device_id: str
    rssi_dbm: float
    pose_id: str | None = None
    device_time_ms: int | None = None
    host_time_utc: str | None = None
    channel: int | None = None
    csi_magnitudes: list[int] | None = None

    def __post_init__(self) -> None:
        for name in ("trial_id", "receiver_id", "device_id"):
            identifier(getattr(self, name), name)
        integer(self.sample_index, "sample_index")
        if self.pose_id is not None:
            identifier(self.pose_id, "pose_id")
        if self.device_time_ms is not None:
            integer(self.device_time_ms, "device_time_ms")
        if self.host_time_utc is not None:
            if not isinstance(self.host_time_utc, str):
                raise ValueError("host_time_utc must be an ISO-8601 UTC string or null")
            try:
                parsed = datetime.fromisoformat(self.host_time_utc.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("host_time_utc must be ISO-8601 UTC") from exc
            if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError("host_time_utc must include the UTC timezone")
        signal(self.rssi_dbm, self.channel, self.csi_magnitudes)


PHASES = frozenset({"CAPTURE_START", "CAPTURE_END", "MOVE_START", "MOVE_END", "SETTLE_START"})


@dataclass(frozen=True, kw_only=True)
class PositionEvent:
    trial_id: str
    receiver_id: str
    event_index: int
    device_time_ms: int
    pose_id: str
    phase: str

    def __post_init__(self) -> None:
        for name in ("trial_id", "receiver_id", "pose_id"):
            identifier(getattr(self, name), name)
        integer(self.event_index, "event_index")
        integer(self.device_time_ms, "device_time_ms")
        if not isinstance(self.phase, str) or self.phase not in PHASES:
            raise ValueError(f"unknown pose event phase: {self.phase}")


@dataclass(frozen=True, kw_only=True)
class RawSample:
    sample_index: int
    device_time_ms: int
    device_id: str
    rssi_dbm: float
    channel: int | None = None
    csi_magnitudes: list[int] | None = None

    def __post_init__(self) -> None:
        integer(self.sample_index, "sample_index")
        integer(self.device_time_ms, "device_time_ms")
        identifier(self.device_id, "device_id")
        signal(self.rssi_dbm, self.channel, self.csi_magnitudes)


@dataclass(frozen=True, kw_only=True)
class CaptureWindow:
    pose_id: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        identifier(self.pose_id, "pose_id")
        integer(self.start_ms, "start_ms")
        integer(self.end_ms, "end_ms")
        if self.end_ms <= self.start_ms:
            raise ValueError("capture window must have positive duration")


@dataclass(frozen=True, kw_only=True)
class Truth:
    trial_id: str
    device_id: str
    group_id: str

    def __post_init__(self) -> None:
        for name in ("trial_id", "device_id", "group_id"):
            identifier(getattr(self, name), name)


@dataclass(frozen=True, kw_only=True)
class RFState:
    trial_id: str
    receiver_id: str
    pose_id: str
    bin_index: int
    name: str

    def __post_init__(self) -> None:
        for name in ("trial_id", "receiver_id", "pose_id", "name"):
            identifier(getattr(self, name), name)
        integer(self.bin_index, "bin_index")


@dataclass(frozen=True, kw_only=True)
class StateEdge:
    trial_id: str
    device_id: str
    receiver_id: str
    pose_id: str
    bin_index: int
    weight: float

    def __post_init__(self) -> None:
        for name in ("trial_id", "device_id", "receiver_id", "pose_id"):
            identifier(getattr(self, name), name)
        integer(self.bin_index, "bin_index")
        finite(self.weight, "weight")
        if self.weight <= 0:
            raise ValueError("state edge weight must be positive")


@dataclass(frozen=True, kw_only=True)
class PoseRSSI:
    trial_id: str
    device_id: str
    receiver_id: str
    pose_id: str
    rssi_median_dbm: float
    packet_count: int
    rssi_relative_db: float
    eligible: bool = True

    def __post_init__(self) -> None:
        for name in ("trial_id", "device_id", "receiver_id", "pose_id"):
            identifier(getattr(self, name), name)
        signal(self.rssi_median_dbm, None, None)
        integer(self.packet_count, "packet_count", 1)
        finite(self.rssi_relative_db, "rssi_relative_db")
        if not isinstance(self.eligible, bool):
            raise ValueError("eligible must be boolean")


@dataclass(frozen=True, kw_only=True)
class Similarity:
    trial_id: str
    source_device_id: str
    target_device_id: str
    method: str
    score: float

    def __post_init__(self) -> None:
        for name in ("trial_id", "source_device_id", "target_device_id"):
            identifier(getattr(self, name), name)
        if not isinstance(self.method, str) or self.method not in {"rwr", "pearson"}:
            raise ValueError("similarity method must be rwr or pearson")
        finite(self.score, "score")


@dataclass(frozen=True, kw_only=True)
class Prediction:
    trial_id: str
    predicted_group_id: str
    device_id: str

    def __post_init__(self) -> None:
        for name in ("trial_id", "predicted_group_id", "device_id"):
            identifier(getattr(self, name), name)


@dataclass(frozen=True, kw_only=True)
class CaptureQuality:
    trial_id: str
    source_file: str
    total_rows: int
    accepted_rows: int
    excluded_rows: int
    counts_by_reason: dict[str, int]
    per_pose_counts: dict[str, int]
    warnings: list[str]

    def __post_init__(self) -> None:
        identifier(self.trial_id, "trial_id")
        for name in ("total_rows", "accepted_rows", "excluded_rows"):
            integer(getattr(self, name), name)
        if self.accepted_rows + self.excluded_rows != self.total_rows:
            raise ValueError("capture row counts do not add up")
        for count in [*self.counts_by_reason.values(), *self.per_pose_counts.values()]:
            integer(count, "quality count")


def as_record(value: Any) -> dict:
    """Convert any transport dataclass to a JSON-ready record."""
    return asdict(value)
