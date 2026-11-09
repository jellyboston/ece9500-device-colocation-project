"""Weighted device–RF-state graphs with one normalization per device."""

from __future__ import annotations

from collections import defaultdict
from math import fsum, isfinite
from typing import Iterable
from urllib.parse import quote

import networkx as nx

from .models import StateEdge


def device_node_id(device_id: str) -> str:
    """Escape separators so arbitrary experiment IDs cannot collide."""
    return "D:" + quote(device_id, safe="")


def state_node_id(trial_id: str, receiver_id: str, pose_id: str, bin_index: int) -> str:
    parts = (trial_id, receiver_id, pose_id, str(bin_index))
    return "S:" + ":".join(quote(part, safe="") for part in parts)


def build_bipartite_graph(edges: Iterable[StateEdge]) -> nx.Graph:
    """Sum duplicate associations, then normalize incident weights per device.

    The normalized value is stored on one undirected edge and is reused in
    both directions. Row-normalizing the resulting adjacency for RWwR is a
    separate operation; it must not repeat the device degree correction.
    """
    associations: dict[tuple[str, str, str, str, int], list[float]] = defaultdict(list)
    trials: set[str] = set()
    for edge in edges:
        if isinstance(edge.weight, bool) or not isfinite(edge.weight) or edge.weight <= 0:
            raise ValueError("State edge weights must be finite and strictly positive")
        trials.add(edge.trial_id)
        key = (edge.trial_id, edge.device_id, edge.receiver_id, edge.pose_id, edge.bin_index)
        associations[key].append(float(edge.weight))
    if len(trials) > 1:
        raise ValueError("A bipartite graph must contain only one trial")

    raw = {key: fsum(values) for key, values in associations.items()}
    device_weights: dict[str, list[float]] = defaultdict(list)
    for key, weight in raw.items():
        device_weights[key[1]].append(weight)
    totals = {device: fsum(weights) for device, weights in device_weights.items()}
    if any(not isfinite(total) or total <= 0 for total in totals.values()):
        raise ValueError("The total state edge weight must be finite and positive")

    graph = nx.Graph()
    graph.graph["weight_normalization"] = "per_device_total"
    if trials:
        graph.graph["trial_id"] = next(iter(trials))
    for device in sorted(totals):
        graph.add_node(device_node_id(device), kind="device", bipartite=0, device_id=device)
    for (trial, device, receiver, pose, bin_index), weight in sorted(raw.items()):
        state = state_node_id(trial, receiver, pose, bin_index)
        graph.add_node(
            state, kind="state", bipartite=1, trial_id=trial,
            receiver_id=receiver, pose_id=pose, bin_index=bin_index,
        )
        graph.add_edge(
            device_node_id(device), state, weight=weight / totals[device], raw_weight=weight,
        )
    return graph
