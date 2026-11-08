from itertools import combinations

import networkx as nx
import pytest

from colocation.baseline import pearson_similarity
from colocation.grouping import clique_constellations, mutual_topk
from colocation.models import PoseRSSI


def scores_for_pairs(devices, pairs, background=0.01):
    scores = {(a, b): background for a in devices for b in devices if a != b}
    for a, b in pairs:
        scores[a, b] = 0.8
        scores[b, a] = 0.7
    return scores


def test_mutual_top_one_retains_pairs_and_thresholded_singleton():
    devices = ["phone-B", "watch-B", "tablet-A", "laptop-A", "solo"]
    scores = scores_for_pairs(devices, [("phone-B", "watch-B"), ("tablet-A", "laptop-A")])
    graph = mutual_topk(scores, max_devices=2, min_score=0.05)
    assert clique_constellations(graph, devices, 2) == [
        ["laptop-A", "tablet-A"], ["phone-B", "watch-B"], ["solo"],
    ]
    assert all(len(candidates) <= 1 for candidates in graph.graph["candidate_lists"].values())


def test_one_way_nominations_and_zero_scores_never_match():
    graph = mutual_topk({("A", "B"): 0.9, ("B", "A"): 0.1, ("B", "C"): 0.8, ("C", "B"): 0}, 2, 0)
    assert graph.number_of_edges() == 0
    assert clique_constellations(graph, ["A", "B", "C", "no-samples"], 2) == [
        ["A"], ["B"], ["C"], ["no-samples"],
    ]
    assert mutual_topk({("A", "B"): 0, ("B", "A"): 0}, 2, 0).number_of_edges() == 0


def test_stable_lexicographic_ties_do_not_depend_on_input_order():
    scores = {(a, b): 0.5 for a in ["z", "a", "m"] for b in ["m", "z", "a"] if a != b}
    forward = mutual_topk(scores, 2, 0)
    reverse = mutual_topk(dict(reversed(list(scores.items()))), 2, 0)
    assert forward.graph["candidate_lists"] == reverse.graph["candidate_lists"]
    assert set(forward.edges) == set(reverse.edges) == {("a", "m")}


def test_two_triples_form_cliques_with_k_three():
    groups = [("alpha", "beta", "gamma"), ("delta", "epsilon", "zeta")]
    devices = [device for group in groups for device in group]
    scores = {(a, b): 0.001 for a in devices for b in devices if a != b}
    for group in groups:
        for a, b in combinations(group, 2):
            scores[a, b] = scores[b, a] = 0.3
    graph = mutual_topk(scores, max_devices=3, min_score=0)
    assert clique_constellations(graph, devices, 3) == [list(group) for group in groups]
    assert all(len(candidates) == 2 for candidates in graph.graph["candidate_lists"].values())


def test_overlap_policy_uses_size_score_and_lexicographic_order():
    graph = nx.Graph()
    graph.add_weighted_edges_from([("A", "B", 1), ("A", "C", 1), ("B", "C", 1), ("C", "D", 100)])
    assert clique_constellations(graph, ["A", "B", "C", "D"], 3) == [["A", "B", "C"], ["D"]]
    assert graph.graph["overlap_conflict_count"] == 1
    assert "descending_size" in graph.graph["overlap_policy"]
    path = nx.Graph()
    path.add_weighted_edges_from([("A", "B", 1), ("B", "C", 2)])
    assert clique_constellations(path, ["A", "B", "C"], 3) == [["A"], ["B", "C"]]
    path["A"]["B"]["weight"] = 2
    assert clique_constellations(path, ["A", "B", "C"], 3) == [["A", "B"], ["C"]]


def test_no_connected_component_shortcut_and_no_forced_grouping():
    graph = nx.path_graph(["A", "B", "C", "D"])
    groups = clique_constellations(graph, ["A", "B", "C", "D", "unseen"], 3)
    assert ["A", "B", "C", "D"] not in groups
    assert sorted(device for group in groups for device in group) == ["A", "B", "C", "D", "unseen"]
    assert ["unseen"] in groups


def row(device, pose, value, receiver="RX", eligible=True):
    return PoseRSSI(
        trial_id="trial", device_id=device, receiver_id=receiver, pose_id=pose,
        rssi_median_dbm=-60 + value, packet_count=10,
        rssi_relative_db=value, eligible=eligible,
    )


def test_pearson_uses_only_shared_receiver_pose_cells():
    rows = [row("A", f"P{i}", value) for i, value in enumerate([-2, 0, 2])]
    rows += [row("B", f"P{i}", value) for i, value in enumerate([-4, 0, 4])]
    rows += [row("C", f"P{i}", value, receiver="other") for i, value in enumerate([-2, 0, 2])]
    rows += [row("A", "unshared", 49)]
    result = pearson_similarity(rows, min_shared_poses=3)
    assert result["A", "B"] == pytest.approx(1)
    assert result["B", "A"] == pytest.approx(1)
    assert not any("C" in pair for pair in result)


def test_pearson_skips_constant_insufficient_and_ineligible_data():
    rows = [row("A", f"P{i}", v) for i, v in enumerate([-1, 0, 1])]
    rows += [row("constant", f"P{i}", 0) for i in range(3)]
    rows += [row("sparse", "P0", -1), row("sparse", "P1", 1)]
    rows += [row("ineligible", f"P{i}", v, eligible=False) for i, v in enumerate([-1, 0, 1])]
    assert pearson_similarity(rows) == {}


@pytest.mark.parametrize("kwargs", [
    {"max_devices": 1}, {"max_devices": True}, {"min_score": -1},
    {"min_score": "0.1"}, {"min_score": []},
])
def test_invalid_grouping_configuration_fails(kwargs):
    with pytest.raises(ValueError):
        mutual_topk({}, **kwargs)


@pytest.mark.parametrize("score", ["0.5", [], True])
def test_mistyped_similarity_values_raise_clear_value_errors(score):
    with pytest.raises(ValueError, match="scores"):
        mutual_topk({("A", "B"): score})
