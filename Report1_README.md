# ECE 9500 — Report #1 CLI Cheatsheet & Testing Guide

**Project:** Device Constellations — RSSI-only, GraphTrack-inspired colocation  
**Audience:** Teammates who want to run experiments without editing the algorithm.  
**Status:** The commands below are the **planned interface to implement**; they will work after the code described in [`ECE9500_Report1_Low_Level_Spec_v2.md`](ECE9500_Report1_Low_Level_Spec_v2.md) is added to the repository. The original `wisniff/` firmware is not itself the Python analysis package.

## 1. Open the project in VS Code (one-time setup)

1. Clone or pull [`jellyboston/ece9500-device-colocation-project`](https://github.com/jellyboston/ece9500-device-colocation-project), then open its **root directory** in VS Code.
2. Open **Terminal → New Terminal**. The example commands below assume you are inside `analysis/` (a new folder created by the implementation).
3. Run:

```bash
cd analysis
python3 -m venv .venv
source .venv/bin/activate             # macOS / Linux
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

Select the interpreter `analysis/.venv` in VS Code with **Python: Select Interpreter**. If `python3` isn't available, use your installed Python 3.11+ executable. If `analysis/` or `colocation/cli.py` does not yet exist, the coding agent still needs to implement the specification—**these commands are not built into Python or the current GitHub codebase**.

## 2. How to read a command

Example:

```bash
python -m colocation.cli synthesize --config config/report1.json --seed 9500 --out data/processed/synth001
```

| Piece | Meaning |
|---|---|
| `python` | Runs Python in your selected environment. |
| `-m colocation.cli` | Runs **our custom project command-line interface**. |
| `synthesize` | Action (subcommand): make artificial wireless measurements. |
| `--config config/report1.json` | Load experiment settings from a JSON file. |
| `--seed 9500` | Fix the random number generator so repeated runs produce the same synthetic values. |
| `--out ...` | Where to save the output files. |

Every `python -m colocation.cli ...` command below is a **custom command for this project**. The last command, `python -m pytest -q`, uses the standard `pytest` test runner; `-q` means quiet output.

## 3. CLI command reference

Run these from `analysis/`:

| Subcommand | What it does | Main input → output |
|---|---|---|
| `synthesize` | Makes a controllable, labeled **fake** RSSI experiment. | Config + seed → `observations.jsonl`, `devices.json`, `poses.json`, separate `truth.json` |
| `infer` | Runs the full RSSI-only pipeline: pose aggregation → relative RSSI bins → weighted graph → RWwR → mutual matches → cliques. **Never reads truth.** | Canonical `observations.jsonl` + config → `groups.json`, scores, figures |
| `evaluate` | Compares predictions with **independently known** true groups. | `groups.json` + `truth.json` → `metrics.json` |
| `summarize-wisniff` | Inspects the existing ambient RSSI JSON. **Does not do colocation inference.** | WiSniff JSON → summary + histogram |
| `ingest-csi` | Parses an old, single-transmitter CSI file, for exploratory analysis only. | Legacy CSI CSV → canonical rows with **unknown pose** |
| `ingest-capture` | Joins a controlled capture's measurements with **explicit same-clock position events**. Enforces device attribution and position checks. | Samples + events + pose manifest → canonical rows + quality report |
| `python -m pytest -q` | Runs automated tests. | Implementation/tests → pass or failure messages |

**Conceptual rule:** Both synthetic and *properly labeled* real captures must feed the **same** `infer` command. The graph code should never distinguish their origins, know a device's owner, or assume there are exactly two people.

## 4. Workflow A — Synthetic experiment (recommended first)

This workflow checks whether the **software** implements the algorithm. It does not prove that real RF signals can identify colocation.

### A1. Generate a test dataset

```bash
python -m colocation.cli synthesize \
  --config config/report1.json \
  --seed 9500 \
  --out data/processed/synth001
```

Check for these files under `data/processed/synth001/`:

- `observations.jsonl`: packet-level RSSI observations at known receiver positions; **this is what inference reads**.
- `devices.json`: known transmitting IDs; may include a device with insufficient samples.
- `poses.json`: receiver-position IDs and known synthetic coordinates.
- `truth.json`: actual device groupings for **evaluation only**, never passed to `infer`.

A JSONL file contains **one JSON object per line**; open it in VS Code to inspect individual packets.

### A2. Run colocation inference

```bash
python -m colocation.cli infer \
  --input data/processed/synth001/observations.jsonl \
  --config config/report1.json \
  --out outputs/synth001
```

Look at `outputs/synth001/groups.json`, `device_similarity.csv`, `similarity_heatmap.png`, and `device_similarity_graph.png`. These are **predictions**, not labels.

### A3. Score the predictions

```bash
python -m colocation.cli evaluate \
  --predictions outputs/synth001/groups.json \
  --truth data/processed/synth001/truth.json \
  --out outputs/synth001/metrics.json
```

Read `pairwise_precision`, `pairwise_recall`, `pairwise_f1`, and `count_absolute_error` (the exact output keys must be documented in the implementation). If the predicted groups don't match truth, keep the original outputs and investigate the settings rather than changing raw measurements until they agree.

### A4. Change the synthetic experiment

Edit `analysis/config/report1.json`, ideally by **copying it** (e.g. `config/synth_hard.json`) so you retain a reproducible baseline. Key settings:

| Setting | Example | If you change it… |
|---|---|---|
| `synthetic.group_sizes` | `[2, 2]` | Controls the **actual** numbers of devices per true group. `[2,2,1]` makes 5 devices with a singleton; `[3,3]` makes two triples. |
| `synthetic.device_ids` | `["M1","D1","M2","D2"]` | Optional friendly names; must be unique and match total device count. **Remove** this field when changing group sizes unless you also change the list. |
| `synthetic.group_center_x_m` | `[2.0,8.0]` | Physical centers of each true group along the toy one-dimensional path; supply one center per group. |
| `synthetic.num_poses` | `10` | Number of receiver stopping points; larger values give more spatial views. |
| `synthetic.pose_spacing_m` | `1.0` | Distance in meters between positions on the simple generated receiver path. |
| `synthetic.packets_per_device_pose` | `10` | More packets provide more stable medians, generally at greater synthetic data volume. |
| `synthetic.noise_sd_db` | `2.0` | Higher value adds random RSSI noise; associations may become less reliable. |
| `synthetic.tx_power_offset_sd_db` | `4.0` | Controls device-to-device transmit power differences. |
| `synthetic.missing_observation_probability` | `0.0` | Higher value drops packet samples, simulating incomplete captures. |
| `synthetic.path_loss_exponent` | `2.0` | Changes how quickly simulated RSSI falls with distance; **toy model, not calibrated physics**. |
| `synthetic.group_spread_m` | `0.2` | Larger values spread devices farther apart inside each true group. |
| `rssi.relative_bin_thresholds_db` | `[-8,-3,3,8]` | Moves the boundaries of the *relative-RSSI* RF states; **not absolute RSSI** and not verified distance cutoffs. |
| `rssi.min_packets_per_device_pose` | `3` | Minimum number of packet samples required to use one device at one pose. |
| `rssi.min_poses_per_device` | `3` | Devices with insufficient usable poses become low-coverage singletons. |
| `grouping.max_devices_per_group` | `2` | **Maximum assumed group size** (GraphTrack's `K`), **not** the number of groups. For `[3,3]`, set `K=3`. |
| `grouping.min_directional_similarity` | `0.0` | Minimum score for mutual candidate edges; strictly zero-score matches remain forbidden. Increasing it can prevent weak forced matches. |
| `rwr.restart_probability` | `0.15` | Controls how often the random walk returns to its starting device. |

Use the same seed when comparing parameter effects; change **one setting at a time** to make your comparison interpretable. Report parameter values rather than claiming one combination is universally best.

**Four recommended trial configurations:**

1. **Default:** `[2,2]`, `K=2`, moderate noise → test two known pairs.
2. **More devices:** `[2,2,2]`, `K=2`, supply 3 group centers → test 6 devices/3 pairs.
3. **Singleton:** `[2,2,1]`, `K=2`, supply 3 group centers → test singleton behavior. If weak positive edges still force a match, use a prespecified positive score threshold and report the false match as a limitation; do not tune using the same test labels.
4. **Triples:** `[3,3]`, `K=3`, supply 2 group centers → test clique grouping beyond pairs.

A harder experiment might legitimately have lower pairwise F1; that does **not** make a software crash acceptable. The algorithm should always produce a valid, non-overlapping partition of the observed/manifest device IDs.

## 5. Workflow B — Real-data exploration (existing captures)

### B1. Analyze `wisniff_data.json`

```bash
python -m colocation.cli summarize-wisniff \
  --input ../wisniff/data/wisniff_data.json \
  --out outputs/wisniff
```

This old file has 40 observation records and 18 unique MAC strings, but **no synchronized receiver pose data or known device ownership**. Use it for RSSI distributions and parser checks—not a real colocation claim. Do **not** use `infer` directly on it.

### B2. Inspect the legacy CSI CSV (optional)

```bash
python -m colocation.cli ingest-csi \
  --input ../wisniff/tools/csi_COM6_1794086754.csv \
  --trial-id singlelink001 --receiver-id RX1 --device-id T1 \
  --out data/processed/singlelink001.jsonl
```

`--device-id T1` is an **operator label** because the current receiver captures only one known transmitter. These rows lack receiver-position labels, so this exploratory output **cannot yet be used by spatial `infer`**. The last 57 columns are already CSI magnitudes in the example CSV, not raw complex values.

## 6. Workflow C — Real controlled movement capture (when available)

This is the pathway for testing real position-indexed RSSI. It is **not** a requirement to have the robot; manually marked receiver positions are sufficient for a staged test.

### C1. Capture samples plus explicit pose markers

- Place a controlled TX at a fixed location; move the **RX** between known marked positions (`P01`, `P02`, etc.). The **TX stays fixed**.
- The RX firmware should print `# POSE_EVENT,P01,CAPTURE_START,18500` and `# POSE_EVENT,P01,CAPTURE_END,26500`, where the last field uses the **same ESP32 `millis()`** clock as the measurement rows.
- The serial logger must **save** the event markers. Its current implementation only prints `#` lines, so it must be extended. Use timestamped events, **not blank lines** in the sample CSV.
- Exclude moving and settling periods; do not pretend a packet heard while carrying the laptop belongs to a fixed pose.

For `ingest-capture`, put three files inside a private local `analysis/data/raw/` folder:

**`capture001.csv`** — legacy rows from the single TX firmware (headerless):

```csv
CSI,18510,-42,6,3,0,12,15,14
CSI,18760,-43,6,3,0,13,15,15
```

**`pose_events001.csv`** — derived from the firmware event markers:

```csv
event_index,device_time_ms,pose_id,phase
0,18500,P01,CAPTURE_START
1,26500,P01,CAPTURE_END
2,26510,P01,MOVE_START
3,30500,P02,MOVE_END
4,30510,P02,SETTLE_START
5,32500,P02,CAPTURE_START
6,40500,P02,CAPTURE_END
```

**`poses001.csv`** — manually surveyed RX position labels (coordinates may be left empty):

```csv
pose_id,pose_index,x_m,y_m
P01,1,0.0,0.0
P02,2,1.0,0.0
```

> These are **schema examples**, not a usable real trial. They contain only 2 pose windows and 2 sample packets, below the initial quality thresholds. For a real test, gather ≥3 populated poses per device and ≥3 packet samples at each pose (prefer 6–10 poses with many more packets).

### C2. Convert the real capture into inference-ready observations

```bash
python -m colocation.cli ingest-capture \
  --input data/raw/capture001.csv \
  --events data/raw/pose_events001.csv \
  --poses data/raw/poses001.csv \
  --format csi-legacy \
  --trial-id capture001 --receiver-id RX1 \
  --single-known-transmitter --device-id T1 \
  --config config/report1.json \
  --out data/processed/capture001
```

Inspect `data/processed/capture001/ingest_report.json` before running inference. It should tell you how many samples were accepted, excluded during movement/settling, or rejected due to identity/clock/pose errors. It also writes the canonical `observations.jsonl` and position/device manifests.

**Important: one TX yields one device, not a colocation test.** You may plot its RSSI spatial trajectory; running `infer` should return a singleton/insufficient-grouping-evidence diagnostic, not pretend it has discovered a person grouping.

### C3. When the firmware supports multiple transmitters

The current RX firmware identifies the first transmitter and filters later CSI to that one peer. To compare **different devices**, the firmware must log a stable ID *on each sample*. A multi-TX input needs a headered CSV of this form:

```csv
device_time_ms,device_id,rssi_dbm,channel
18510,D001,-42,6
18520,D002,-46,6
18600,D001,-41,6
```

Use the same pose-event and pose-manifest formats as above, but call:

```bash
python -m colocation.cli ingest-capture \
  --input data/raw/multi_tx.csv \
  --events data/raw/pose_events001.csv \
  --poses data/raw/poses001.csv \
  --format observed-csv --trial-id controlled002 --receiver-id RX1 \
  --config config/report1.json \
  --out data/processed/controlled002

python -m colocation.cli infer \
  --input data/processed/controlled002/observations.jsonl \
  --config config/report1.json \
  --out outputs/controlled002
```

With a **separately recorded ground-truth file**, run `evaluate` as in Workflow A. Without such labels you can inspect predicted groups, but you cannot report group accuracy. Never guess transmitter IDs from similar RSSI values. Do not combine unsynchronized uptime clocks from two receivers.

## 7. Common problems and their meaning

| Message/problem | Check first |
|---|---|
| `No module named colocation` | Are you in `analysis/` with the implementation present and the virtual environment selected? |
| `No module named serial` or `networkx` | Did `python -m pip install -r requirements.txt` succeed? |
| Missing `pose_id` / no valid pose windows | You ran an ambient capture or forgot pose events; do not fabricate receiver locations. |
| Missing transmitter identity | On single-known-TX legacy captures, verify TX and pass both `--single-known-transmitter` and `--device-id`; with multi-TX, add `device_id` per row in firmware. |
| Event overlap / clock reset / unknown pose | Check ESP32 timestamps and `pose_events.csv` against `poses.csv`. Avoid relying on laptop wall time. |
| Few/no matched devices | Inspect sample coverage, bins, `K`, similarity scores, and a potential too-high score threshold; a singleton can be correct. |
| Dataset groups correctly but only on synthetic | You have demonstrated code behavior, **not yet real-world colocation accuracy**. |

## 8. What to share with the team/professor

For synthetic runs, share `config_used.json`, seed, packet/pose counts, `groups.json`, similarity figures, and `metrics.json`. For real captures, share the **capture-quality report**, RSSI-by-pose figure, and any independently recorded ground truth. Explain which results are synthetic and which are measured. Keep MAC-bearing campus data and private device credentials out of public commits.

**Full implementation details:** [`ECE9500_Report1_Low_Level_Spec_v2.md`](ECE9500_Report1_Low_Level_Spec_v2.md), especially §§6–10. The spec is the source of truth if any quick-start explanation is abbreviated.
