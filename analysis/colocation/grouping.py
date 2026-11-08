"""Mutual candidates and deterministic, disjoint maximal-clique selection."""

from __future__ import annotations

from itertools import combinations
from math import fsum, isfinite
from typing import Iterable, Mapping

import networkx as nx


OVERLAP_POLICY = "descending_size_then_summed_bidirectional_score_then_lexicographic; greedy_disjoint"


def _validate_max_devices(max_devices: int) -> None:
    if isinstance(max_devices, bool) or not isinstance(max_devices, int) or max_devices < 2:
        raise ValueError("max_devices_per_group must be an integer of at least two")


def mutual_topk(
    scores: Mapping[tuple[str, str], float], max_devices: int = 2, min_score: float = 0.0,
) -> nx.Graph:
    """Connect mutually nominated positive-scoring device pairs.

    ``max_devices`` is GraphTrack's group-size bound K, so each source
    nominates at most K−1 candidates. Lexicographic IDs break exact ties.
    Edge weights are the sum of the two accepted directional scores.
    """
    _validate_max_devices(max_devices)
    if isinstance(min_score, bool) or not isinstance(min_score, (int, float)) or not isfinite(min_score) or min_score < 0:
        raise ValueError("min_directional_similarity must be finite and nonnegative")
    devices: set[str] = set()
    for pair, score in scores.items():
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise ValueError("Similarity keys must be (source_device_id, target_device_id) pairs")
        if any(not isinstance(device, str) or not device for device in pair):
            raise ValueError("Similarity device IDs must be nonempty strings")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not isfinite(score):
            raise ValueError("Similarity scores must be finite numbers")
        devices.update(pair)

    ordered = sorted(devices)
    candidate_count = min(max_devices - 1, max(0, len(ordered) - 1))
    candidates: dict[str, list[str]] = {}
    for source in ordered:
        ranked = [
            (target, float(scores[source, target]))
            for target in ordered
            if source != target and scores.get((source, target), 0.0) > 0
        ]
        ranked.sort(key=lambda item: (-item[1], item[0]))
        candidates[source] = [target for target, _ in ranked[:candidate_count]]

    graph = nx.Graph()
    graph.add_nodes_from(ordered)
    graph.graph.update(
        candidate_lists=candidates,
        max_devices_per_group=max_devices,
        min_directional_similarity=float(min_score),
    )
    for source, target in combinations(ordered, 2):
        forward = float(scores.get((source, target), 0.0))
        reverse = float(scores.get((target, source), 0.0))
        if (
            target in candidates[source] and source in candidates[target]
            and forward > 0 and reverse > 0
            and forward >= min_score and reverse >= min_score
        ):
            graph.add_edge(
                source, target, weight=fsum((forward, reverse)),
                source_to_target=forward, target_to_source=reverse,
            )
    return graph


def clique_constellations(
    graph: nx.Graph, all_devices: Iterable[str], max_devices: int = 2,
) -> list[list[str]]:
    """Select maximal cliques greedily and retain every unmatched singleton.

    This prototype policy never merges a connected component unless it is
    also a clique. Overlapping candidates are discarded as whole cliques;
    their unassigned members become singletons rather than new subcliques.
    """
    _validate_max_devices(max_devices)
    if graph.is_directed() or graph.is_multigraph():
        raise ValueError("Clique grouping requires an undirected, simple similarity graph")
    devices = set(all_devices)
    if any(not isinstance(device, str) or not device for device in devices):
        raise ValueError("All device IDs must be nonempty strings")
    unknown = set(graph) - devices
    if unknown:
        raise ValueError(f"Similarity graph contains IDs missing from all_devices: {sorted(unknown)}")
    if nx.number_of_selfloops(graph):
        raise ValueError("Similarity graphs cannot contain self loops")
    for _, _, edge in graph.edges(data=True):
        weight = edge.get("weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not isfinite(weight) or weight <= 0:
            raise ValueError("Clique edge weights must be finite and positive")

    def key(clique: tuple[str, ...]) -> tuple[int, float, tuple[str, ...]]:
        mutual_sum = fsum(graph[u][v].get("weight", 1.0) for u, v in combinations(clique, 2))
        return -len(clique), -mutual_sum, clique

    candidates = sorted((tuple(sorted(c)) for c in nx.find_cliques(graph)), key=key)
    groups: list[list[str]] = []
    assigned: set[str] = set()
    overlap_conflicts = 0
    oversized = 0
    for clique in candidates:
        if len(clique) > max_devices:
            oversized += 1
            continue
        if assigned.intersection(clique):
            overlap_conflicts += 1
            continue
        groups.append(list(clique))
        assigned.update(clique)
    groups.extend([device] for device in sorted(devices - assigned))
    groups.sort(key=tuple)
    graph.graph.update(
        overlap_policy=OVERLAP_POLICY,
        overlap_conflict_count=overlap_conflicts,
        oversized_clique_count=oversized,
        candidate_clique_count=len(candidates),
    )
    return groups
