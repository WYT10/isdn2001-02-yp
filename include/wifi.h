#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

enum { WIFI_READING_CAPACITY = 1024 };

typedef struct {
    bool enabled;
    char ssid[33];
    char password[65];
    uint32_t after_ms;
    uint32_t retry_delay_ms;
    uint8_t channel;
    uint8_t max_clients;
} wifi_fallback_settings_t;

typedef struct {
    char ssid[33];
    char password[65];
    uint32_t retry_delay_ms;
    uint32_t status_interval_ms;
    wifi_fallback_settings_t fallback;
} wifi_settings_t;

/* The ESP32 station is a singleton. Settings are copied before the task starts. */
esp_err_t wifi_start(const wifi_settings_t *settings);
esp_err_t wifi_publish_reading(const char *json, size_t length);
