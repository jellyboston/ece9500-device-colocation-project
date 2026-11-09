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

See [RX TCP and Uno setup](wisniff/tools/RX_TCP_SETUP.md) for private build flags,
receiver upload, Uno serial input, file schemas and timestamp limitations.

The Pi listens on port 9000; RX firmware connects as a client after joining the
same hotspot. Current firmware uses channel 1; configure every radio and the Pi
logger to the actual hotspot channel.

From the repository root on the Pi:

```bash
analysis/.venv/bin/python wisniff/tools/csi_data.py \
  --transport tcp --protocol rssi-labeled-v1 \
  --host 0.0.0.0 --port 9000 --receiver-id RX1 --channel 1 \
  --headless --output-dir analysis/data/raw
```

For simultaneous Uno movement notifications, append `--uno-port UNO_PORT
--uno-baud 115200`, replacing UNO_PORT with its actual USB serial path. Plain
START/STOP lines and timestamped `ROBOT,sequence,millis,event` records are supported.
Both streams are saved in one `capture.csv`; `observations.csv` exports labeled RF
rows for C3 ingestion. Independent Uno and ESP32 clocks are preserved, not silently
synchronized. Uno movement events alone do not supply ESP32-clock pose windows.

Build RX with `pio run -d wisniff -e esp32-c61-rx-tcp` using your existing ignored
private file and a PI_TCP_HOST define. Serial fallback is the rx-serial environment.

Legacy CSI remains available via `--protocol csi-legacy-v1` and existing test inputs.
See [Pi tests](pi-tcp-tests/README.md) and [systemd instructions](wisniff/tools/systemd/README.md).
