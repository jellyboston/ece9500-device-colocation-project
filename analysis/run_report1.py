"""Reproduce Report #1 CLI outputs and anonymized acceptance evidence.

Run with ``analysis/.venv/bin/python analysis/run_report1.py`` from the repository
root, or ``python run_report1.py`` from analysis/. No hardware is required. The
capture input is a clearly synthetic serial/event fixture, not a measured trial.
"""

from copy import deepcopy
from importlib.metadata import version
from pathlib import Path
import random
import shutil
import subprocess
import sys

from colocation.config import load_config
from colocation.evaluate import score_groups
from colocation.models import Device, Truth
from colocation.pipeline import infer_observations
from colocation.storage import write_json
from colocation.synthetic import generate_synthetic


ANALYSIS = Path(__file__).resolve().parent
SEED = 9500


def run_cli(*arguments: str) -> None:
    """Exercise the public command interface using this Python environment."""
    subprocess.run(
        [sys.executable, "-m", "colocation.cli", *arguments],
        cwd=ANALYSIS,
        check=True,
    )


def run_documented_workflows() -> None:
    fixtures = ANALYSIS / "tests" / "fixtures"
    for filename in ("capture_samples.csv", "pose_events.csv", "poses.csv"):
        if not (fixtures / filename).is_file():
            raise FileNotFoundError(f"Required synthetic capture fixture is missing: {fixtures / filename}")
    run_cli("synthesize", "--config", "config/report1.json", "--seed", str(SEED), "--out", "data/processed/synth001")
    run_cli("infer", "--input", "data/processed/synth001/observations.jsonl", "--config", "config/report1.json", "--out", "outputs/synth001")
    run_cli("evaluate", "--predictions", "outputs/synth001/groups.json", "--truth", "data/processed/synth001/truth.json", "--out", "outputs/synth001/metrics.json")
    run_cli("summarize-wisniff", "--input", "../wisniff/data/wisniff_data.json", "--out", "outputs/wisniff")
    run_cli(
        "ingest-csi", "--input", "../wisniff/tools/csi_COM6_1794086754_useful.csv",
        "--trial-id", "singlelink001", "--receiver-id", "RX1", "--device-id", "T1",
        "--out", "data/processed/singlelink001.jsonl",
    )
    run_cli(
        "ingest-capture", "--input", "tests/fixtures/capture_samples.csv",
        "--events", "tests/fixtures/pose_events.csv", "--poses", "tests/fixtures/poses.csv",
        "--format", "csi-legacy", "--trial-id", "capture001", "--receiver-id", "RX1",
        "--single-known-transmitter", "--device-id", "T1", "--config", "config/report1.json",
        "--out", "data/processed/capture001",
    )
    run_cli("infer", "--input", "data/processed/capture001/observations.jsonl", "--config", "config/report1.json", "--out", "outputs/capture001")


def scenario_config(base: dict, sizes: list[int], centers: list[float], *, k: int = 2) -> dict:
    config = deepcopy(base)
    config["synthetic"].update(group_sizes=sizes, group_center_x_m=centers)
    config["synthetic"].pop("device_ids", None)
    config["grouping"]["max_devices_per_group"] = k
    return config


def run_acceptance_scenarios() -> dict:
    base = load_config(ANALYSIS / "config" / "report1.json", synthetic=True)
    three_pairs = scenario_config(base, [2, 2, 2], [1.0, 4.5, 8.0])
    three_pairs["synthetic"]["device_ids"] = [
        "zeta:phone", "alpha%watch", "device/9", "Ω laptop", "left", "unfamiliar",
    ]
    singleton = scenario_config(base, [2, 2, 1], [1.0, 4.5, 8.0])
    singleton["grouping"]["min_directional_similarity"] = 0.05
    triples = scenario_config(base, [3, 3], [2.0, 8.0], k=3)
    noisy = deepcopy(base)
    noisy["synthetic"]["noise_sd_db"] = 12.0
    scenarios = [
        ("default_two_pairs", base),
        ("three_pairs_arbitrary_identifiers", three_pairs),
        ("two_pairs_and_singleton", singleton),
        ("two_triples_k3", triples),
        ("incomplete_and_uneven_coverage", deepcopy(base)),
        ("negative_control_noise12", noisy),
    ]
    evidence = []
    for name, config in scenarios:
        observations, devices, poses, truth = generate_synthetic(config, SEED)
        transformations = {}
        if name == "incomplete_and_uneven_coverage":
            transformations = {
                "retain_only_poses_by_device": {"M1": ["P01", "P02"]},
                "exclude_poses_by_device": {"D1": ["P03", "P05"]},
                "exclude_odd_sample_indices_by_device": ["D2"],
                "additional_zero_sample_manifest_devices": ["silent-transmitter"],
            }
            observations = [
                row for row in observations
                if not (row.device_id == "M1" and row.pose_id not in {"P01", "P02"})
                and not (row.device_id == "D1" and row.pose_id in {"P03", "P05"})
                and not (row.device_id == "D2" and row.sample_index % 2)
            ]
            devices.append(Device(trial_id="synth001", device_id="silent-transmitter"))
            truth.append(Truth(trial_id="synth001", device_id="silent-transmitter", group_id="G3"))
        result = infer_observations(observations, config, devices)
        metrics = score_groups(result.groups, truth)
        baseline = score_groups(result.baseline_groups, truth)
        flattened = [device for group in result.groups for device in group]
        valid_partition = (
            len(flattened) == len(set(flattened))
            and set(flattened) == {device.device_id for device in devices}
            and all(1 <= len(group) <= config["grouping"]["max_devices_per_group"] for group in result.groups)
        )
        if not valid_partition:
            raise RuntimeError(f"Invalid predicted device partition in scenario {name}")
        shuffled = list(observations)
        random.Random(42).shuffle(shuffled)
        repeated = infer_observations(shuffled, config, list(reversed(devices)))
        deterministic = result.groups == repeated.groups and result.rwr_scores == repeated.rwr_scores
        if not deterministic:
            raise RuntimeError(f"Order-dependent inference in scenario {name}")
        evidence.append({
            "scenario": name,
            "source": "synthetic",
            "seed": SEED,
            "config": config,
            "observation_transformations": transformations,
            "observations_count": len(observations),
            "manifest_device_count": len(devices),
            "manifest_pose_count": len(poses),
            "predicted_groups": result.groups,
            "pearson_baseline_groups": result.baseline_groups,
            "rwr_metrics": metrics,
            "pearson_baseline_metrics": baseline,
            "graph_minus_baseline_pairwise_f1": metrics["pairwise_f1"] - baseline["pairwise_f1"],
            "graph_improved_pairwise_f1": metrics["pairwise_f1"] > baseline["pairwise_f1"],
            "valid_partition": valid_partition,
            "deterministic_under_row_and_manifest_reordering": deterministic,
            "observations_summary": result.summary,
        })
    return {
        "description": "Reproducible software acceptance evidence, not measured RF colocation validation",
        "seed": SEED,
        "python_version": sys.version.split()[0],
        "packages": {package: version(package) for package in ("numpy", "pandas", "networkx", "matplotlib", "pyserial", "pytest")},
        "scenarios": evidence,
        "limitations": [
            "Generated ground truth tests software behavior; it does not establish that real colocated devices have matching RF fingerprints.",
            "The Pearson comparator always uses mutual top-1 (maximum group size 2); the graph uses configurable K. Triple-case accuracy differences also reflect that capacity difference.",
            "The 12 dB noise control is prespecified and unchanged after observing predictions; noise need not reduce accuracy at every seed.",
            "Low-coverage and zero-sample manifest devices are retained as singletons; correct coverage handling can reduce accuracy against known synthetic truth.",
            "WiSniff outputs are aggregate exploration of one ambient scan without pose, time, or ownership labels; observed MAC count is not person count.",
            "capture001 uses a synthetic single-transmitter serial/event fixture; it tests joining and singleton diagnostics, not hardware performance or multi-device grouping.",
            "Real sample and event files must be supplied from the same ESP32 recording run. Integer uptime alone cannot detect every accidental mix-up between recordings.",
        ],
    }


def copy_report_artifacts() -> None:
    sources = {
        "synth001": [
            "config_used.json", "observations_summary.json", "groups.json", "metrics.json",
            "device_similarity.csv", "rssi_by_pose.png", "rssistate_graph.png",
            "similarity_heatmap.png", "device_similarity_graph.png",
        ],
        "wisniff": ["summary.json", "rssi_histogram.png"],
    }
    for source, filenames in sources.items():
        destination = ANALYSIS / "report1_evidence" / source
        destination.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            shutil.copy2(ANALYSIS / "outputs" / source / filename, destination / filename)


def main() -> int:
    run_documented_workflows()
    evidence = run_acceptance_scenarios()
    copy_report_artifacts()
    write_json(ANALYSIS / "report1_evidence" / "acceptance_summary.json", evidence)
    print("Anonymized report evidence written to analysis/report1_evidence/.")
    print("capture001 is a synthetic ingestion fixture; no hardware experiment was run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
