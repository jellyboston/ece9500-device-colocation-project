# Pi TCP tests

The new RX firmware and combined Uno capture are documented in
[RX TCP and Uno setup](../wisniff/tools/RX_TCP_SETUP.md). Tests cover labeled CSI/PKT,
concurrent Uno events and the firmware's nonblocking TCP transport. The native
transport/private-flag checks need a C++ compiler; pseudo-serial checks need
POSIX and pyserial. Legacy framing tests remain supported.

Run from the repository root:

```sh
python3 -m unittest discover -s pi-tcp-tests -v
```

These tests open real loopback TCP connections and check saved files and counts.
Each scenario has its own file with its purpose and expected output in a docstring.
They use temporary directories, need no ESP32 or desktop, and do not write capture
data into Git. They verify the Pi receiver; real firmware, RF packet loss, and
operation across SSH logout or reboot require separate hardware checks.

Optional Linux pseudo-terminal check for the retained serial command (requires
`pyserial` from the analysis environment):

```sh
analysis/.venv/bin/python pi-tcp-tests/serial_smoke.py
```
