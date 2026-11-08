"""Deterministic random walks with restart on weighted bipartite graphs."""

from __future__ import annotations

from math import isfinite
from urllib.parse import unquote

import networkx as nx
import numpy as np


def transition_matrix(graph: nx.Graph) -> tuple[list[str], np.ndarray]:
    """Return a row-stochastic matrix over non-isolated nodes only."""
    if graph.is_directed() or graph.is_multigraph():
        raise ValueError("RWwR requires an undirected, simple weighted graph")
    for u, v, data in graph.edges(data=True):
        weight = data.get("weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not isfinite(weight) or weight <= 0:
            raise ValueError("RWwR graph weights must be finite and strictly positive")
        if u == v:
            raise ValueError("RWwR bipartite graphs cannot contain self loops")
    nodes = sorted(node for node in graph if graph.degree(node) > 0)
    if not nodes:
        return nodes, np.zeros((0, 0), dtype=float)
    adjacency = nx.to_numpy_array(graph, nodelist=nodes, weight="weight", dtype=float)
    sums = adjacency.sum(axis=1)
    if not np.all(np.isfinite(sums)) or np.any(sums <= 0):
        raise ValueError("Non-isolated graph rows require finite positive weight totals")
    transition = adjacency / sums[:, None]
    if not np.allclose(transition.sum(axis=1), 1.0, atol=1e-12, rtol=0):
        raise ValueError("RWwR transition rows do not sum to one")
    return nodes, transition


def compute_rwr_scores(
    graph: nx.Graph, alpha: float = 0.15, tol: float = 1e-10, max_iter: int = 1000,
) -> dict[tuple[str, str], float]:
    """Return directional stationary mass at every other device node.

    Zero scores for disconnected nodes remain explicit for inspection. They
    are never valid match candidates. Isolated devices are not walk sources.
    Diagnostic convergence information is attached to ``graph.graph['rwr']``.
    """
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not isfinite(alpha) or not 0 < alpha <= 1:
        raise ValueError("restart_probability must be finite and in (0, 1]")
    if isinstance(tol, bool) or not isinstance(tol, (int, float)) or not isfinite(tol) or tol <= 0:
        raise ValueError("RWwR tolerance must be finite and positive")
    if isinstance(max_iter, bool) or not isinstance(max_iter, int) or max_iter < 1:
        raise ValueError("RWwR max_iterations must be a positive integer")

    devices: dict[str, str] = {}
    for node, data in graph.nodes(data=True):
        if data.get("kind") == "device" or (isinstance(node, str) and node.startswith("D:")):
            device_id = data.get("device_id", unquote(node[2:]))
            if not isinstance(device_id, str) or not device_id:
                raise ValueError("Every device node needs a nonempty device_id")
            if device_id in devices:
                raise ValueError(f"Duplicate device node for {device_id!r}")
            devices[device_id] = node
    nodes, transition = transition_matrix(graph)
    indices = {node: index for index, node in enumerate(nodes)}
    scores = {(source, target): 0.0 for source in sorted(devices) for target in sorted(devices) if source != target}
    diagnostics = {"iterations_by_device": {}, "stationary_mass": {}, "isolated_devices": []}
    for source, node in sorted(devices.items()):
        if node not in indices:
            diagnostics["isolated_devices"].append(source)
            continue
        restart = np.zeros(len(nodes), dtype=float)
        restart[indices[node]] = 1.0
        probability = restart.copy()
        for iteration in range(1, max_iter + 1):
            next_probability = alpha * restart + (1.0 - alpha) * (transition.T @ probability)
            difference = float(np.linalg.norm(next_probability - probability, ord=1))
            probability = next_probability
            if difference < tol:
                break
        else:
            raise ValueError(f"RWwR did not converge for device {source!r} within {max_iter} iterations")
        if not np.all(np.isfinite(probability)) or np.any(probability < 0):
            raise ValueError(f"RWwR returned invalid probabilities for device {source!r}")
        mass = float(probability.sum())
        if not np.isclose(mass, 1.0, atol=1e-9, rtol=0):
            raise ValueError(f"RWwR probability mass for device {source!r} is {mass}, expected one")
        diagnostics["iterations_by_device"][source] = iteration
        diagnostics["stationary_mass"][source] = mass
        for target, target_node in sorted(devices.items()):
            if source != target and target_node in indices:
                scores[source, target] = float(probability[indices[target_node]])
    graph.graph["rwr"] = diagnostics
    return scores
