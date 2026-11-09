"""Independent partition evaluation; ground truth enters only this module."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, is_dataclass
from itertools import combinations
from typing import Any, Iterable, Mapping


def _partition(groups: Iterable[Iterable[str]], name: str) -> tuple[list[list[str]], set[str]]:
    if not isinstance(groups, (list, tuple)):
        raise ValueError(f"{name} groups must be a list of device-ID lists")
    result: list[list[str]] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, (list, tuple)) or not group:
            raise ValueError(f"{name} groups must be nonempty lists")
        if any(not isinstance(device, str) or not device for device in group):
            raise ValueError(f"{name} device IDs must be nonempty strings")
        if len(set(group)) != len(group) or seen.intersection(group):
            raise ValueError(f"{name} must assign each device to exactly one group")
        result.append(sorted(group))
        seen.update(group)
    return sorted(result, key=tuple), seen


def _pairs(groups: list[list[str]]) -> set[tuple[str, str]]:
    return {pair for group in groups for pair in combinations(group, 2)}


def score_groups(predictions: Any, truth: Any) -> dict[str, Any]:
    """Return pairwise precision/recall/F1 and absolute group-count error.

    Predictions may be a groups list or a JSON object with ``groups`` and
    optional ``trial_id``. Truth is a list of schema Truth records (dataclass
    instances or dictionaries), optionally wrapped as ``{"truth": [...]}``.
    Device sets must match exactly; missing devices cannot improve metrics.

    An empty predicted-positive set has precision 1 only when truth also has
    no positives; otherwise precision is 0. Empty truth positives have recall
    1. Thus identical singleton-only partitions receive F1=1.
    """
    prediction_trial = None
    if isinstance(predictions, Mapping):
        prediction_trial = predictions.get("trial_id")
        if "groups" not in predictions:
            raise ValueError("Prediction JSON must contain 'groups'")
        predictions = predictions["groups"]
    predicted_groups, predicted_ids = _partition(predictions, "Prediction")
    if isinstance(truth, Mapping):
        if "truth" not in truth:
            raise ValueError("Truth JSON must be a record list or contain 'truth'")
        truth = truth["truth"]
    if not isinstance(truth, (list, tuple)):
        raise ValueError("Truth must be a list of trial_id/device_id/group_id records")
    truth_groups: dict[str, list[str]] = defaultdict(list)
    truth_ids: set[str] = set()
    trials: set[str] = set()
    for item in truth:
        row = asdict(item) if is_dataclass(item) and not isinstance(item, type) else item
        if not isinstance(row, Mapping):
            raise ValueError("Each truth record must be an object")
        for field in ("trial_id", "device_id", "group_id"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError(f"Truth records require a nonempty {field}")
        device = row["device_id"]
        if device in truth_ids:
            raise ValueError(f"Truth assigns device {device!r} more than once")
        truth_ids.add(device)
        trials.add(row["trial_id"])
        truth_groups[row["group_id"]].append(device)
    if len(trials) > 1:
        raise ValueError("Evaluation must compare one trial at a time")
    if prediction_trial is not None and trials and prediction_trial not in trials:
        raise ValueError("Prediction and truth trial IDs do not match")
    if predicted_ids != truth_ids:
        raise ValueError(
            "Prediction and truth device sets do not match: "
            f"missing predictions={sorted(truth_ids - predicted_ids)}, "
            f"unknown predictions={sorted(predicted_ids - truth_ids)}"
        )
    actual_groups = sorted((sorted(group) for group in truth_groups.values()), key=tuple)
    predicted_pairs = _pairs(predicted_groups)
    actual_pairs = _pairs(actual_groups)
    true_positive = len(predicted_pairs & actual_pairs)
    false_positive = len(predicted_pairs - actual_pairs)
    false_negative = len(actual_pairs - predicted_pairs)
    precision = true_positive / len(predicted_pairs) if predicted_pairs else float(not actual_pairs)
    recall = true_positive / len(actual_pairs) if actual_pairs else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "pairwise_precision": precision,
        "pairwise_recall": recall,
        "pairwise_f1": f1,
        "count_absolute_error": abs(len(predicted_groups) - len(actual_groups)),
        "predicted_group_count": len(predicted_groups),
        "true_group_count": len(actual_groups),
        "device_count": len(truth_ids),
        "true_positive_pairs": true_positive,
        "false_positive_pairs": false_positive,
        "false_negative_pairs": false_negative,
        "empty_pair_convention": "precision=1 only if both pair sets empty; recall=1 if truth pairs empty",
    }
