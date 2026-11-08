"""Canonical JSON storage with contextual schema errors."""

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .models import Device, Observation, Pose


def read_json(path: str | Path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def _json_default(value):
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def write_json(path: str | Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, default=_json_default, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_observations(path: str | Path, observations: list[Observation]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in observations:
            stream.write(json.dumps(asdict(row), sort_keys=True, allow_nan=False) + "\n")


def load_observations(path: str | Path) -> list[Observation]:
    observations = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("each observation must be an object")
                observations.append(Observation(**record))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}, line {line_number}: {exc}") from exc
    return observations


def _load_manifest(path: str | Path, model, key: str):
    records = read_json(path)
    if not isinstance(records, list):
        raise ValueError(f"{path}: manifest must be an array of records")
    parsed, seen = [], set()
    for index, record in enumerate(records):
        try:
            if not isinstance(record, dict):
                raise ValueError("manifest row must be an object")
            row = model(**record)
            primary_key = row.trial_id, getattr(row, key)
            if primary_key in seen:
                raise ValueError(f"duplicate manifest key: {primary_key}")
            seen.add(primary_key)
            parsed.append(row)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path}, record {index}: {exc}") from exc
    return parsed


def load_devices(path: str | Path) -> list[Device]:
    return _load_manifest(path, Device, "device_id")


def load_poses(path: str | Path) -> list[Pose]:
    rows = _load_manifest(path, Pose, "pose_id")
    indices = [(row.trial_id, row.pose_index) for row in rows]
    if len(set(indices)) != len(indices):
        raise ValueError(f"{path}: duplicate pose_index")
    return rows
