# laptop_ping.py  -  usage: python laptop_ping.py <gateway_ip> [rate_hz]
import socket, sys, time

target = sys.argv[1]
rate = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0
period = 1.0 / rate

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
payload = b"x" * 32
sent = errs = 0
nxt = time.perf_counter()
t_report = nxt + 1.0

while True:
    try:
        s.sendto(payload, (target, 9))
        sent += 1
    except OSError as e:
        errs += 1
        last_err = e
    nxt += period
    now = time.perf_counter()
    if now - nxt > period:          # fell behind: skip ahead instead of bursting
        nxt = now
    while time.perf_counter() < nxt:
        pass                        # spin: exact timing, uses one CPU core
    if time.perf_counter() >= t_report:
        print(f"sent={sent}/s errors={errs}", f"({last_err})" if errs else "")
        sent = errs = 0
        t_report += 1.0