# ece9500-device-colocation-project
Course project for ECE 9500 taught by Professor Tara Boroushaki FA 2026. Project members: Jake Boston ('27), Cindy Mo ('27), Dixon Miller ('27), William Flannigan ('27)

## Connecting to the Raspberry Pi 

To ssh: `xrpi4@10.66.56.138`  
When asked for password: `wvkbd`


## Setting up ESP32
Install and setup Platformio following the [tutorial](https://docs.platformio.org/en/stable/integration/ide/vscode.html). Then open a project using the WiSniff folder. It may take ages to setup. This is normal. Just let it run it's course. Afterwards, all should be setup.  

The important files to pay attention to are as follows:
```text
Project Root
├── include/              # Global application header files (.h)
├── lib/                  # Local isolated custom libraries
├── managed_components/   # Automatically managed ESP-IDF components and trees
├── src/                  # Main execution source directory
│   └──  main.cpp          # Main application code (Sniffer setup & execution loops)
├── test/                 # System automation and framework test validation runs
└── platformio.ini        # Project configuration profile (Boards, flags, and dependencies)
```


## Report #1 offline analysis

See [Report1_README.md](Report1_README.md) for Python setup, synthetic experiments, controlled-capture file ingestion, and evaluation. Developer notes are in [analysis/README.md](analysis/README.md).

## Pi-Integration

On the Pi, start collection without a desktop:

```sh
/home/xrpi4/ece9500-repo/analysis/.venv/bin/python /home/xrpi4/ece9500-repo/wisniff/tools/csi_data.py --headless --host 0.0.0.0 --port 9000 --receiver-id RX1 --channel 6
```

Connect the ESP32 RX to the Pi's reachable IP on port 9000. Use a fixed-channel
2.4 GHz access point, with the RX and ESP-NOW transmitters on channel 6.
Send UTF-8 lines ending in a newline:

```text
CSI,<receiver_millis>,<RSSI>,<channel>,<count>,0,<magnitudes...>
# POSE_EVENT,P01,CAPTURE_START,<receiver_millis>
# POSE_EVENT,P01,CAPTURE_END,<receiver_millis>
```

Each recording gets a private folder under `analysis/data/raw/run-*/`, containing
`csi.csv`, `pose_events.csv`, `session.json`, and `collector.log`. Ctrl+C saves and
closes it. Replace `--headless` with `--plot` for a display, or use serial:
`analysis/.venv/bin/python wisniff/tools/csi_data.py /dev/ttyUSB0 --headless`.

For collection after SSH closes, follow the [systemd setup](wisniff/tools/systemd/README.md).
Stop that service before running a foreground collector on the same port.
The [protocol and firmware handoff](wisniff/tools/TCP_PROTOCOL.md) explains metadata,
clock resets, and the proposed future transmitter-ID format. Legacy rows have no
transmitter ID. Pi mock tests pass; the teammate still needs to add the TCP sender
and pose markers, then verify a real RX, SSH logout, and optional reboot startup.
Keep captures out of Git; copy recordings to another computer with `scp` or `rsync`.
