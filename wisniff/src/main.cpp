#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>
#include <esp_random.h>
#include "soc/soc_caps.h"
#include <string.h>

// 0 = TX (steady pinger, full CSI)
// 1 = RX (capture)
// 2 = MOCK (fake mobile device: irregular transmissions, RSSI only at the RX)
#define ROLE 2

#define ROLE_TX 0
#define ROLE_RX 1
#define ROLE_MOCK 2

#undef CSI_CHANNEL
#define CSI_CHANNEL 1 // must match the hotspot's channel

#undef TX_INTERVAL_MS
#define TX_INTERVAL_MS 10 // 100 Hz, matches Wi-CaL

#ifndef MOCK_MIN_MS
#define MOCK_MIN_MS 10 // mock sends every MOCK_MIN_MS..MOCK_MAX_MS (random)
#endif
#ifndef MOCK_MAX_MS
#define MOCK_MAX_MS 50
#endif

#define PKT_MAGIC 0xC51C51A5u

struct __attribute__((packed)) Pkt
{
    uint32_t magic;
    uint32_t seq;
};

static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static void check(esp_err_t e, const char *what)
{
    if (e != ESP_OK)
        Serial.printf("# ERROR %s: %s\n", what, esp_err_to_name(e));
}

static void wifiCommon()
{
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    WiFi.setSleep(false);
    check(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20), "bandwidth");
    check(esp_wifi_set_channel(CSI_CHANNEL, WIFI_SECOND_CHAN_NONE), "channel");
}

// ================== TX and MOCK share the same radio setup ==================
#if ROLE == ROLE_TX || ROLE == ROLE_MOCK

static void startEspNowTx()
{
    check(esp_now_init(), "esp_now_init");
    esp_now_peer_info_t p = {};
    memcpy(p.peer_addr, BCAST, 6);
    p.channel = 0;
    p.ifidx = WIFI_IF_STA;
    p.encrypt = false;
    check(esp_now_add_peer(&p), "add_peer");

    esp_now_rate_config_t rc = {};
    rc.phymode = WIFI_PHY_MODE_HT20;
    rc.rate = WIFI_PHY_RATE_MCS0_LGI; // OFDM so the RX can decode / measure it
    check(esp_now_set_peer_rate_config(BCAST, &rc), "set_peer_rate_config");
}

void setup()
{
    Serial.begin(921600);
    delay(500);
    wifiCommon();
#if ROLE == ROLE_TX
    Serial.printf("# TX node %s, channel %d, interval %d ms\n",
                  WiFi.macAddress().c_str(), CSI_CHANNEL, TX_INTERVAL_MS);
#else
    Serial.printf("# MOCK node %s, channel %d, interval %d-%d ms\n",
                  WiFi.macAddress().c_str(), CSI_CHANNEL, MOCK_MIN_MS, MOCK_MAX_MS);
#endif
    startEspNowTx();
}

// ====================== TX ======================
#if ROLE == ROLE_TX
void loop()
{
    static uint32_t seq = 0, sent = 0, fail = 0, lastStat = 0;
    static TickType_t last = xTaskGetTickCount();

    Pkt p = {PKT_MAGIC, seq++};
    if (esp_now_send(BCAST, (uint8_t *)&p, sizeof(p)) == ESP_OK)
        sent++;
    else
        fail++;
    vTaskDelayUntil(&last, pdMS_TO_TICKS(TX_INTERVAL_MS)); // steady period, no drift

    if (millis() - lastStat >= 2000)
    {
        lastStat = millis();
        Serial.printf("# tx sent=%lu fail=%lu\n", (unsigned long)sent, (unsigned long)fail);
    }
}

// ====================== MOCK ======================
#else
void loop()
{
    static uint32_t seq = 0, sent = 0, fail = 0, lastStat = 0;

    Pkt p = {PKT_MAGIC, seq++};
    if (esp_now_send(BCAST, (uint8_t *)&p, sizeof(p)) == ESP_OK)
        sent++;
    else
        fail++;

    // irregular gap, like a phone: uniform random in [MOCK_MIN_MS, MOCK_MAX_MS]
    uint32_t wait = MOCK_MIN_MS + (esp_random() % (MOCK_MAX_MS - MOCK_MIN_MS + 1));
    vTaskDelay(pdMS_TO_TICKS(wait));

    if (millis() - lastStat >= 2000)
    {
        lastStat = millis();
        Serial.printf("# mock sent=%lu fail=%lu\n", (unsigned long)sent, (unsigned long)fail);
    }
}
#endif

// ====================== RX ======================
#elif ROLE == ROLE_RX

// ESP32 TX (full CSI). Printed at the TX board's boot: "# TX node ..."
static const uint8_t ESP_TX_MAC[6] = {0xD8, 0x85, 0xAC, 0x60, 0x00, 0x9C};
#define TX_LABEL "ESP"

// ---- Everything below is RSSI only. Laptops AND mock ESP32s go here. ----
// Labels: no commas.
struct KnownDev
{
    const char *label;
    uint8_t mac[6];
};
static const KnownDev KNOWN[] = {
    // 7A:77:D2:97:16:FB (Jake)
    {"LAP1", {0x7A, 0x77, 0xD2, 0x97, 0x16, 0xFB}},
    // 30:89:4a:6f:b5:71 (Cindy)
    {"LAP2", {0x30, 0x89, 0x4A, 0x6F, 0xB5, 0x71}},
    // mock "mobile" ESP32s: paste the MAC each prints at boot ("# MOCK node ...")
    {"MOCK1", {0xD8, 0x85, 0xAC, 0x60, 0x3B, 0x64}}, // <-- set me
    {"MOCK2", {0x30, 0xED, 0xA0, 0xE7, 0xF1, 0x88}}, // <-- set me
};
#define N_KNOWN (sizeof(KNOWN) / sizeof(KNOWN[0]))

#define CSI_EXPECTED_LEN 114
#define CSI_DC_INDEX 28
#define SC_MAX 26
#define MAX_SC (2 * SC_MAX)

enum : uint8_t
{
    EV_CSI = 0,
    EV_PKT = 1
};
struct Event
{
    uint32_t ts_ms;
    int8_t rssi;
    uint8_t ch;
    uint8_t type; // EV_CSI / EV_PKT
    uint8_t dev;  // EV_PKT: index into KNOWN
    uint8_t n;    // EV_CSI: subcarrier count
    uint8_t mag[MAX_SC];
};

static QueueHandle_t evQueue;
static volatile uint32_t rxCount = 0, dropCount = 0, badLen = 0, csiOther = 0;
static volatile uint32_t devCount[N_KNOWN] = {0};
static volatile uint32_t otherCount = 0;

static inline uint8_t isqrt32(uint32_t x)
{
    uint32_t res = 0, bit = 1u << 14;
    while (bit > x)
        bit >>= 2;
    while (bit)
    {
        if (x >= res + bit)
        {
            x -= res + bit;
            res = (res >> 1) + bit;
        }
        else
            res >>= 1;
        bit >>= 2;
    }
    return (uint8_t)res;
}

// ---- Source classification: the ONLY place MAC addresses are interpreted. ----
// Returns index into KNOWN, or -1 if unknown. Swap this out later for MAC-blind operation.
static int classify(const uint8_t *mac)
{
    for (size_t i = 0; i < N_KNOWN; i++)
        if (memcmp(mac, KNOWN[i].mac, 6) == 0)
            return (int)i;
    return -1;
}

// Wi-Fi task context: keep short, no printing.
static void csiCb(void *ctx, wifi_csi_info_t *info)
{
    if (!info || !info->buf)
        return;

    // 1) ESP32 TX: full CSI
    if (memcmp(info->mac, ESP_TX_MAC, 6) == 0)
    {
        if (info->len != CSI_EXPECTED_LEN)
        {
            badLen++;
            return;
        }

        static Event e;
        e.type = EV_CSI;
        e.ts_ms = millis();
        e.rssi = info->rx_ctrl.rssi;
        e.ch = info->rx_ctrl.channel;
        e.dev = 0;

        uint8_t w = 0;
        for (int k = -SC_MAX; k <= SC_MAX; k++)
        {
            if (k == 0)
                continue;
            int idx = k + CSI_DC_INDEX;
            int32_t im = info->buf[2 * idx];
            int32_t re = info->buf[2 * idx + 1];
            e.mag[w++] = isqrt32((uint32_t)(re * re + im * im));
        }
        e.n = w;

        rxCount++;
        if (xQueueSend(evQueue, &e, 0) != pdTRUE)
            dropCount++;
        return;
    }

    // 2) Known laptop or mock ESP32: RSSI only
    int idx = classify(info->mac);
    if (idx >= 0)
    {
        Event p = {};
        p.type = EV_PKT;
        p.ts_ms = millis();
        p.rssi = info->rx_ctrl.rssi;
        p.ch = info->rx_ctrl.channel;
        p.dev = (uint8_t)idx;
        devCount[idx]++;
        if (xQueueSend(evQueue, &p, 0) != pdTRUE)
            dropCount++;
        return;
    }

    csiOther++; // anything else: count only
}

// The sniffer exists so the radio stays in promiscuous mode (it hears other devices'
// frames). It only counts unknown data frames.
static void sniffCb(void *buf, wifi_promiscuous_pkt_type_t type)
{
    if (type != WIFI_PKT_DATA)
        return;
    const wifi_promiscuous_pkt_t *pkt = (const wifi_promiscuous_pkt_t *)buf;
    if (pkt->rx_ctrl.sig_len < 24)
        return;
    if (classify(pkt->payload + 10) < 0)
        otherCount++;
}

static void startCsi()
{
    wifi_csi_config_t cfg = {};
#if SOC_WIFI_HE_SUPPORT
    cfg.enable = 1;
    cfg.acquire_csi_legacy = 1;
    cfg.acquire_csi_ht20 = 1;
    cfg.acquire_csi_su = 1;
#else
    cfg.lltf_en = true;
    cfg.htltf_en = true;
    cfg.stbc_htltf2_en = true;
    cfg.ltf_merge_en = true;
    cfg.channel_filter_en = true;
#endif
    check(esp_wifi_set_csi_config(&cfg), "set_csi_config");
    check(esp_wifi_set_csi_rx_cb(csiCb, nullptr), "set_csi_rx_cb");
    check(esp_wifi_set_csi(true), "set_csi");
}

static void startSniffer()
{
    wifi_promiscuous_filter_t flt = {};
    // MGMT too, so ESP-NOW (action) frames from the TX and mocks still reach the CSI path.
    flt.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA;
    check(esp_wifi_set_promiscuous_filter(&flt), "promisc_filter");
    check(esp_wifi_set_promiscuous_rx_cb(sniffCb), "promisc_cb");
    check(esp_wifi_set_promiscuous(true), "promisc");
    check(esp_wifi_set_channel(CSI_CHANNEL, WIFI_SECOND_CHAN_NONE), "channel(after promisc)");
}

static void emit(const Event &e)
{
    static char line[512];
    int k;
    if (e.type == EV_CSI)
    {
        // CSI,ts_ms,rssi,channel,n,label,mag0,mag1,...
        k = snprintf(line, sizeof(line), "CSI,%lu,%d,%u,%u,%s",
                     (unsigned long)e.ts_ms, e.rssi, e.ch, e.n, TX_LABEL);
        for (uint8_t i = 0; i < e.n && k < (int)sizeof(line) - 6; i++)
            k += snprintf(line + k, sizeof(line) - k, ",%u", e.mag[i]);
    }
    else
    {
        // PKT,ts_ms,rssi,channel,label
        k = snprintf(line, sizeof(line), "PKT,%lu,%d,%u,%s",
                     (unsigned long)e.ts_ms, e.rssi, e.ch, KNOWN[e.dev].label);
    }
    line[k++] = '\n';
    Serial.write((uint8_t *)line, k);
}

void setup()
{
    Serial.begin(921600);
    delay(1000);
    evQueue = xQueueCreate(128, sizeof(Event));
    wifiCommon();
    Serial.printf("# RX node %s, channel %d, expecting TX %02X:%02X:%02X:%02X:%02X:%02X\n",
                  WiFi.macAddress().c_str(), CSI_CHANNEL,
                  ESP_TX_MAC[0], ESP_TX_MAC[1], ESP_TX_MAC[2],
                  ESP_TX_MAC[3], ESP_TX_MAC[4], ESP_TX_MAC[5]);
    startCsi();
    startSniffer();
}

void loop()
{
    static uint32_t lastStat = 0;
    static Event e;

    // wait briefly for the first event, then drain whatever backlog has built up
    if (xQueueReceive(evQueue, &e, pdMS_TO_TICKS(5)) == pdTRUE)
    {
        do
        {
            emit(e);
        } while (xQueueReceive(evQueue, &e, 0) == pdTRUE);
    }

    uint32_t now = millis();
    if (now - lastStat >= 2000)
    {
        lastStat = now;
        Serial.printf("# esp=%lu drop=%lu bad_len=%lu", (unsigned long)rxCount,
                      (unsigned long)dropCount, (unsigned long)badLen);
        for (size_t i = 0; i < N_KNOWN; i++)
            Serial.printf(" %s=%lu", KNOWN[i].label, (unsigned long)devCount[i]);
        Serial.printf(" other_data=%lu other_csi=%lu\n",
                      (unsigned long)otherCount, (unsigned long)csiOther);
    }
}

#else
#error "ROLE must be 0 (TX), 1 (RX) or 2 (MOCK)"
#endif