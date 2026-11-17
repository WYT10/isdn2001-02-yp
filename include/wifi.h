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
    bool enabled;
    char identity[128];
    char username[128];
    char password[128];
    char server_domain[254];
    int64_t build_epoch;
} wifi_enterprise_settings_t;

typedef struct {
    char ssid[33];
    char password[65];
    wifi_enterprise_settings_t enterprise;
    uint32_t retry_delay_ms;
    uint32_t status_interval_ms;
    wifi_fallback_settings_t fallback;
} wifi_settings_t;

typedef struct {
    bool enabled;
    const char *url;
    const char *device_token;
    const char *label;
    uint32_t batch_interval_ms;
    uint32_t timeout_ms;
    int64_t build_epoch;
} wifi_cloud_settings_t;

esp_err_t wifi_cloud_start(const wifi_cloud_settings_t *settings);

/* The ESP32 station is a singleton. Settings are copied before the task starts. */
esp_err_t wifi_start(const wifi_settings_t *settings);
esp_err_t wifi_publish_reading(const char *json, size_t length);

typedef enum {
    WIFI_ACTION_SCAN, WIFI_ACTION_RECONNECT, WIFI_ACTION_AP_ON,
    WIFI_ACTION_AP_ONLY, WIFI_ACTION_AUTO, WIFI_ACTION_STATUS,
} wifi_action_t;

/* Mutations are queued and performed exclusively by the network task. */
esp_err_t wifi_request(wifi_action_t action);
