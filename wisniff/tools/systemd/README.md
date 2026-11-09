# Unattended Pi collection

Run the foreground command in the top-level README first. This unit uses the
checkout and virtual environment at `/home/xrpi4/ece9500-repo`, runs as `xrpi4`,
and listens for RX1 on port 9000 using `rssi-labeled-v1`, expecting channel 1. Edit those settings before
installation if the experiment uses different values. Each process start makes
a new recording directory; reconnects stay in the current recording.

For Uno capture, append `--uno-port /dev/serial/by-id/YOUR_UNO --uno-baud 115200`
to ExecStart after identifying the actual port. See [RX TCP and Uno setup](../RX_TCP_SETUP.md)
for private flags, upload and timing limitations. Uno input is disabled in the
example unit until an actual port is configured.

Install and start from the repository root:

```sh
install -d -m 700 /home/xrpi4/ece9500-repo/analysis/data/raw
sudo install -m 644 wisniff/tools/systemd/ece9500-csi.service /etc/systemd/system/ece9500-csi.service
sudo systemctl daemon-reload
sudo systemctl start ece9500-csi.service
sudo systemctl status ece9500-csi.service --no-pager
sudo journalctl -u ece9500-csi.service -f
```

Stop any foreground listener before starting the service. The service restarts
on failures; an intentional `sudo systemctl stop ece9500-csi.service` stops it.
SIGTERM flushes and closes capture files. `collector.log` also retains diagnostics
inside each recording. Current counts and connection boundaries are updated in
`session.json` every second, at events, at disconnect, and on clean shutdown.
Files are private to `xrpi4`; output directories are mode 700 and files mode 600.

A system service continues after VS Code or SSH closes. Verify this with a real
stream: note CSV row count, disconnect SSH, reconnect, check `systemctl status`
and confirm that the count increased. Do not run a second collector on port 9000.

If collection should start at boot, enable it explicitly, then test a reboot:

```sh
sudo systemctl enable ece9500-csi.service
# Reboot only when the experiment and other Pi work can be interrupted.
# After the next reboot:
sudo systemctl is-active ece9500-csi.service
sudo journalctl -b -u ece9500-csi.service --no-pager
```

Real RX, SSH logout, and reboot checks are separate from the mock TCP tests.
