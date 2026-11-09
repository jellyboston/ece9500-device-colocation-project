# RX TCP and Uno movement capture

## What is implemented

The RX joins a hotspot and connects to the Pi's TCP server. Existing labeled
CSI/PKT records are preserved. Wi-Fi callbacks enqueue measurements; the main loop
polls a nonblocking TCP sender. The Uno independently runs its motion schedule.
The Pi saves RF and Uno serial events to one `capture.csv` with synchronized writes.

The source default ROLE remains MOCK (2). Explicit RX environments select ROLE=1
without source edits. The effective channel remains 1 and steady TX interval 10 ms,
matching the previous source overrides. These settings now live in platformio.ini
and are honored. Match the real hotspot channel on every radio; RX forwarding
pauses on a different associated channel.

## 1. Private flags on the firmware build machine

Use your teammate's existing ignored `wisniff/private_build_flags.ini`.
`platformio.ini` already includes `${security.build_flags}`. No actual credentials
have been copied into this change. Lowercase `wifi_ssid` / `wifi_pass` macros are
supported, along with `WIFI_SSID` and `WIFI_PASSWORD` / `WIFI_PASS`.

Add a quoted `PI_TCP_HOST` define containing the Pi's hotspot IPv4 address, found
with `hostname -I` on the Pi. Do not use its old campus address or `0.0.0.0`.
Optional defines: `PI_TCP_PORT` (9000), `RX_RECEIVER_ID` ("RX1").

`private_build_flags.example.ini` contains placeholders and normal string quoting.
Preserve your teammate's working quoting if different. If wifi_ssid and wifi_pass
are INI settings rather than exported macros, export them via security.build_flags:

```ini
[security]
wifi_ssid = YOUR_HOTSPOT_NAME
wifi_pass = YOUR_HOTSPOT_PASSWORD
build_flags =
    -Dwifi_ssid=\"${security.wifi_ssid}\"
    -Dwifi_pass=\"${security.wifi_pass}\"
    -DPI_TCP_HOST=\"PI_HOTSPOT_IPV4\"
```

Supply valid compiler string quoting, including SSIDs with spaces. Do not overwrite
an existing private file or commit it. Missing RX TCP settings produce errors naming
the required macros. TX/MOCK and RX serial do not need networking credentials.

## 2. Build and upload RX

From the repository root on the machine connected to the ESP32:

```bash
pio run -d wisniff -e esp32-c61-rx-tcp
# Replace RX_PORT with the actual receiver upload port.
pio run -d wisniff -e esp32-c61-rx-tcp -t upload --upload-port RX_PORT
```

The target is ESP32-C61; confirm the physical board. Serial debug remains at
921600 baud. Serial fallback: `-e esp32-c61-rx-serial`. The base environment still
builds MOCK. No upload was performed during development.

The TCP transport uses IPv4, a 2-second connection deadline/retry interval,
nonblocking partial writes, and a 5-second stalled-write deadline. During outages
queued observations are discarded with counters rather than replayed later.
A pending partial record is discarded across disconnects. Session metadata goes
first on each connection. Delivery is best effort, not exactly once; inspect
queue_drop, offline_drop and transport_drop diagnostics.

## 3. Start the Pi logger

Use the Pi's analysis environment and install its requirements, including pyserial
for Uno input. Find the Uno's USB port:

```bash
analysis/.venv/bin/python -m serial.tools.list_ports -v
```

From the repository root, replace UNO_PORT with the actual path, preferably a stable
`/dev/serial/by-id/...` path. Channel 1 must match the hotspot:

```bash
analysis/.venv/bin/python wisniff/tools/csi_data.py \
  --transport tcp --host 0.0.0.0 --port 9000 \
  --protocol rssi-labeled-v1 --receiver-id RX1 --channel 1 \
  --uno-port UNO_PORT --uno-baud 115200 --headless \
  --output-dir analysis/data/raw
```

Stop any other listener/service on port 9000 first. The supplied systemd unit selects
the labeled protocol; edit its paths and add the Uno port for your Pi. A legacy
firmware connection needs an explicitly selected legacy collector. Existing legacy
test/serial defaults remain unchanged. Do not open another Uno serial monitor.

## 4. Uno messages

Plain newline-terminated START and STOP are accepted at 115200 baud. START means
movement begins; STOP means movement ends. If the sketch actually prints STARP,
use `--uno-start-token STARP`. `--uno-stop-token` is configurable too.

Recommended timestamped format:

```text
ROBOT,0,1250,START
ROBOT,1,6250,STOP
```

Fields: `ROBOT,event_sequence,uno_millis,event`. Suggested sketch helper:

```cpp
void reportMotion(const char *event) {
    static unsigned long sequence = 0;
    Serial.print("ROBOT,"); Serial.print(sequence++); Serial.print(',');
    Serial.print(millis()); Serial.print(','); Serial.println(event);
}
// Serial.begin(115200) in setup(). Call reportMotion("START") when commanding
// the motors to start and reportMotion("STOP") when commanding them to stop.
```

No Uno sketch is present here, so this change does not modify its motion schedule.
Unknown complete Uno lines are saved as ROBOT_UNKNOWN, with a counter; malformed
timestamped lines are reported. Plain messages retain an empty source timestamp.
Opening USB serial may reset an Uno: verify startup on the bench and ensure RF
streaming is working before beginning the autonomous route.

## 5. Files and timing

Each process start creates a private run-* folder:

- `capture.csv`: combined RF, Uno and receiver pose events. Columns include unique
  record_index, pi_received_monotonic_ns, readable pi_elapsed_ms, source, original
  source_time_ms, record_type, RF identity/features, movement/pose event, CSI JSON,
  and the original raw_record.
- `observations.csv`: C3-compatible RF observations, with the header
  `device_time_ms,device_id,rssi_dbm,channel,csi_magnitudes_json`. No robot rows.
- `csi_labeled.csv`: raw labeled CSI; legacy mode instead produces `csi.csv`.
- `pose_events.csv`: genuine ESP32-clock POSE_EVENT records, when supplied.
- `session.json` and `collector.log`: protocol, counters, connections and errors.

Both readers timestamp received batches before file-writing delays. A shared lock
protects writes; sort by common receipt timestamp to compare arrivals across threads.
Original source clocks are preserved.

**Uno millis and ESP32 millis are independent.** The shared CSV provides approximate
arrival-time alignment, not synchronization. `robot_clock_synchronized` remains false.
STOP is not silently converted into an ESP32 capture-start timestamp; START is a
movement event, not a stationary-capture start. Allow settling after a physical stop.

The strict ingest-capture command still requires actual same-RX-clock pose events.
observations.csv is ready as observed-csv input, but Uno-only movement messages do
not establish those windows. Clock synchronization/uncertainty or acknowledged
receiver-clock pose markers are a separate integration. Do not feed the mixed
master CSV directly into the strict observed-csv adapter.

## 6. Verification

```bash
analysis/.venv/bin/python -m unittest discover -s pi-tcp-tests -v
cd analysis
.venv/bin/python -m pytest -q
```

Tests cover loopback framing/reconnects, the actual firmware transport compiled
natively with forced short writes, private macro aliases, concurrent RF/Uno writes,
C3 export parsing, and pseudo-serial Uno input through the real CLI (POSIX + pyserial).
Native C++ tests skip when no compiler is installed. They do not replace an ESP32
target build, Wi-Fi/CSI bench check, or physical Uno test.

Before recording, confirm the RX1 SESSION, increasing RF counts, Uno connected,
valid START/STOP rows, and explained drop counters. Test reconnects and reboot
boundaries. The teammate's RF callbacks and transmitter mappings are retained.
