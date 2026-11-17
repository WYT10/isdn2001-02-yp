#include "flow_sensor.h"
#include "wifi.h"
#include "esp_cpu.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <inttypes.h>
#include <math.h>
#include <stdio.h>

#ifndef FLOW_RUN_SELF_TEST
#define FLOW_RUN_SELF_TEST 0
#endif

typedef struct {
    flow_sensor_config_t sensor;
    wifi_settings_t wifi;
    struct {
        bool benchmark;
        bool self_test;
        int test_gpio;
    } diagnostics;
} app_config_t;

static const app_config_t app = {
    .sensor = {
        .gpio = 9, /* XIAO D10: sensor input only. */
        .pull_up = true,
        .capture_timing = true,
        .glitch_filter_ns = 1000,
        .stale_after_us = 2000000,
        .report_ms = 250,
        .window_samples = 4,
        .pulses_per_litre = 0.0, /* Unknown until calibrated. */
    },
    .wifi = {
        .ssid = "ABCD",
        .password = "00000000",
        .retry_delay_ms = 5000,
        .status_interval_ms = 60000,
        .fallback = {
            .enabled = true,
            .ssid = "SensorLab-Local",
            .password = "00000000",
            .after_ms = 60000,
            .retry_delay_ms = 30000,
            .channel = 6,
            .max_clients = 4,
        },
    },
    .diagnostics = {
        .benchmark = true,
        .self_test = FLOW_RUN_SELF_TEST,
        .test_gpio = 4, /* XIAO D3: disconnected during synthetic tests. */
    },
};

void app_main(void)
{
    setvbuf(stdout, NULL, _IOLBF, 0);
    /* Allow time for native USB to enumerate and a monitor to attach. */
    vTaskDelay(pdMS_TO_TICKS(3000));
    printf("{\"type\":\"boot\",\"sensor\":\"ZJ-S201C\",\"pin\":\"D10\","
           "\"gpio\":%d,\"report_ms\":%" PRIu32 ",\"pulses_per_litre\":%.6f,"
           "\"calibrated\":%s,\"selftest\":%s}\n", app.sensor.gpio,
           app.sensor.report_ms, app.sensor.pulses_per_litre,
           app.sensor.pulses_per_litre > 0 ? "true" : "false",
           app.diagnostics.self_test ? "true" : "false");
    if (app.diagnostics.benchmark) flow_sensor_benchmark();
    if (app.diagnostics.self_test)
        flow_sensor_selftest(&app.sensor, app.diagnostics.test_gpio);
    flow_sensor_start(&app.sensor);
    flow_sensor_snapshot_t previous, current;
    flow_sensor_snapshot(&previous);
    ESP_ERROR_CHECK(wifi_start(&app.wifi));
    uint64_t total = previous.count;
    uint32_t counts[FLOW_SENSOR_WINDOW_CAPACITY] = {0};
    uint64_t times[FLOW_SENSOR_WINDOW_CAPACITY] = {0};
    unsigned index = 0;
    TickType_t wake = xTaskGetTickCount();
    while (true) {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(app.sensor.report_ms));
        int64_t work_start = esp_timer_get_time();
        uint32_t cycles_start = esp_cpu_get_cycle_count();
        flow_sensor_snapshot(&current);
        uint32_t delta = flow_count_delta(previous.count, current.count);
        uint64_t dt = current.time_us - previous.time_us;
        total += delta;
        counts[index] = delta;
        times[index] = dt;
        index = (index + 1) % app.sensor.window_samples;
        uint64_t window_pulses = 0, window_us = 0;
        for (unsigned i = 0; i < app.sensor.window_samples; ++i) {
            window_pulses += counts[i];
            window_us += times[i];
        }
        double hz = flow_frequency(window_pulses, window_us);
        double lpm = flow_lpm(hz, app.sensor.pulses_per_litre);
        double litres = flow_litres(total, app.sensor.pulses_per_litre);
        char rate[40] = "null", volume[40] = "null", pulse[160] = "null";
        if (isfinite(lpm)) snprintf(rate, sizeof(rate), "%.6f", lpm);
        if (isfinite(litres)) snprintf(volume, sizeof(volume), "%.9f", litres);
        if (current.timing_valid) {
            double period_us = 1e6 * current.period_ticks / current.capture_hz;
            double high_us = 1e6 * current.high_ticks / current.capture_hz;
            snprintf(pulse, sizeof(pulse),
                "{\"hz\":%.5f,\"high_us\":%.3f,\"low_us\":%.3f,\"duty_pct\":%.3f}",
                1e6 / period_us, high_us, period_us - high_us, 100.0 * high_us / period_us);
        }
        uint32_t cycles = esp_cpu_get_cycle_count() - cycles_start;
        int64_t work_us = esp_timer_get_time() - work_start;
        static char reading[WIFI_READING_CAPACITY];
        int length = snprintf(reading, sizeof(reading),
               "{\"type\":\"flow\",\"uptime_us\":%" PRId64 ",\"dt_us\":%" PRIu64 ","
               "\"pulses\":%" PRIu32 ",\"total_pulses\":%" PRIu64 ",\"window_us\":%" PRIu64 ","
               "\"frequency_hz\":%.5f,\"flow_lpm\":%s,\"total_l\":%s,"
               "\"pulse\":%s,\"read_calc_format_us\":%" PRId64 ",\"read_calc_format_cycles\":%" PRIu32 "}",
               current.time_us, dt, delta, total, window_us, hz, rate, volume,
               pulse, work_us, cycles);
        if (length <= 0 || (size_t)length >= sizeof(reading))
            ESP_ERROR_CHECK(ESP_ERR_INVALID_SIZE);
        ESP_ERROR_CHECK(wifi_publish_reading(reading, (size_t)length));
        puts(reading);
        previous = current;
    }
}
