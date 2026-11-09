"""Generate controlled laptop Wi-Fi traffic; this does not measure RSSI.

Start `receive` on the Pi and `send --host <Pi hotspot IP>` on each laptop.
The ESP32 sniffer identifies Wi-Fi transmitter MACs, not this UDP payload.
Python standard library only. Run over Wi-Fi, not a laptop Ethernet connection.
"""

import argparse
from collections import Counter
import math
import socket
import time


def positive_rate(value):
    rate = float(value)
    if not math.isfinite(rate) or rate <= 0:
        raise argparse.ArgumentTypeError("rate must be positive and finite")
    return rate


def run_sender(host, port, rate, duration):
    interval = 1.0 / rate
    start = next_send = time.monotonic()
    sent = 0
    print(f"Sending to {host}:{port} at target {rate:g} datagrams/s; Ctrl+C stops.", flush=True)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            while duration == 0 or time.monotonic() - start < duration:
                payload = f"ECE9500_WIFI_TRAFFIC {sent}".encode("ascii").ljust(200, b".")
                sock.sendto(payload, (host, port))
                sent += 1
                next_send += interval
                # Do not produce a catch-up burst after a long scheduler pause.
                now = time.monotonic()
                if next_send < now:
                    next_send = now + interval
                time.sleep(max(0, next_send - now))
    except KeyboardInterrupt:
        pass
    elapsed = time.monotonic() - start
    print(f"Sent {sent} datagrams in {elapsed:.2f}s. This is not the ESP32 capture count.")


def run_receiver(host, port, duration):
    start = last_report = time.monotonic()
    counts = Counter()
    print(f"Receiving UDP traffic on {host}:{port}; Ctrl+C stops.", flush=True)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((host, port))
            sock.settimeout(0.25)
            while duration == 0 or time.monotonic() - start < duration:
                try:
                    _, address = sock.recvfrom(4096)
                    counts[address[0]] += 1
                except socket.timeout:
                    pass
                now = time.monotonic()
                if now - last_report >= 5:
                    print(f"Received {sum(counts.values())} datagrams from {len(counts)} source IPs.", flush=True)
                    last_report = now
    except KeyboardInterrupt:
        pass
    print(f"Total received: {sum(counts.values())} datagrams from {len(counts)} source IPs.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("send", "receive"):
        child = subcommands.add_parser(command)
        child.add_argument("--host", required=command == "send", default="0.0.0.0" if command == "receive" else None)
        child.add_argument("--port", type=int, default=9001)
        child.add_argument("--duration", type=float, default=0, help="seconds; 0 runs until Ctrl+C")
        if command == "send":
            child.add_argument("--rate", type=positive_rate, default=20.0)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("duration must be finite and nonnegative")
    try:
        if args.command == "send":
            run_sender(args.host, args.port, args.rate, args.duration)
        else:
            run_receiver(args.host, args.port, args.duration)
    except OSError as exc:
        parser.exit(2, f"Network error: {exc}\n")


if __name__ == "__main__":
    main()
