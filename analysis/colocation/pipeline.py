"""Source-independent inference. This module never imports synthetic or truth code."""

from dataclasses import dataclass

import networkx as nx

from .baseline import pearson_similarity
from .config import validate_config
from .features import aggregate_by_pose, encode_rssi_states
from .graph import build_bipartite_graph
from .grouping import clique_constellations, mutual_topk
from .models import Device, Observation, PoseRSSI
from .rwr import compute_rwr_scores


@dataclass
class InferenceResult:
    trial_id: str
    devices: list[str]
    groups: list[list[str]]
    baseline_groups: list[list[str]]
    summary: dict
    rwr_scores: dict[tuple[str, str], float]
    pearson_scores: dict[tuple[str, str], float]
    pose_rssi: list[PoseRSSI]
    bipartite_graph: nx.Graph
    similarity_graph: nx.Graph


def infer_observations(
    observations: list[Observation], config: dict, devices: list[Device] | None = None,
) -> InferenceResult:
    validate_config(config)
    trials = {row.trial_id for row in observations}
    if devices is not None:
        trials.update(row.trial_id for row in devices)
        keys = [(row.trial_id, row.device_id) for row in devices]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate device manifest key")
    if len(trials) != 1:
        raise ValueError("inference requires exactly one trial; check manifest and observation trial IDs")
    trial_id = next(iter(trials))
    observed_ids = {row.device_id for row in observations}
    all_devices = sorted(observed_ids | {row.device_id for row in devices or []})
    
    pose_rssi, quality = aggregate_by_pose(observations, config)
    missing_ids = sorted(set(all_devices) - observed_ids)
    quality["low_coverage_devices"] = sorted(set(quality["low_coverage_devices"]) | set(missing_ids))
    for device in missing_ids:
        quality["per_device"][device] = {"packet_count": 0, "retained_pose_count": 0, "eligible": False}
        quality["warnings"].append(f"Manifest device {device} has no samples: emitted as a singleton")
    quality["per_device"] = dict(sorted(quality["per_device"].items()))
    if devices is None:
        quality["warnings"].append("No device manifest: fully unseen transmitters cannot be discovered")
    graph = build_bipartite_graph(encode_rssi_states(pose_rssi, config))
    rwr = config["rwr"]
    scores = compute_rwr_scores(graph, rwr["restart_probability"], rwr["tolerance"], rwr["max_iterations"])
    grouping = config["grouping"]
    similarity_graph = mutual_topk(scores, grouping["max_devices_per_group"], grouping["min_directional_similarity"])
    groups = clique_constellations(similarity_graph, all_devices, grouping["max_devices_per_group"])
    pearson = pearson_similarity(pose_rssi, config["rssi"]["min_shared_poses"])
    # The specified comparator uses mutual top-1 even when the graph uses K > 2.
    baseline_graph = mutual_topk(pearson, 2, 0.0)
    baseline_groups = clique_constellations(baseline_graph, all_devices, 2)
    eligible_count = sum(item["eligible"] for item in quality["per_device"].values())
    if eligible_count < 2:
        quality["warnings"].append("Fewer than two eligible transmitters: insufficient evidence to evaluate colocation grouping")
    summary = {
        "trial_id": trial_id,
        "device_count": len(all_devices),
        "observed_device_count": len(observed_ids),
        "eligible_device_count": eligible_count,
        "receiver_ids": sorted({row.receiver_id for row in observations}),
        "pose_ids": sorted({row.pose_id for row in observations}),
        "quality": quality,
        "rwr_diagnostics": graph.graph.get("rwr", {}),
        "grouping": dict(similarity_graph.graph),
        "baseline": {"method": "pearson", "max_devices_per_group": 2, "groups": baseline_groups},
    }
    return InferenceResult(
        trial_id=trial_id, devices=all_devices, groups=groups, baseline_groups=baseline_groups,
        summary=summary, rwr_scores=scores, pearson_scores=pearson,
        pose_rssi=pose_rssi, bipartite_graph=graph, similarity_graph=similarity_graph,
    )
