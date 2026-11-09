# Four-device RSSI field guide

**Transport update:** [RX TCP and Uno setup](../../../wisniff/tools/RX_TCP_SETUP.md)
implements labeled CSI/PKT collection, observations.csv export and combined Uno/RF
capture. The original software audit below predates that update. Receiver-clock
pose-window control/alignment remains a separate prerequisite for spatial inference.

Goal: test whether one moving receiver can group two known laptop/ESP32 pairs,
and verify that real recordings pass the existing ingestion pipeline.

This is a controlled RSSI experiment. CSI may be saved for later work, but is
not used for grouping here. These geometry/timing settings are starting choices,
not validated RF separation thresholds. No firmware or collector fixes are
implemented by this experiment kit.

## 1. Equipment and labels

- One robot, one Raspberry Pi, and one mounted ESP32 receiver (`RX1`).
- Two additional ESP32s used as transmitters (`ESP1`, `ESP2`): three ESP32s total.
- One Mac laptop (`LAP1`) and one Windows laptop (`LAP2`).
- A phone providing a 2.4 GHz hotspot, tape, measuring tape, and nonmetal supports.
- Power for the Pi and ESP32s; charged laptops with sleep disabled during runs.

Known groups for the baseline layout:

| Group | Devices |
|---|---|
| G1 | LAP1 and ESP1 |
| G2 | LAP2 and ESP2 |

Record the devices' actual Wi-Fi transmitter addresses privately and map them to
these four labels. Keep group labels in the separate truth file. A device label
must not encode or change with its physical group.

## 2. Software gate: finish this before recording

The inspected checkout is not yet end-to-end compatible:

| Component | Inspected behavior | Needed for this trial |
|---|---|---|
| Firmware | Two laptop labels, one hardcoded ESP32 CSI source; serial output | Two distinct ESP32 source labels; four observed IDs |
| Firmware records | `CSI,ms,rssi,ch,n,ESP,magnitudes...` and `PKT,ms,rssi,ch,LAP1` | Agreed, explicitly versioned labeled record format |
| Pi collector | Legacy CSI expects literal `0` at field 6; rejects `PKT` | Parse labeled CSI and PKT; save RSSI from both |
| TCP | Python server exists; inspected firmware still uses `Serial.write` | Add firmware TCP sender if TCP is chosen; serial is usable after parser fixes |
| Pose markers | Collector can save markers; firmware does not emit them | Receiver-clock START/END control and recorded acknowledgments |
| Offline C3 adapter | Headered `observed-csv` supported | Use the exact header below |
| Inference/evaluation | Arbitrary device IDs and singleton handling supported | Existing code can run after valid ingestion |

Required developer changes:

1. Replace the single ESP32 source filter with an allowlist containing ESP1 and
   ESP2. Carry the correct source label in every queued measurement. Verify the
   two laptop allowlist addresses after joining the hotspot.
2. Give all four devices a valid RSSI measurement path. A bad/unsupported CSI
   length must not silently remove an otherwise usable RSSI observation. Avoid
   counting the same ESP32 frame twice through separate measurement callbacks.
3. Add an explicit labeled protocol to the collector, retaining legacy parsing
   as its own mode. Parse both existing labeled CSI and PKT records, validate
   timestamps/channel/RSSI/counts, and write `observations.csv` with one row per
   accepted RF observation. Keep optional CSI/raw records separately.
4. Use exactly these four required output columns:

   ```csv
   device_time_ms,device_id,rssi_dbm,channel
   10010,LAP1,-48,6
   10012,ESP1,-44,6
   10018,LAP2,-64,6
   10020,ESP2,-61,6
   ```

   Values above are illustrative, not measurements. Channel must be the actual
   hotspot channel. Optional CSI is permitted only in `csi_magnitudes_json`.
   Additional columns such as `label` or `source_type` are currently rejected by
   the observed-csv adapter; put experimental metadata in a sidecar instead.
5. Add operator/robot START and END commands that the receiver timestamps with
   its own `millis()`. Emit `# POSE_EVENT,P01,CAPTURE_START,<millis>` and the
   corresponding END marker. Provide the operator a tested way to send these
   commands. Wait for END acknowledgment before moving. The Pi's UTC clock or a
   handwritten stopwatch time must not replace receiver uptime.
6. Save event rows using the existing `event_index,device_time_ms,pose_id,phase`
   header. Indices must increase. Start a new trial on a receiver reboot/reset.
7. Before a real run, test all four IDs, labeled CSI/PKT conversion, malformed
   records, same-clock event joins, and movement exclusions. Compare the raw
   counts with disk output. A TCP connection by itself is not acceptance.

The existing legacy parser rejects a label such as `ESP1` in the sentinel field;
loosening that parser without versioning would mix two different formats.

## 3. Prepare the network and traffic

1. Use a phone hotspot rather than relying on uncontrolled campus roaming.
2. Select its 2.4 GHz/compatibility option. On supported iPhones this is called
   Maximize Compatibility. Verify the actual band; do not assume it is 2.4 GHz.
3. Connect both laptops and the Pi to the hotspot. Keep the phone stationary,
   outside both device groups and outside the robot's path.
4. Read the connected channel on Windows with `netsh wlan show interfaces`.
   Record it as N. If needed, use `netsh wlan show networks mode=bssid` and
   identify the connected hotspot. Do not repeatedly scan during recordings.
5. Set `CSI_CHANNEL=N` in the RX and both ESP32 TX builds. The current
   `wisniff/platformio.ini` explicitly supplies `-DCSI_CHANNEL=6`, so changing
   only the C++ fallback default is insufficient.
6. From analysis/, copy `config/report1.json` to `config/real_hotspot.json` and
   change `capture.expected_channel` to N. Keep K=2 and the original bins for
   this first prespecified experiment. This is a prototype config, not a real-RF
   calibration. Record it and do not retune on the evaluation run.
7. Keep each laptop's address stable on this hotspot: Mac Private Wi-Fi Address
   Fixed or Off; Windows per-network random hardware addresses Off. Record and
   verify the address actually used after connecting. Do not use an Ethernet
   adapter's address. Do not use the hotspot/AP address as a laptop's ID.
8. Keep lids open at the same angle, prevent sleep, pause unrelated transfers,
   and leave all traffic generators running throughout a trial.

Use the included standard-library traffic generator. It sends real Wi-Fi packets;
it does not generate RSSI values or simulated measurements.

On the Pi, from the repository root, start a UDP traffic sink:

```bash
python3 analysis/experiments/four_device_rssi/traffic.py receive
```

Find the Pi's hotspot IP with `hostname -I`. It may differ from the old campus IP.
Copy `traffic.py` onto both laptops. Replace PI_IP below with that actual address.

Mac terminal in the folder containing traffic.py:

```bash
python3 traffic.py send --host PI_IP --rate 20
```

Windows terminal in the folder containing traffic.py (Python required):

```powershell
py -3 traffic.py send --host PI_IP --rate 20
```

The sink should show traffic from both laptop IPs. The ESP32 RSSI logger must
independently show LAP1 and LAP2: sink counts do not prove ESP32 capture.
Use Wi-Fi for the laptop path. If the hotspot blocks laptop-to-Pi traffic,
resolve that first or select a reachable sink; do not assume the generator works.

Set both ESP32 transmitters to a fixed 50 ms interval (20 sends/s) for this pilot,
or document a different fixed interval. The current PlatformIO config uses 20 ms;
adjust `TX_INTERVAL_MS` there rather than only its C++ fallback. All four devices
must transmit during every capture window, rather than taking turns at positions.

## 4. Lay out the track

Use 18 ft of the 20.6 ft track. Leave about 1.3 ft at each end, adjusting for robot
clearance. Define x=0 at the receiver antenna's first stopping point, P01.

Mark ten receiver antenna stopping points, 2 ft (0.6096 m) apart:

| Pose | x from P01, ft | x, m |
|---|---:|---:|
| P01 | 0 | 0.0000 |
| P02 | 2 | 0.6096 |
| P03 | 4 | 1.2192 |
| P04 | 6 | 1.8288 |
| P05 | 8 | 2.4384 |
| P06 | 10 | 3.0480 |
| P07 | 12 | 3.6576 |
| P08 | 14 | 4.2672 |
| P09 | 16 | 4.8768 |
| P10 | 18 | 5.4864 |

Use the supplied `poses.csv` only after verifying those measured positions.
Measure antenna position, not the front wheels or bumper. These are receiver
coordinates; transmitter positions are separate experimental notes.

Put both groups on the same side of the track, on a parallel line 3 ft (0.9144 m)
away:

```text
                  LAP1 + ESP1                 LAP2 + ESP2
                  x=4 ft, y=3 ft              x=14 ft, y=3 ft
                  <---------- 10 ft ---------->

Track y=0:
P01  P02  P03  P04  P05  P06  P07  P08  P09  P10
 0    2    4    6    8   10   12   14   16   18 ft
```

- Put each ESP32 beside its laptop, roughly 6 in (15 cm) from the nearest case
  edge. Do not put it on/under a metal laptop case. Photograph the arrangement.
  This defines a small physical group; it is not an antenna-separation guarantee.
- Keep transmitter heights consistent and roughly near receiver height where
  practical. Use nonmetal supports; record actual heights and laptop lid angles.
- Fix RX1 on a nonmetal mount above/away from the Pi, robot metal and motor wires.
  Keep its antenna orientation and robot heading the same across baseline runs.
- Keep people out of the path between receiver and devices during stationary
  captures. Keep power banks/cables and the phone in fixed positions.

One receiver is sufficient for this RSSI spatial-trajectory prototype. It does not
provide two-receiver differential RSSI or establish full physical localization.

## 5. Stationary preflight: stop/go gate

Before moving, confirm a 10-second stationary test saves all four labels and
separate START/END events. Target at least 50 valid RF observations per device
in 10 seconds; 20 UDP sends/s is a traffic target, not a guarantee of 200 RF rows.

If any device is missing, fix its channel, current address, source filtering,
traffic, transport or parser. Do not start the route with a missing transmitter.
If counts are low, fix traffic or increase the dwell for every pose and repeat
the preflight. Select the dwell before the evaluation runs. The algorithm's
minimum of 3 samples per cell is a software gate, not a good collection target.

Verify malformed rows are not silently accumulating. Inspect queue-drop and
bad-CSI-length counters. Do not change signal-processing thresholds to make
the preflight predictions look correct.

## 6. Record a trial

1. Name the baseline trial `real001`; start a new capture directory and record
   firmware version, channel N, device mapping, geometry, heights and traffic rate.
2. Keep all four transmitters running and fixed in place.
3. Move the receiver antenna to P01 and stop the motors.
4. Wait 2 seconds to settle; this is not part of the capture window.
5. Send START P01 through the implemented receiver-clock control. Verify its
   CAPTURE_START acknowledgment is saved.
6. Stay still for 10 seconds, or the longer fixed dwell chosen at preflight.
7. Send END P01; wait for the saved CAPTURE_END acknowledgment.
8. Only now move to P02. Repeat steps 3-7 through P10. Movement speed need not
   be constant because moving measurements will be excluded later.
9. Stop collection cleanly. Save raw files and check 10 complete, nonoverlapping
   windows and data coverage for all four devices at all ten poses.
10. Repeat two more baseline runs (`real002`, `real003`), keeping geometry,
    orientation and settings fixed. Use separate trial IDs, output folders and
    appropriately updated truth files. Never pool receiver uptimes across runs.

A 5-second stop is only usable if it includes a separate settling period and
still produces sufficient samples. The recommended initial total stop is about
12 seconds: 2 seconds settling + 10 seconds capture, plus marker acknowledgment.

Optional control: swap ESP1 and ESP2 between the two stationary laptop locations,
without changing device labels or other settings, and record a fresh trial.
Its true groups are now LAP1+ESP2 and LAP2+ESP1. Record new truth *before* inference.
This checks whether associations follow physical grouping rather than names or
hardware type. Do not judge graph superiority on a single four-device result.

## 7. Required files and ingestion

After the developer fixes, the capture directory must contain:

- `observations.csv`: exact observed-csv schema from section 2.
- `pose_events.csv`: real, receiver-timestamped markers, not invented times.
- Session metadata and logs; optional raw/labeled CSI for auditing.

The ten-location manifest is supplied here as `poses.csv`. The separate
`truth_real001.json` template is valid only for the baseline LAP1+ESP1/LAP2+ESP2
layout and trial ID real001. It asserts measured setup labels, not personal ownership.

From analysis/, after recording and after fixing the live writer:

```bash
source .venv/bin/activate
# Replace with the actual directory printed by the collector, relative to analysis/.
RUN_DIR="data/raw/REPLACE_WITH_ACTUAL_CAPTURE_DIRECTORY"

python -m colocation.cli ingest-capture \
  --input "$RUN_DIR/observations.csv" \
  --events "$RUN_DIR/pose_events.csv" \
  --poses experiments/four_device_rssi/poses.csv \
  --format observed-csv --trial-id real001 --receiver-id RX1 \
  --config config/real_hotspot.json --out data/processed/real001
```

Read `data/processed/real001/ingest_report.json` first. It should identify all four
devices and correct per-pose counts, report normal movement/gap exclusions, and
contain no unknown-pose, identity, channel or clock errors. Some excluded samples
are expected: they are not evidence of packet loss. Then:

```bash
python -m colocation.cli infer \
  --input data/processed/real001/observations.jsonl \
  --config config/real_hotspot.json --out outputs/real001

python -m colocation.cli evaluate \
  --predictions outputs/real001/groups.json \
  --truth experiments/four_device_rssi/truth_real001.json \
  --out outputs/real001/metrics.json
```

If a known transmitter has no samples, treat the run as an incomplete experiment.
To inspect it fairly, include that device in the explicit Device manifest; otherwise
the ingester cannot discover it from absent rows. Do not drop it from truth to
inflate metrics. The evaluation command rejects mismatched device sets.

## 8. What success looks like

First distinguish successful data collection from successful grouping.

Collection success:

- Four stable transmitter IDs, one receiver ID, one channel and one clock session.
- Ten complete stationary windows and adequate per-device/per-pose counts.
- Moving samples excluded by ingestion; timestamps/IDs are not fabricated.
- Accepted/excluded counts reconcile; malformed rows and firmware losses reported.

Expected RF pattern (hypothesis, not a guaranteed shape):

- LAP1 and ESP1 generally become stronger (less negative RSSI) near P03.
- LAP2 and ESP2 generally become stronger near P08.
- The same-group *relative* RSSI curves resemble each other more than cross-group
  curves. Absolute levels may differ substantially due to hardware/power offsets.
- Indoor multipath can introduce dips, shift peaks and defeat this representation.

Grouping success:

- Mutual RWwR candidates and Pearson trajectories favor LAP1-ESP1 and LAP2-ESP2.
- Predicted groups match those pairs; ideal pairwise F1=1 and count error=0.
- Merely predicting two groups is not success: two incorrect pairs also have zero
  group-count error. Default K=2/zero threshold can accept weak positive matches.
- Results are repeatable across the baseline trials, and the swapped-device
  control favors its new physical pairings if the method is tracking colocation.

Keep graph and Pearson results side by side, report failures and sparse coverage,
and preserve the prespecified config. A valid recording with poor F1 is still useful
evidence about RF colocation, rather than a reason to edit measurements.

## Reference links

- [Espressif: ESP-NOW and Wi-Fi channel coexistence](https://github.com/espressif/esp-faq/blob/master/docs/en/application-solution/esp-now.rst)
- [Apple: private Wi-Fi addresses](https://support.apple.com/guide/mac-help/use-a-private-wi-fi-address-on-mac-mchlb1cb3eb4/mac)
- [Microsoft: Wi-Fi addresses and network settings](https://support.microsoft.com/en-au/windows/experience/connectivity-networking/connect-to-a-wi-fi-network-in-windows)
- [Microsoft: check wireless connection/channel](https://learn.microsoft.com/en-us/troubleshoot/windows-client/networking/wireless-network-connectivity-issues-troubleshooting)

Verify the Pi checkout and flashed firmware match this audit. Do not assume the
older Report1_README collection-status paragraphs describe the newer logger.
