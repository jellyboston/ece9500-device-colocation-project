"""Direct Pearson comparator using only genuinely shared receiver poses."""

from __future__ import annotations

from itertools import combinations
from math import isfinite
from typing import Iterable

import numpy as np

from .models import PoseRSSI


def pearson_similarity(
    pose_rssi: Iterable[PoseRSSI], min_shared_poses: int = 3,
) -> dict[tuple[str, str], float]:
    """Score eligible devices on matching (receiver_id, pose_id) cells only.

    Undefined correlations (too little shared coverage or a constant vector)
    are omitted, so they cannot masquerade as evidence for a match. Valid
    negative correlations are preserved in the score table.
    """
    if isinstance(min_shared_poses, bool) or not isinstance(min_shared_poses, int) or min_shared_poses < 2:
        raise ValueError("Pearson min_shared_poses must be an integer of at least two")
    trials: set[str] = set()
    values: dict[str, dict[tuple[str, str], float]] = {}
    for row in pose_rssi:
        trials.add(row.trial_id)
        if not row.eligible:
            continue
        if not isfinite(row.rssi_relative_db):
            raise ValueError("Relative RSSI values must be finite for Pearson comparison")
        cells = values.setdefault(row.device_id, {})
        cell = row.receiver_id, row.pose_id
        if cell in cells:
            raise ValueError("Pearson input contains duplicate device/receiver/pose cells")
        cells[cell] = row.rssi_relative_db
    if len(trials) > 1:
        raise ValueError("Pearson comparison must contain only one trial")

    scores: dict[tuple[str, str], float] = {}
    for source, target in combinations(sorted(values), 2):
        shared = sorted(values[source].keys() & values[target].keys())
        if len(shared) < min_shared_poses:
            continue
        x = np.array([values[source][pose] for pose in shared], dtype=float)
        y = np.array([values[target][pose] for pose in shared], dtype=float)
        x -= x.mean()
        y -= y.mean()
        denominator = float(np.linalg.norm(x) * np.linalg.norm(y))
        if denominator == 0:
            continue
        score = float(np.clip(np.dot(x, y) / denominator, -1.0, 1.0))
        if not isfinite(score):
            raise ValueError("Pearson comparison produced a nonfinite score")
        scores[source, target] = score
        scores[target, source] = score
    return scores
