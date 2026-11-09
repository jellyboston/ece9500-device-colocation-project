# ESP32 receiver → Pi collection protocol

The Pi listens on TCP port **9000**, bound to **0.0.0.0** by default. Both are
configurable. One ESP32 RX connects to the Pi's reachable LAN address; the Pi's
configured receiver ID identifies that RX, never a transmitter. Serial uses the
same record handling for comparison.

## Records accepted by this collector

Send UTF-8 text with one complete record per LF (`\n`); CRLF is also accepted.
TCP writes may split records or contain several records. Finish every record,
including the last one, with a newline. An unfinished record at disconnect is
reported and discarded; it cannot continue in the next connection.
The default maximum record size is 16 KiB (`--max-record-bytes`); oversized
records are discarded through the next newline so subsequent records can recover.

Legacy CSI remains exactly:

```text
CSI,<receiver_millis>,<rssi_dbm>,<channel>,<n>,0,<n magnitudes>
CSI,12345,-52,6,3,0,10,20,30
```

`receiver_millis` is the original nonnegative receiver timestamp, RSSI is between
-120 and 0 dBm, channel is 1–14, `n` is positive, the sentinel is literally `0`,
and there must be exactly `n` nonnegative integer magnitudes. Valid rows go into
`csi.csv` without a header or added identity columns. Malformed rows are reported
and excluded. The existing firmware limits `n` to 306.

The legacy row contains **no transmitter ID**. Do not interpret the TCP address,
receiver ID, or sentinel as a transmitter ID. Offline legacy ingestion requires
the operator's explicit assertion that there was one known transmitter.

Optional session metadata is one JSON object after `# SESSION,`:

```text
# SESSION,{"protocol_version":"csi-legacy-v1","receiver_id":"RX1","firmware_version":"your-build-version","channel":6}
```

Use the Pi's configured receiver ID. `protocol_version` must be
`csi-legacy-v1`, `firmware_version` is a string, and `channel` is an integer from
1 to 14. Send this after each connection when available. Firmware diagnostics
beginning with `#` are saved in `collector.log`, including the existing
`# peer ..., csi=..., dropped=...` counters. Session metadata and connection
boundaries are recorded in `session.json`.
Only these four metadata keys are accepted. An advertised receiver ID or protocol
that does not match the collector closes that connection; other invalid metadata
is reported and skipped. Missing metadata leaves firmware/channel unknown unless
the operator supplied them through the command line.

## Pose events and the receiver clock

The experiment supplies real position labels. The RX emits these markers through
the same ordered sending queue as measurements, using the **same `millis()`
clock**:

```text
# POSE_EVENT,P01,CAPTURE_START,12300
# POSE_EVENT,P01,CAPTURE_END,22300
```

Supported phases are `CAPTURE_START`, `CAPTURE_END`, `MOVE_START`, `MOVE_END`, and
`SETTLE_START`. The Pi writes `pose_events.csv` with columns
`event_index,device_time_ms,pose_id,phase`; indices start at zero and increase in
arrival order. Pi arrival time does not replace receiver time. A separate TCP
client cannot supply the RX clock or append to its in-progress stream.

Keep recording measurements during movement. `ingest-capture` later selects
stationary capture windows. Supply the experiment's own pose table; the collector
does not guess coordinates or labels. The current report configuration requires
at least 3 packets per device per pose, 3 poses per device, and 3 shared poses;
collect comfortably more and check the resulting capture-quality report.

Reconnects preserve the recording. A decreasing receiver timestamp is reported
as a possible reset or wrap; separate clock epochs into explicit analysis trials
before ingestion. TCP reconnects alone do not establish that the clock reset.
`session.json` flags `requires_clock_split` and records reset locations. Connection
row/event offsets are zero-based, with exclusive end offsets. Receiver-clock
checks run independently for CSI and pose events to allow queued delivery.

## Network and firmware handoff

Use a controlled **2.4 GHz access point with a fixed channel**, initially channel
6 to match `CSI_CHANNEL` and the report configuration. The Pi may use Ethernet
or Wi-Fi on the reachable LAN. The RX joins that access point; all ESP-NOW
transmitters must use the same channel. Disable automatic AP channel changes for
the experiment. Espressif documents the
[shared Wi-Fi/ESP-NOW channel requirement](https://docs.espressif.com/projects/esp-faq/en/latest/application-solution/esp-now.html).

The teammate owns firmware changes on `report1/pi-setup`. The current
`wifiCommon()` disconnects Wi-Fi and sets the CSI channel; adding AP association
there affects both TX and RX roles and needs deliberate coordination. Retain
HT20 and disabled Wi-Fi sleep, and verify actual channel and CSI delivery after
association. Channel agreement alone does not prove CSI reception still works.
At implementation time this branch existed in the Pi checkout but was not
published on origin; the teammate's latest unpushed changes could not be inspected.

Preserve this path:

```text
CSI callback → bounded queue → sending loop/task → TCP
```

Keep connection attempts, reconnect delays, formatting, and potentially blocking
writes outside the CSI callback. Espressif states that the
[CSI callback runs in the Wi-Fi task and should queue work](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c6/api-guides/wifi-driver/wifi-vendor-features.html#wi-fi-channel-state-information-configure).
Handle partial writes and retain unsent byte offsets within a connection. After
disconnect, resume with a complete record so fragments cannot join across
connections. Document the queue's overflow and replay policy; this protocol has
no application acknowledgments or exactly-once guarantee.

Current firmware has a 32-frame queue. Its cumulative `rxCount` counts accepted
CSI callback observations, including queue drops; `dropCount` increments when
enqueue fails. Counters print every two seconds on serial. Forward those
diagnostics over TCP too. The build sets `TX_INTERVAL_MS=20` (50 Hz), while the
source default is 10 ms. TCP cannot recover RF observations missed before capture
or frames dropped by this queue. TX sequence numbers currently do not appear in
CSI rows, so those rows cannot quantify every over-the-air loss.

## Proposed extension: not implemented or agreed with the firmware teammate

Preserve `CSI,...` for legacy captures. Before supporting several transmitters or
RSSI-only observations, agree a separate versioned record, for example
`OBS,2,<JSON object>`:

```text
OBS,2,{"device_time_ms":12345,"transmitter_id":"TX_A","source_type":"controlled_espnow","measurement_type":"csi","rssi_dbm":-52,"channel":6,"csi_magnitudes":[10,20,30]}
OBS,2,{"device_time_ms":12346,"transmitter_id":"TX_A","source_type":"controlled_espnow","measurement_type":"rssi","rssi_dbm":-54,"channel":6,"csi_magnitudes":null}
```

`TX_A` is illustrative: firmware must supply an actual per-sample identity and a
documented mapping. Agree identity scope, source labels (for example
`controlled_espnow` versus `ambient_wifi`), reset/boot identification, sequencing,
and storage together. Save extensions to a separate explicitly versioned schema;
never append new columns to legacy `csi.csv`. This collector does not accept
these proposed `OBS` rows. Existing analysis also needs an explicit adapter for
any agreed extension.

## Real-device acceptance still required

1. Join the fixed-channel AP, connect the RX, and confirm increasing valid CSV
   rows and unchanged receiver timestamps.
2. Emit real pose markers, verify saved labels/times, and check capture quality.
3. Compare CSI rate and queue-drop counters before and after enabling TCP; test
   backpressure and reconnect without blocking capture callbacks.
4. Interrupt Wi-Fi/TCP and restart the RX; inspect connection and clock-reset
   diagnostics, saved counts, and incomplete-record reporting.
5. Run through systemd, close VS Code/SSH, and verify collection continues.
   Test reboot startup if boot-time collection is enabled.

Mock TCP tests validate the Pi collector. They do not establish RF capture,
firmware networking, marker generation, or real-device readiness.
