import math

import networkx as nx
import numpy as np
import pytest

from colocation.graph import build_bipartite_graph, device_node_id, state_node_id
from colocation.models import StateEdge
from colocation.rwr import compute_rwr_scores, transition_matrix


def edge(device, pose="P1", weight=1, receiver="RX", trial="trial"):
    return StateEdge(
        trial_id=trial, device_id=device, receiver_id=receiver,
        pose_id=pose, bin_index=0, weight=weight,
    )


def test_duplicate_counts_normalize_once_before_state_transitions():
    graph = build_bipartite_graph([
        edge("A", "P1", 2), edge("A", "P1", 3), edge("A", "P2", 5),
        edge("B", "P1", 20),
    ])
    a, b = device_node_id("A"), device_node_id("B")
    state = state_node_id("trial", "RX", "P1", 0)
    assert sum(data["weight"] for _, _, data in graph.edges(a, data=True)) == pytest.approx(1)
    assert graph[a][state]["raw_weight"] == 5
    assert graph[a][state]["weight"] == pytest.approx(0.5)
    assert graph[b][state]["weight"] == pytest.approx(1)
    nodes, transition = transition_matrix(graph)
    np.testing.assert_allclose(transition.sum(axis=1), 1, rtol=0, atol=1e-12)
    assert transition[nodes.index(state), nodes.index(a)] == pytest.approx(1 / 3)
    assert transition[nodes.index(state), nodes.index(b)] == pytest.approx(2 / 3)


def test_rwr_matches_closed_form_two_devices_sharing_one_state():
    graph = build_bipartite_graph([edge("a"), edge("b")])
    scores = compute_rwr_scores(graph, alpha=0.15, tol=1e-12, max_iter=1000)
    expected = 0.85**2 / (2 * (2 - 0.15))
    assert scores["a", "b"] == pytest.approx(expected, abs=1e-11)
    assert scores["b", "a"] == pytest.approx(expected, abs=1e-11)
    assert set(scores) == {("a", "b"), ("b", "a")}
    assert all(mass == pytest.approx(1) for mass in graph.graph["rwr"]["stationary_mass"].values())


def test_shared_states_outrank_unreachable_devices_and_isolates_are_omitted():
    rows = [edge("a"), edge("b"), edge("c", "other")]
    graph = build_bipartite_graph(rows)
    graph.add_node("D:empty", kind="device", device_id="empty")
    scores = compute_rwr_scores(graph)
    assert scores["a", "b"] > scores["a", "c"] == 0
    assert scores["a", "empty"] == scores["empty", "a"] == 0
    assert graph.graph["rwr"]["isolated_devices"] == ["empty"]
    reordered = build_bipartite_graph(list(reversed(rows)))
    reordered.add_node("D:empty", kind="device", device_id="empty")
    assert compute_rwr_scores(reordered) == scores


def test_empty_graph_and_restart_only_walk_are_defined():
    assert compute_rwr_scores(nx.Graph()) == {}
    graph = build_bipartite_graph([edge("a"), edge("b")])
    assert set(compute_rwr_scores(graph, alpha=1).values()) == {0}


def test_namespace_escaping_prevents_separator_collisions():
    graph = build_bipartite_graph([
        edge("D:S:1", pose="c", receiver="a:b"),
        edge("D:S:1", pose="b:c", receiver="a"),
    ])
    assert graph.number_of_nodes() == 3
    assert device_node_id("a:b") != device_node_id("a%3Ab")
    assert state_node_id("t", "a:b", "c", 0) != state_node_id("t", "a", "b:c", 0)


def test_mixed_trials_and_invalid_weights_fail():
    with pytest.raises(ValueError, match="one trial"):
        build_bipartite_graph([edge("a", trial="first"), edge("b", trial="second")])
    graph = nx.Graph()
    graph.add_edge("D:a", "S:a", weight=-1)
    with pytest.raises(ValueError, match="positive"):
        compute_rwr_scores(graph)


@pytest.mark.parametrize("kwargs", [
    {"alpha": 0}, {"alpha": math.nan}, {"alpha": 1.1},
    {"tol": 0}, {"max_iter": 0}, {"max_iter": True},
    {"alpha": "0.15"}, {"alpha": []}, {"tol": "small"}, {"tol": []},
])
def test_invalid_walk_configuration_fails(kwargs):
    with pytest.raises(ValueError):
        compute_rwr_scores(nx.Graph(), **kwargs)


def test_nonconvergence_is_reported_instead_of_returning_inaccurate_scores():
    graph = build_bipartite_graph([edge("a"), edge("b")])
    with pytest.raises(ValueError, match="did not converge"):
        compute_rwr_scores(graph, max_iter=1)


@pytest.mark.parametrize("weight", ["1", [], True])
def test_mistyped_walk_weights_raise_clear_value_errors(weight):
    graph = nx.Graph()
    graph.add_edge("D:a", "S:a", weight=weight)
    with pytest.raises(ValueError, match="weights"):
        compute_rwr_scores(graph)
