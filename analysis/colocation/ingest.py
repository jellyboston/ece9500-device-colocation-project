"""Adapters for exploratory captures; these never invent position or time data."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import re

from .models import Observation, RawSample


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer >= {minimum}")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        result = int(value)
    else:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    if result < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return result


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _rssi(value: object) -> float:
    result = _number(value, "rssi_dbm")
    if not -120 <= result <= 0:
        raise ValueError("rssi_dbm must be between -120 and 0 dBm")
    return result


def _channel(value: object) -> int:
    result = _integer(value, "channel", minimum=1)
    if result > 14:
        raise ValueError("channel must be between 1 and 14")
    return result


def _magnitudes(value: object) -> list[int]:
    if not isinstance(value, list) or not value or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value
    ):
        raise ValueError("csi_magnitudes must be a nonempty array of nonnegative integers")
    return list(value)


def load_wisniff(
    path: str | Path,
    *,
    trial_id: str = "wisniff001",
    receiver_id: str = "RX1",
) -> list[Observation]:
    """Read a WiSniff scan, replacing MACs with deterministic scan-local aliases.

    Alias numbers have no identity meaning across captures. Source MACs are used
    transiently to recognize repeated records, and are never returned or logged.
    """
    trial_id = _identifier(trial_id, "trial_id")
    receiver_id = _identifier(receiver_id, "receiver_id")
    with Path(path).open(encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"WiSniff input is not valid JSON (line {exc.lineno})") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
        raise ValueError("WiSniff JSON must contain a devices array")
    records = payload["devices"]
    validated: list[tuple[str, float, int]] = []
    for row_index, record in enumerate(records):
        try:
            if not isinstance(record, dict):
                raise ValueError("each devices entry must be an object")
            mac = _identifier(record.get("mac"), "mac")
            if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
                raise ValueError("mac must use six colon-separated hexadecimal octets")
            if isinstance(record.get("rssi"), bool) or not isinstance(record.get("rssi"), (int, float)):
                raise ValueError("rssi must be numeric in WiSniff JSON")
            if isinstance(record.get("channel"), bool) or not isinstance(record.get("channel"), int):
                raise ValueError("channel must be an integer in WiSniff JSON")
            validated.append((mac.lower(), _rssi(record.get("rssi")), _channel(record.get("channel"))))
        except ValueError as exc:
            raise ValueError(f"WiSniff record {row_index}: {exc}") from exc
    aliases = {mac: f"W{index:03d}" for index, mac in enumerate(sorted({row[0] for row in validated}), 1)}
    return [
        Observation(
            trial_id=trial_id,
            receiver_id=receiver_id,
            sample_index=index,
            device_id=aliases[mac],
            rssi_dbm=rssi,
            channel=channel,
        )
        for index, (mac, rssi, channel) in enumerate(validated)
    ]


def _parse_csi_row(row: list[str], sample_index: int, device_id: str) -> RawSample:
    if len(row) < 6 or row[0].strip() != "CSI":
        raise ValueError("expected CSI,<millis>,<RSSI>,<channel>,<n>,0,<n magnitudes>")
    count = _integer(row[4], "n_subcarriers", minimum=1)
    if row[5].strip() != "0":
        raise ValueError("CSI sentinel at column 6 must be the literal 0")
    if len(row) != 6 + count:
        raise ValueError(f"CSI n_subcarriers={count} requires {count} magnitudes; found {len(row) - 6}")
    return RawSample(
        sample_index=sample_index,
        device_time_ms=_integer(row[1], "device_time_ms"),
        device_id=device_id,
        rssi_dbm=_rssi(row[2]),
        channel=_channel(row[3]),
        csi_magnitudes=[_integer(item, "CSI magnitude") for item in row[6:]],
    )


def _load_csi_samples(path: str | Path, device_id: str) -> list[RawSample]:
    device_id = _identifier(device_id, "device_id")
    samples: list[RawSample] = []
    previous_time = -1
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, strict=True)
        try:
            for row in reader:
                if not row or not any(cell.strip() for cell in row) or row[0].lstrip().startswith("#"):
                    continue
                try:
                    sample = _parse_csi_row(row, len(samples), device_id)
                    if sample.device_time_ms < previous_time:
                        raise ValueError("device_time_ms decreased: possible receiver clock reset/wrap; split the trial explicitly")
                except ValueError as exc:
                    raise ValueError(f"CSI input line {reader.line_num}: {exc}") from exc
                samples.append(sample)
                previous_time = sample.device_time_ms
        except csv.Error as exc:
            raise ValueError(f"CSI input line {reader.line_num}: malformed CSV") from exc
    if not samples:
        raise ValueError("CSI input contains no sample rows")
    return samples


def load_csi_csv(
    path: str | Path,
    trial_id: str,
    receiver_id: str,
    device_id: str,
) -> list[Observation]:
    """Read an operator-attributed single-TX log, retaining unknown poses.

    Supplying ``device_id`` is the operator's single-known-transmitter assertion
    for this exploratory API. The positioned capture API requires the explicit
    ``single_known_transmitter`` flag as well.
    """
    trial_id = _identifier(trial_id, "trial_id")
    receiver_id = _identifier(receiver_id, "receiver_id")
    return [
        Observation(
            trial_id=trial_id,
            receiver_id=receiver_id,
            sample_index=sample.sample_index,
            device_id=sample.device_id,
            rssi_dbm=sample.rssi_dbm,
            device_time_ms=sample.device_time_ms,
            channel=sample.channel,
            csi_magnitudes=sample.csi_magnitudes,
        )
        for sample in _load_csi_samples(path, device_id)
    ]
