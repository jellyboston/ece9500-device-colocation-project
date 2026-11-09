# ECE 9500 — Project Context for Codex

> **How to use this file:** This is a handoff reference for an AI coding agent working on the course research project. **The submitted full proposal reproduced below is the source of truth for the project's chosen scope.** The summaries and implementation discussion following it are explanatory context, not amendments to the proposal. If a separate, newer low-level implementation specification is supplied, use that document to guide implementation details while preserving the project's stated research goal. Ask for a decision rather than silently reconciling conflicting hardware or algorithm details.
>
> **Source files:** `ECE_Abstract_and_Full_Proposal.pdf` (authoritative full proposal and earlier abstract), `Wi-CaL_WiFi_Sensing_and_Machine_Learning_Based_Device-Free_Crowd_Counting_and_Localization.pdf`, `GraphTrack.pdf`. The earlier `10_13-deep-research-report.md` is **supplementary exploration, not an authoritative specification**. The downloadable bundle also includes the three source PDFs under `references/`.
>
> **Verbatim fidelity:** Sections under **Full proposal — verbatim** preserve the original proposal's wording, punctuation, item names, quantities, prices, and stated technical choices. Line wrapping and layout are adapted to Markdown. The two system figures and original Gantt chart are included as images because those cannot be reproduced word-for-word as ordinary Markdown. An accessible transcription of the Gantt chart is clearly labeled separately. Do not treat commentary outside the verbatim sections as original proposal text.

---

# Part I — Full proposal (verbatim)

*Original source: `ECE_Abstract_and_Full_Proposal.pdf`, pages 1–5.*

## 1. Past Work & Motivation

Counting wireless devices can overestimate the number of people in an area because one person may carry multiple devices, such as a phone, laptop, and smartwatch. Our project aims to reduce this overcounting by identifying physically colocated devices and grouping them into constellations at the person-level.

Our primary foundation is Wi-CaL (Choi et al), which demonstrates how low-cost ESP32 devices can use Wi-Fi Channel State Information (CSI) amplitude, signal processing, and multiple wireless links for device-free crowd counting and coarse localization. Expanding on its sensing techniques, we will use a mobile robot with multiple Wi-Fi receivers to collect RSSI and CSI measurements from individual transmitting devices. Rather than detecting how people affect fixed wireless links, we will analyze how each device's signal changes as the robot moves to identify potential colocation.

GraphTrack (Wang et al) provides our complementary inference framework. It uses weighted graphs and similarity algorithms to associate devices belonging to the same user based on shared browsing observations. We adapt this approach by replacing browsing-history data with physical RSSI/CSI fingerprints, allowing us to group devices based on their wireless similarity.

## 2. System Overview

![Original system overview diagram from full proposal, page 1](ece9500_project_context_assets/system_architecture.png)

The system operates using dual, separated ESP32 units that communicate with a central compute unit using USB 3.0. The compute unit also controls the movement of the robot chassis via an Arduino USB-enabled microcontroller that communicates with the control board via I2C. The control board contains MOSFETs to drive the chassis motors. In an advanced iteration, the compute unit would be a Raspberry Pi SBC powered by the robot battery via the robot control board, but in early versions we will use a laptop computer with an internal battery.

## 3. Methods

**RSSI:** The ESP32-C5 collects an ambient signal strength baseline using Wi-Fi Promiscuous Mode (Sniffer Mode). We collect these signal strengths while simultaneously logging the robot's real-time wheel odometry to timestamp and cross-reference the exact position of the robot at the millisecond the packet was intercepted.

**CSI features + Strength:** Similar to Wi-Cal, we utilize CSI Amplitude to mitigate the phase-synchronization noise on the ESP32s. The ESP32 collects a raw array of complex numbers representing the channel response for each subcarrier. These raw values are transmitted to our central computing unit, which calculates the absolute amplitude via the magnitude formula. At the same time, information elements can be extracted from these packets.

**Grouping Method:** We adapt the GraphTrack framework by constructing a multilayer heterogeneous graph to fuse physical tracking with digital identity by using RSSI and CSI for spatial approximation while using packet timing for additional device information.

**Data Pipeline:** RSSI and CSI data will be streamed via USB-Serial connections using a high baud rate (921600) to ensure zero dropouts while testing early algorithms. With the mobile platform, a Raspberry Pi can be mounted directly onto the mobile platform. Otherwise, a simple socket/udp protocol can be written to transmit the data from the ESP32 to a central computing unit located elsewhere.

![Original wireless sensing scene diagram from full proposal, page 2](ece9500_project_context_assets/wireless_sensing_scene.png)

## 4. Implementation Plan

Phase 1: Single ESP32 Baseline Validation (No Platform)

- Verify clean RSSI logging from ambient test devices.
- Enable the CSI callback function and capture raw subcarrier arrays
- Build the serial data transmission protocol.
- Pipe mock packet streams to confirm the GraphTrack RWR clustering engine successfully groups devices based on generated randomized MAC inputs.

Phase 2: Dual Receiver Multi-Device Bench Testing

- Implement a pair of ESP32-C6 receivers sitting apart (stationary) and verify that they can simultaneously capture the same packet burst and log matching timestamps
- Perform initial tests to verify feasibility of proceeding steps

Phase 3: Mobile Platform Automated Integration

- Mount your ESP32 pair onto the mobile base.
- Program the robot to run a predetermined path and ensure the data logger can correlate robot position with incoming RF Packet IDs.
- Stress Testing under Varying Conditions (# of people, varying distances, room layouts)

## 5. Equipment List

| Item | Quantity | Cost | Purpose | Vendor |
|---|---:|---:|---|---|
| ESP32-C6 | 6 | 9.00 | Robot receivers and test transmitters | Digikey |
| Yahboom Chassis Kit | 1 | 79.00 | Motors, structure, control board, battery | Yahboom |
| Arduino | 1 | 8.99 | Interface compute unit with robot control | Amazon |
| USB Power Bank 2x | 1 | 17.99 | Power ESP32s during testing | Amazon |
| USB 3.0 Hub | 1 | 6.98 | Compute unit to USB devices | Amazon |
| Raspberry Pi 4 B 2GB | 1 | 43.50 | Compute unit for fully mobile iteration | Sparkfun |
| AS5600 Magnetic Encoder 3x | 1 | 7.99 | Track robot’s location | Amazon |
| Gyroscope, Accelerometer, Magnetometer | 1 | 20.49 | Track robot’s location | Amazon |
| nRF52833 | 1 | 16.88 | Bluetooth | Amazon |
| 80Gbps USB-C cable | 1 | 24.99 | Arduino to Mac cable | Amazon |
| 480 MBps USB C to Micro USB | 2 | 10.98 | ESP32 to Mac cable | Amazon |

## 6. Gantt Chart

![Original Gantt chart from full proposal, page 4. Includes all source task wording, dates, color bars, and assigned leads.](ece9500_project_context_assets/gantt_chart.png)

## References

Choi, H., Fujimoto, M., Matsui, T., Misaki, S., & Yasumoto, K. (2022). Wi-CaL: WiFi sensing and machine learning based device-free crowd counting and localization. IEEE Access, 10, 24395–24410. https://doi.org/10.1109/ACCESS.2022.3155812

Wang, B., Zhou, T., Li, S., Cao, Y., & Gong, N. (2022). GraphTrack: A graph-based cross-device tracking framework. In Proceedings of the 2022 ACM Asia Conference on Computer and Communications Security (pp. 82–96). https://doi.org/10.1145/3488932.3517398

---

# Part II — Earlier submitted abstract (verbatim; historical, not the controlling scope)

*Original source: `ECE_Abstract_and_Full_Proposal.pdf`, page 6. This is included because it appears in the same uploaded PDF, but the **full proposal above supersedes it** wherever they differ.*

Team Members:

Cindy Mo  
Jake Boston  
Dixon Miller  
William Flanigan

Title: Device Constellations: Passive Wireless Sensing for Person-Level Crowd Estimation

People increasingly carry multiple wireless devices, such as phones, laptops, smartwatches, and earphones, making passive device detection an imperfect proxy for estimating the number and organization of people in a space. We propose a passive, multi-receiver wireless sensing system that uses Wi-Fi and Bluetooth RSSI measurements to identify nearby devices and infer device colocation. By comparing signal observations across multiple receivers and over time, the system clusters devices into dynamic groups, or “constellations,” that approximate their physical grouping and, potentially, common ownership. As a stretch goal, we will investigate whether these multi-receiver RSSI observations can also provide coarse spatial localization of individual devices or inferred constellations within an indoor environment.

TO DO:

- Deploy on robot and estimate robot motion on top of it
- Ex: moving in Dunham building and trying to detect 20 devices
  - Assume you know, let’s say 4 people with 5 devices
  - Goal: can you localize those 4 people?
- To look into:
  - Turtle robots
- Idea:
  - Borrow lab owned mobile robot (prefer not to do this)

---

# Part III — Gantt chart text transcription (supplementary, NOT verbatim layout)

*The original diagram in Part I is authoritative. This searchable transcription is provided so a CLI agent can process the schedule without image-reading tools. Original chart labels and tasks are retained where readable; intervals are interpreted from its colored bars.*

| Charted period | Task text from chart | Project leader |
|---|---|---|
| Oct 12–Oct 26 | Mount BMO085 and AS5600 to chassis, flash ESP32-C5 sniffer nodes and test packet capture, verify I^2C data reading on microcontroller | Will |
| Oct 26–Nov 9 | Build micro-ROS / serial driver for encoders & IMU, configure ROS 2 robot localization (EKF fusion), run SLAM Toolbox in Dunham building for 2D floorplan, set up Nav2 loop trajectory execution | Dixon |
| Nov 9–Nov 23 | Timestamp-align RF frames with robot poses, extract differential RSSI, implement CSI amplitude parsing and hampel filtering, benchmark colocation signal variance on 2 test devices | Jake |
| Nov 23–Dec 14 | Deploy 20 devices across 4 stationary people, collect trajectory data across multiple runs in Dunham, implement GraphTrack-inspired graph construction, cluster devices into 4 constellations and compute ARI/F1 score | Cindy |
| Dec 7–Dec 21 | Implement spatial likelihood and centroid fitting for clusters, calculate localization error against ground truth, run ablations (1 vs. 2 receivers, RSSI vs. CSI, direct vs. graph) | Dixon/Jake |
| Dec 14–end of chart (extends past Dec 21 tick) | Build real-time visualization dashboard (constellations + count), lock hardware configuration & rehearse Dunham demo run, finalize research report & presentation slides | Will/Cindy |

*Note: Date ranges above describe the colored timeline bars as shown in the original chart, rather than verified subsequent project status. Overlapping activities are intentional.*

---

# Part IV — High-level paper summaries (explanatory; NOT proposal text)

## A. Wi-CaL — WiFi Sensing and Machine Learning Based Device-Free Crowd Counting and Localization

**Paper:** Choi et al. (2022), *IEEE Access*, https://doi.org/10.1109/ACCESS.2022.3155812. See also the attached `Wi-CaL_WiFi_Sensing_and_Machine_Learning_Based_Device-Free_Crowd_Counting_and_Localization.pdf`.

**Research question:** Can low-cost ESP32 Wi-Fi links estimate both the number of people in a room and the coarse section of the room where they are located, without requiring people to carry devices?

**How it works, at a high level:**

1. Establish **four fixed ESP32 transmitter–receiver links** spanning an indoor room. People walking through the space change the radio multipath environment, which changes the Wi-Fi channel even though they are not transmitting.
2. Collect **CSI** (complex channel response on multiple Wi-Fi subcarriers) and RSS measurements; work primarily with **CSI amplitude**, avoiding the calibration problems associated with commodity CSI phase.
3. Aggregate CSI into **six-second windows with three-second overlap**, and reduce noise with **Hampel** and **Savitzky–Golay** filtering.
4. Extract engineered features: per-subcarrier statistics (e.g. standard deviation), CSI-bundle shape and spread (e.g. interquartile range, adjacent-subcarrier differences, successive CSI-vector distance), and RSS variability.
5. Train an ML **regressor for crowd count** and a **classifier for room section**, and evaluate on repeated sessions in different rooms.

**Key distinction from our project:** Wi-CaL is **device-free human sensing**: it examines how human bodies perturb pre-existing fixed Wi-Fi links. Our project examines signals **transmitted by individually observed devices** while a dual-receiver **robot moves**. We borrow the measurement and CSI-feature-engineering ideas, **not** Wi-CaL's specific input/output task or fixed-link geometry. Wi-CaL does not solve our person-level cross-device association problem.

**Useful to the coding agent:** Understand per-packet CSI arrays, magnitude/amplitude extraction, time/pose windowing, noise filtering, feature extraction, multi-receiver measurements, and evaluation across experimental sessions. Do not assume Wi-CaL's six-second windows, feature selection, and reported accuracies will transfer directly to moving-receiver RF fingerprinting.

## B. GraphTrack — A Graph-based Cross-Device Tracking Framework

**Paper:** Wang et al. (2022), *Proceedings of ACM ASIA CCS*, https://doi.org/10.1145/3488932.3517398. See also the attached `GraphTrack.pdf`.

**Research question:** Given separate devices and their browsing observations, which devices belong to the **same user**?

**How it works, at a high level:**

1. For each already-identified device, obtain browsing observations such as IP addresses used and website domains visited.
2. Construct separate **weighted bipartite graphs**: `IP–Device` and `Domain–Device`. Device–observation edge weights represent repeated usage/visits; GraphTrack normalizes weights to avoid unfairly favoring heavy browsing activity.
3. Run **Random Walk with Restart (RWwR)**, a.k.a. personalized PageRank, from each device in the graphs. At each step the walk either follows an edge (according to transition weights) or restarts at its original device; its stationary probabilities yield directed device-to-device similarity scores. This uses indirect, **multi-hop** graph connections, not merely identical observations.
4. Construct a **device-similarity graph**. In the unsupervised version, if a user can have at most `K` devices, add a device-pair edge only when the two devices rank each other among their top `K−1` candidates. GraphTrack also has labeled-data/threshold variants.
5. Find **cliques** (fully pairwise-connected sets) to predict groups of devices associated with a user; resolve overlapping cliques using the paper's specified rules.
6. **GraphTrack-OR** constructs IP-based and domain-based device-similarity graphs separately, takes their **edgewise union (OR)**, and then performs clique analysis. This is OR of **accepted graph edges**, not OR of raw measurements or a direct arithmetic combination of RWwR scores. The paper also compares AND and unified-graph variants; OR performed best on the paper's data, which does **not** establish that OR is best for RSSI/CSI.

**Key distinction from our project:** GraphTrack's observation nodes are naturally discrete **IPs and domains**; our observations are continuous **RSSI and multivariate CSI features** conditioned on **robot position/time**. To adapt GraphTrack, an additional, nontrivial step is needed to transform RF observations into shared, comparable RF-state nodes or another appropriate graph representation. GraphTrack predicts **common ownership from browsing behavior**; our research hypothesis concerns **physical colocation from wireless propagation patterns**. Colocation does not by itself prove common ownership.

**Useful to the coding agent:** Bipartite heterogeneous graph modeling, device–observation edge weights, normalized transitions, RWwR, mutual top-neighbor relationships, clique extraction, OR fusion, and comparisons against simpler direct-similarity baselines.

## C. How the two papers connect in this project

| Dimension | Wi-CaL | GraphTrack | Our full proposal |
|---|---|---|---|
| Source signal/evidence | Channel changes across controlled, fixed Wi-Fi links | Device browsing histories, IPs, domains | Per-device RSSI/CSI plus packet timing and robot trajectory |
| Core technical contribution | CSI signal processing + crowd count/section prediction | Graph representations + RWwR-based device association | Transfer wireless measurements into graph-based physical colocation inference |
| What gets grouped/counts | People affecting the wireless environment | Devices inferred to have a common user | Colocated transmitting devices as person-level **constellations**, to reduce device-overcount error |
| What is **not** established | Same-person grouping of transmitting devices | Similarity from RF physics | That colocated consumer devices reliably share RF fingerprints; **this is the hypothesis to test** |

---

# Part V — Prior algorithm discussion (explanatory ideas, NOT locked proposal requirements)

The team discussed the following possible way to **adapt** GraphTrack. This is a design direction for consideration against a separate detailed implementation specification, **not** verbatim full-proposal text and **not** a claim of tested performance:

1. Align each captured packet and its RSSI/CSI metadata with its **receiver ID**, **source device ID**, **timestamp**, and **robot position / odometry bin**. Motion serves to collect spatially diverse views of the same transmitting devices.
2. Build each device's **spatial RF fingerprint**: feature measurements indexed by robot location or time/position window. Raw absolute RSSI may differ across devices due to transmitter power and antenna differences; investigate normalized RSSI trajectories and **differential RSSI** between receivers.
3. A proposed initial **RSSI–State–Device graph** could use shared nodes such as `(robot-position bin, differential-RSSI bin)`, where differential RSSI is `RSSI_left − RSSI_right`. Bin thresholds are empirical choices, not pre-established physical truths.
4. A proposed **CSI–State–Device graph** could derive low-dimensional features from CSI amplitude (such as standard deviation, IQR, adjacent-subcarrier differences, and temporal change), standardize them, and assign similar feature vectors to shared state labels (e.g. by k-means). **Cluster label A/B/C is an arbitrary feature-pattern category**, not a known physical position or person. Its utility must be validated experimentally.
5. Give device-to-state edges weights reflecting observation frequency/consistency (with appropriate normalization), run RWwR in the two graphs, make device-only similarity graphs, **OR their accepted edges** as in GraphTrack-OR, then infer groups with cliques.
6. **Before relying on a graph method**, compare against a simpler direct device-pair baseline (e.g. correlation of aligned normalized RSSI/differential-RSSI trajectories). Evaluate known colocated vs separated transmitters, and then test CSI contributions, single vs dual receivers, and robustness across trials.

**Important design cautions:** Two devices with similar RF features are not necessarily colocated; even colocated devices can have different channel responses because of transmit frequency, antenna geometry, packet characteristics, and multipath. A simple shared-state graph can also spuriously connect otherwise unrelated devices through very common bins. Normalize and test representations against controls; do not assume adding RWwR or OR fusion automatically improves accuracy. Packet-level CSI may not be obtainable for every arbitrary consumer transmission. Focus early validation on **observable, controlled signals** and document any limitations in a purportedly passive setting.

---

# Part VI — Scope/implementation notes for a coding agent

- **Priority:** The full proposal in Part I controls the intended project; the historical abstract, deep research report, and algorithm brainstorming are subordinate. A newer explicit instruction from the project team or a separate implementation specification can clarify details, but do not silently treat exploratory variants as selected scope.
- **Preserve source ambiguities:** The original proposal uses **ESP32-C5** in its RSSI method and chart, but **ESP32-C6** in its bench-testing plan and equipment table. The accompanying vendor URL embedded in the PDF for the first equipment row points to an **ESP32-C61** listing. The prose is intentionally reproduced verbatim; verify the actual board model and corresponding firmware/CSI support before coding or ordering.
- **No unwarranted guarantees:** The proposal's reference to a serial baud rate of `921600` “to ensure zero dropouts” is its stated plan, not a hardware guarantee; packet delivery, receiver synchronization, CSI support, and end-to-end timestamps require testing.
- **Research framing:** Reducing an overcount based on observable transmitting devices is not the same as detecting every person. A person carrying no observable transmitter may not be detected, and physical colocation is not always common ownership.
- **Source diagrams:** Relative image paths in this Markdown refer to `ece9500_project_context_assets/`. Keep this file next to that folder when copying into the VS Code workspace. The original PDF is included in the downloadable bundle for exact visual/source verification.

