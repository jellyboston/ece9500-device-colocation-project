#include <Arduino.h>
#include <WiFi.h>
#include "esp_wifi.h"

// CSI Callback function triggered on packet reception
void csi_rx_cb(void *ctx, wifi_csi_info_t *data) {
    // Extract metadata
    wifi_pkt_rx_ctrl_t rx_ctrl = data->rx_ctrl;
    
    // Check if there is payload buffer data
    if (data->buf == nullptr || data->len == 0) {
        return;
    }

    // Cast the raw buffer to signed 8-bit integers
    int8_t *csi_raw = (int8_t *)data->buf;
    
    // Each subcarrier uses 2 bytes: Imaginary (I) and Real (Q)
    int num_subcarriers = data->len / 2;

    Serial.printf("CSI_PACKET | RSSI: %d | Subcarriers: %d | Magnitudes: [", rx_ctrl.rssi, num_subcarriers);

    for (int i = 0; i < num_subcarriers; i++) {
        // Espressif packs data as: [Imaginary, Real, Imaginary, Real...]
        int8_t imaginary = csi_raw[i * 2];
        int8_t real      = csi_raw[i * 2 + 1];

        // Compute Magnitude = sqrt(Real^2 + Imaginary^2)
        float magnitude = sqrt((real * real) + (imaginary * imaginary));

        // Print values comma-separated
        Serial.print(magnitude, 2);
        if (i < num_subcarriers - 1) {
            Serial.print(", ");
        }
    }
    Serial.println("]");
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    // 1. Initialize Wi-Fi in Station mode
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.print("Connecting to Wi-Fi...");
    
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nConnected to Wi-Fi successfully!");

    // 2. Configure CSI parameters
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));

    // 2. Define clean operational bitfields for ESP32-C6 / C61 (Wi-Fi 6 MAC)
    wifi_csi_config_t csi_config = {
        .enable = 1,
        .acquire_csi_legacy = 1,      // Capture non-HT legacy frames
        .acquire_csi_ht20 = 1,        // Capture HT20 PPDU
        .acquire_csi_ht40 = 1,        // Capture HT40 PPDU
        .acquire_csi_su = 1,          // Capture HE20 Single User frames
        .acquire_csi_mu = 1,          // Capture HE20 Multi User frames
        .acquire_csi_dcm = 1,         // Capture Dual Carrier Modulation options
        .acquire_csi_beamformed = 1,  // Capture Beamformed profiles
        .val_scale_cfg = 0,           // Value scaling configuration flag
        .dump_ack_en = 0              // Do not dump ACK frames
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    // Apply configuration
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));

    // 3. Register our processing function as the callback
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_rx_cb, NULL));

    // 4. Turn on CSI Collection Globally
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
    Serial.println("CSI Engine Initialized and running...");
}

void loop() {
    // CSI runs asynchronously via hardware interrupts and the registered callback
    delay(1000); 
}
