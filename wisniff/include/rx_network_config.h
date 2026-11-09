#pragma once

// Names only: credentials are supplied by ignored private_build_flags.ini.
#ifndef WIFI_SSID
#ifdef wifi_ssid
#define WIFI_SSID wifi_ssid
#endif
#endif
#ifndef WIFI_PASSWORD
#ifdef wifi_pass
#define WIFI_PASSWORD wifi_pass
#elif defined(WIFI_PASS)
#define WIFI_PASSWORD WIFI_PASS
#endif
#endif
#ifndef WIFI_SSID
#error "RX TCP requires WIFI_SSID or wifi_ssid in security.build_flags"
#endif
#ifndef WIFI_PASSWORD
#error "RX TCP requires WIFI_PASSWORD, WIFI_PASS or wifi_pass in security.build_flags"
#endif
#ifndef PI_TCP_HOST
#error "RX TCP requires quoted PI_TCP_HOST (the Pi hotspot IPv4 address) in security.build_flags"
#endif
#ifndef PI_TCP_PORT
#define PI_TCP_PORT 9000
#endif
#ifndef RX_RECEIVER_ID
#define RX_RECEIVER_ID "RX1"
#endif
static_assert(PI_TCP_PORT > 0 && PI_TCP_PORT < 65536, "PI_TCP_PORT must be 1..65535");
