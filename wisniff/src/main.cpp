#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoJson.h>
#include "esp_wifi.h"

#define DOT11_MGMT_TYPE     0
#define DOT11_PROBE_REQ_SUB 4

// Collection duration set to exactly 3 minutes (180,000 ms)
const unsigned long COLLECTION_TIME_MS = 180000; 
unsigned long sniffer_start_time = 0;
bool collection_complete = false;

// Fixed array tracking structures to ensure memory safety on RISC-V
struct StoredLog {
    char ecosystem[16];
    char network[33];
    int rssi;
    int channel;
    char mac[18];
    char raw_ie[128]; // Trimmed hex IE footprint safely contained
};

// Max records to hold in static RAM buffer to prevent heap memory exhaustion
#define MAX_LOGS 40
StoredLog log_buffer[MAX_LOGS];
int log_count = 0;

void sniffer_callback(void* buf, wifi_promiscuous_pkt_type_t type) {
    if (collection_complete || log_count >= MAX_LOGS) return;

    const wifi_promiscuous_pkt_t* packet = (wifi_promiscuous_pkt_t*)buf;
    const uint8_t* payload = packet->payload;
    uint32_t len = packet->rx_ctrl.sig_len;

    if (len < 24) return; 

    uint8_t frame_type = (payload[0] & 0x0C) >> 2;
    uint8_t frame_subtype = (payload[0] & 0xF0) >> 4;

    if (frame_type == DOT11_MGMT_TYPE && frame_subtype == DOT11_PROBE_REQ_SUB) {
        const uint8_t* src_mac = &payload[10];
        const uint8_t* bssid_mac = &payload[16];

        // Filter out commercial infrastructure devices using Broadcast BSSID verification
        if (bssid_mac[0] == 0xFF && bssid_mac[1] == 0xFF && bssid_mac[2] == 0xFF) {
            
            bool is_private_mac = (src_mac[0] & 0x02);
            bool profile_apple = false;
            bool profile_android = false;
            bool has_wps = false;
            char target_ssid[33] = {0};

            // Safely offset into information elements block
            uint32_t pos = 24; 
            while (pos < len - 2) {
                uint8_t ie_id = payload[pos];
                uint8_t ie_len = payload[pos + 1];
                
                if (pos + 2 + ie_len > len) break;
                uint32_t ie_data_idx = pos + 2;

                if (ie_id == 0 && ie_len <= 32) { // SSID Name
                    memcpy(target_ssid, &payload[ie_data_idx], ie_len);
                } 
                else if (ie_id == 221 && ie_len >= 3) { // Vendor specific fingerprint maps
                    uint8_t oui1 = payload[ie_data_idx];
                    uint8_t oui2 = payload[ie_data_idx + 1];
                    uint8_t oui3 = payload[ie_data_idx + 2];

                    if ((oui1 == 0x00 && oui2 == 0x17 && oui3 == 0xF2) || 
                        (oui1 == 0x00 && oui2 == 0x0D && oui3 == 0x3A)) {
                        profile_apple = true;
                    }
                    if (oui1 == 0x00 && oui2 == 0x1A && oui3 == 0x11) {
                        profile_android = true;
                    }
                    if (oui1 == 0x00 && oui2 == 0x50 && oui3 == 0xF2 && ie_len >= 4 && payload[ie_data_idx + 3] == 0x04) {
                        has_wps = true;
                    }
                }
                pos += 2 + ie_len;
            }

            // Lock structural index slot
            StoredLog* log = &log_buffer[log_count];

            if (profile_apple) strcpy(log->ecosystem, "apple");
            else if (profile_android) strcpy(log->ecosystem, "android");
            else if (has_wps && is_private_mac) strcpy(log->ecosystem, "android_windows");
            else if (!is_private_mac) strcpy(log->ecosystem, "fixed_hardware");
            else strcpy(log->ecosystem, "unknown_client");

            strcpy(log->network, (strlen(target_ssid) > 0) ? target_ssid : "wildcard_sweep");
            log->rssi = packet->rx_ctrl.rssi;
            log->channel = packet->rx_ctrl.channel;

            snprintf(log->mac, sizeof(log->mac), "%02X:%02X:%02X:%02X:%02X:%02X",
                     src_mac[0], src_mac[1], src_mac[2], src_mac[3], src_mac[4], src_mac[5]);

            // Save the raw Information Element footprint safely as a static string block
            uint32_t ie_len_total = (len > 24) ? (len - 24) : 0;
            if (ie_len_total > 0) {
                // Keep the string safe from overflows by capping it at half the destination buffer
                uint32_t write_bytes = (ie_len_total > 63) ? 63 : ie_len_total;
                char* ptr = log->raw_ie;
                for (uint32_t i = 0; i < write_bytes; i++) {
                    ptr += sprintf(ptr, "%02X", payload[24 + i]);
                }
                *ptr = '\0';
            } else {
                strcpy(log->raw_ie, "");
            }

            log_count++;
            Serial.printf("Logged Client #%d into RAM buffer.\n", log_count);
        }
    }
}

void print_final_json_dump() {
    // Dynamically size document on heap execution blocks to avoid stack boundaries
    JsonDocument doc;
    doc["collection_duration_seconds"] = COLLECTION_TIME_MS / 1000;
    doc["total_devices_intercepted"] = log_count;
    
    JsonArray devices = doc["devices"].to<JsonArray>();

    for (int i = 0; i < log_count; i++) {
        JsonObject device_obj = devices.add<JsonObject>();
        device_obj["mac"] = log_buffer[i].mac;
        device_obj["ecosystem"] = log_buffer[i].ecosystem;
        device_obj["requested_network"] = log_buffer[i].network;
        device_obj["rssi"] = log_buffer[i].rssi;
        device_obj["channel"] = log_buffer[i].channel;
        device_obj["raw_ie_hex_prefix"] = log_buffer[i].raw_ie;
    }

    Serial.println("\n\n========================================================");
    Serial.println("COPY-PASTABLE DATA BLOCK (PRETTIFIED JSON)");
    Serial.println("========================================================");
    serializeJsonPretty(doc, Serial); // Output completely clean formatting layout
    Serial.println("\n========================================================");
}

void setup() {
    Serial.begin(115200);
    delay(2000);
    Serial.println("\n--- ESP32-C61 Standalone 3-Minute Passive Sweeper ---");

    WiFi.mode(WIFI_STA);
    WiFi.disconnect(); 
    esp_wifi_set_ps(WIFI_PS_NONE);

    wifi_promiscuous_filter_t filter = {.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT};
    esp_wifi_set_promiscuous_filter(&filter);

    esp_wifi_set_promiscuous_rx_cb(&sniffer_callback);
    esp_wifi_set_promiscuous(true);

    esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE);
    
    sniffer_start_time = millis();
    Serial.println("Monitoring airwaves across all channels. Standby for 3 minutes...");
}

unsigned long last_channel_hop = 0;
uint8_t current_channel = 1;

void loop() {
    if (collection_complete) return;

    // Check timer boundary limits
    if (millis() - sniffer_start_time >= COLLECTION_TIME_MS) {
        collection_complete = true;
        esp_wifi_set_promiscuous(false); // Disarm sniffer immediately
        print_final_json_dump();
        return;
    }

    // Active channel hopper rotation loop
    if (millis() - last_channel_hop > 250) {
        current_channel++;
        if (current_channel > 13) current_channel = 1;
        
        esp_wifi_set_channel(current_channel, WIFI_SECOND_CHAN_NONE);
        last_channel_hop = millis();
    }
}
