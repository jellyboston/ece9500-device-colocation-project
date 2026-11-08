"""Static report figures with labels, units, and deterministic graph layouts."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ece9500-matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np


def _save(fig, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_rssi_by_pose(rows, path, poses=None) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    pose_ids = sorted({row.pose_id for row in rows})
    if poses:
        pose_ids = [row.pose_id for row in sorted(poses, key=lambda row: row.pose_index)]
    order = {pose: index for index, pose in enumerate(pose_ids)}
    for device, receiver in sorted({(row.device_id, row.receiver_id) for row in rows}):
        values = sorted(
            [row for row in rows if (row.device_id, row.receiver_id) == (device, receiver)],
            key=lambda row: order[row.pose_id],
        )
        ax.plot([order[row.pose_id] for row in values], [row.rssi_median_dbm for row in values], "o-", label=f"{device} ({receiver})")
    if rows:
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "No pose cells passed the packet-count gate", ha="center", transform=ax.transAxes)
    ax.set_xticks(range(len(pose_ids)), pose_ids, rotation=45)
    ax.set(xlabel="Receiver pose (manifest order when available)", ylabel="Median RSSI (dBm)", title="RSSI trajectory by receiver pose")
    ax.grid(alpha=0.25)
    _save(fig, path)


def plot_similarity_heatmap(scores, devices, path) -> None:
    fig, ax = plt.subplots(figsize=(max(5, len(devices) * 0.6), max(4, len(devices) * 0.55)))
    matrix = np.array([[scores.get((source, target), 0.0) if source != target else np.nan for target in devices] for source in devices])
    image = ax.imshow(np.ma.masked_invalid(matrix), cmap="viridis", vmin=0, vmax=max(0.01, max(scores.values(), default=0)))
    ax.set_xticks(range(len(devices)), devices, rotation=45, ha="right")
    ax.set_yticks(range(len(devices)), devices)
    ax.set(xlabel="Target device", ylabel="Restart/source device", title="Directional RWwR probability at device nodes")
    fig.colorbar(image, ax=ax, label="Stationary probability (unitless)")
    _save(fig, path)


def plot_bipartite_graph(graph, path) -> None:
    devices = sorted(node for node, attrs in graph.nodes(data=True) if attrs.get("kind") == "device")
    states = sorted(set(graph.nodes) - set(devices))
    fig, ax = plt.subplots(figsize=(12, max(5, min(18, len(states) * 0.24))))
    pos = {node: (0, index / max(1, len(devices) - 1)) for index, node in enumerate(devices)}
    pos.update({node: (1, index / max(1, len(states) - 1)) for index, node in enumerate(states)})
    nx.draw_networkx_edges(graph, pos, ax=ax, alpha=0.3, width=0.7)
    nx.draw_networkx_nodes(graph, pos, nodelist=devices, node_color="#3b82f6", node_size=350, ax=ax)
    nx.draw_networkx_nodes(graph, pos, nodelist=states, node_color="#cbd5e1", node_size=45, ax=ax)
    for node, (x, y) in pos.items():
        label = graph.nodes[node].get("device_id", node)
        ax.text(x + (0.025 if node in states else -0.025), y, label, fontsize=6, ha="left" if node in states else "right", va="center")
    if not graph:
        ax.text(0.5, 0.5, "No eligible RF-state edges", ha="center", transform=ax.transAxes)
    ax.set_title("Weighted device–RSSI-state graph (edge weights normalized per device)")
    ax.set_xlim(-0.25, 2.1)
    ax.axis("off")
    _save(fig, path)


def plot_similarity_graph(graph, devices, groups, path) -> None:
    graph = graph.copy()
    graph.add_nodes_from(devices)
    pos = nx.spring_layout(graph, seed=9500)
    palette = plt.get_cmap("tab10")
    colors = {device: palette(index % 10) for index, group in enumerate(groups) for device in group}
    fig, ax = plt.subplots(figsize=(7, 6))
    nx.draw_networkx(graph, pos, ax=ax, node_color=[colors[node] for node in graph.nodes], node_size=1400, font_size=9, edge_color="#64748b", width=2)
    ax.set_title("Predicted constellations from mutual RWwR matches")
    ax.axis("off")
    _save(fig, path)


def plot_rssi_histogram(observations, path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist([row.rssi_dbm for row in observations], bins=15, color="#2563eb", edgecolor="white")
    ax.set(xlabel="RSSI (dBm)", ylabel="Observation records", title="Ambient WiSniff RSSI distribution (no pose or ownership labels)")
    _save(fig, path)


def save_inference_figures(result, directory, poses=None) -> None:
    directory = Path(directory)
    plot_rssi_by_pose(result.pose_rssi, directory / "rssi_by_pose.png", poses)
    plot_bipartite_graph(result.bipartite_graph, directory / "rssistate_graph.png")
    plot_similarity_heatmap(result.rwr_scores, result.devices, directory / "similarity_heatmap.png")
    plot_similarity_graph(result.similarity_graph, result.devices, result.groups, directory / "device_similarity_graph.png")
