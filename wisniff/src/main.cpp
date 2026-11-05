#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>
#include "soc/soc_caps.h"
#include <math.h>
#include <string.h>

#ifndef CSI_CHANNEL
#define CSI_CHANNEL 6
#endif
#ifndef TX_INTERVAL_MS
#define TX_INTERVAL_MS 20
#endif

#define MAX_SC 306
#define PKT_MAGIC 0xC51C51A5u

struct __attribute__((packed)) Pkt
{
    uint32_t magic;
    uint32_t seq;
};

struct CsiFrame
{
    uint32_t ts_ms;
    int8_t rssi;
    uint8_t ch;
    uint16_t n;
    uint8_t mag[MAX_SC]; // |CSI| per subcarrier (max ~181)
};

static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static uint8_t peerMac[6];
static volatile bool havePeer = false;
static QueueHandle_t csiQueue;
static volatile uint32_t rxCount = 0;

static void check(esp_err_t e, const char *what)
{
    if (e != ESP_OK)
        Serial.printf("# ERROR %s: %s\n", what, esp_err_to_name(e));
}

// ESP-NOW receive: used only to learn the peer's MAC.
static void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    if (havePeer || len < (int)sizeof(Pkt))
        return;
    Pkt p;
    memcpy(&p, data, sizeof(p));
    //   handshake verification
    if (p.magic != PKT_MAGIC)
        return;
    //   get the MAC address
    memcpy(peerMac, info->src_addr, 6);
    havePeer = true;
}

// Wi-Fi task context: keep short, no printing.
// Integer square root (input max 2*128*128 = 32768, result max ~181). No FPU needed.
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
        {
            res >>= 1;
        }
        bit >>= 2;
    }
    return (uint8_t)res;
}

// Wi-Fi task context: keep short, no printing, no floating point.
static void csiCb(void *ctx, wifi_csi_info_t *info)
{
    if (!havePeer || !info || !info->buf || info->len < 2)
        return;
    if (memcmp(info->mac, peerMac, 6) != 0)
        return;

    static CsiFrame f;
    f.ts_ms = millis();
    f.rssi = info->rx_ctrl.rssi;
    f.ch = info->rx_ctrl.channel;
    uint16_t n = info->len / 2;
    if (n > MAX_SC)
        n = MAX_SC;
    f.n = n;
    for (uint16_t i = 0; i < n; i++)
    { // buf = [imag, real, imag, real, ...]
        int32_t im = info->buf[2 * i];
        int32_t re = info->buf[2 * i + 1];
        f.mag[i] = isqrt32((uint32_t)(re * re + im * im));
    }
    rxCount++;
    xQueueSend(csiQueue, &f, 0);
}

static void startCsi()
{
    wifi_csi_config_t cfg = {};
//   For C5 / C6 / C61 use the Wi-Fi 6 struct
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

static void startEspNow()
{
    check(esp_now_init(), "esp_now_init");
    esp_now_register_recv_cb(onRecv);

    esp_now_peer_info_t p = {};
    memcpy(p.peer_addr, BCAST, 6);
    p.channel = 0; // use current channel
    p.ifidx = WIFI_IF_STA;
    p.encrypt = false;
    check(esp_now_add_peer(&p), "add_peer");

    // Force an OFDM (HT MCS0) rate so frames carry CSI.
    esp_now_rate_config_t rc = {};
    rc.phymode = WIFI_PHY_MODE_HT20;
    rc.rate = WIFI_PHY_RATE_MCS0_LGI;
    check(esp_now_set_peer_rate_config(BCAST, &rc), "set_peer_rate_config");
}

void setup()
{
    Serial.begin(921600);
    delay(1000);
    csiQueue = xQueueCreate(8, sizeof(CsiFrame));

    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    WiFi.setSleep(false);
    check(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20), "bandwidth");
    check(esp_wifi_set_channel(CSI_CHANNEL, WIFI_SECOND_CHAN_NONE), "channel");

    Serial.printf("# node %s, channel %d\n", WiFi.macAddress().c_str(), CSI_CHANNEL);
    startEspNow();
    startCsi();
}

void loop()
{
    static uint32_t lastTx = 0, lastStat = 0, seq = 0;
    static CsiFrame f;
    static char line[2048];

    uint32_t now = millis();
    if (now - lastTx >= TX_INTERVAL_MS)
    {
        lastTx = now;
        Pkt p = {PKT_MAGIC, seq++};
        esp_now_send(BCAST, (uint8_t *)&p, sizeof(p));
    }

    if (xQueueReceive(csiQueue, &f, pdMS_TO_TICKS(2)) == pdTRUE)
    {
        int k = snprintf(line, sizeof(line), "CSI,%lu,%d,%u,%u,%u",
                         (unsigned long)f.ts_ms, f.rssi, f.ch, f.n, 0u);
        // field layout: CSI,ts_ms,rssi,channel,n,0,mag0,mag1,...
        for (uint16_t i = 0; i < f.n && k < (int)sizeof(line) - 6; i++)
            k += snprintf(line + k, sizeof(line) - k, ",%u", f.mag[i]);
        line[k++] = '\n';
        Serial.write((uint8_t *)line, k);
    }

    if (now - lastStat >= 2000)
    {
        lastStat = now;
        if (havePeer)
            Serial.printf("# peer %02X:%02X:%02X:%02X:%02X:%02X, csi frames=%lu\n",
                          peerMac[0], peerMac[1], peerMac[2], peerMac[3], peerMac[4], peerMac[5],
                          (unsigned long)rxCount);
        else
            Serial.println("# searching for peer...");
    }
}