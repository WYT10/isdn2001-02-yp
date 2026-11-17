#include "flow_sensor.h"
#include "wifi.h"
#include "cli.h"
#include "sdkconfig.h"
#include "esp_cpu.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#ifndef FLOW_RUN_SELF_TEST
#define FLOW_RUN_SELF_TEST 0
#endif

typedef struct {
    const char *board_name;
    const char *sensor_pin;
    flow_sensor_config_t sensor;
    wifi_settings_t wifi;
    cli_settings_t cli;
    struct {
        bool benchmark;
        bool self_test;
        int test_gpio;
    } diagnostics;
} app_config_t;

static const app_config_t app = {
#if CONFIG_IDF_TARGET_ESP32
    .board_name = "ESP32-WROOM",
    .sensor_pin = "D15 / GPIO15",
#else
    .board_name = "XIAO ESP32-S3",
    .sensor_pin = "D10 / GPIO9",
#endif
    .sensor = {
#if CONFIG_IDF_TARGET_ESP32
        .gpio = 15, /* WROOM D15: sensor input only. */
#else
        .gpio = 9, /* XIAO D10: sensor input only. */
#endif
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
#if CONFIG_IDF_TARGET_ESP32
            .ssid = "SensorLab-WROOM",
#else
            .ssid = "SensorLab-Local",
#endif
            .password = "00000000",
            .after_ms = 60000,
            .retry_delay_ms = 30000,
            .channel = 6,
            .max_clients = 4,
        },
    },
    .cli = {.enabled = true, .stream = false},
    .diagnostics = {
        .benchmark = true,
        .self_test = FLOW_RUN_SELF_TEST,
        .test_gpio = 4, /* XIAO D3: disconnected during synthetic tests. */
    },
};

typedef struct {
    flow_sensor_config_t sensor;
    bool stream;
    uint32_t revision;
} runtime_config_t;

static QueueHandle_t commands;
static char reading[WIFI_READING_CAPACITY];

static bool submit_command(const cli_request_t *request, void *context)
{
    (void)context;
    return xQueueSend(commands, request, 0) == pdTRUE;
}

static bool apply_command(const cli_request_t *request, runtime_config_t *runtime)
{
    const char *name = cli_command_name(request->command);
    if (request->command == CLI_HELP) {
        puts("{\"type\":\"cli\",\"command\":\"help\",\"status\":\"ok\",\"commands\":["
             "\"help\",\"status\",\"get [parameter]\",\"set report_ms 50..10000\","
             "\"set window_samples 1..32\",\"set pulses_per_litre 0..1e9\","
             "\"stream on|off\",\"wifi status\",\"wifi scan\",\"wifi reconnect\","
             "\"wifi ap on\",\"wifi ap only\",\"wifi auto\",\"benchmark\",\"reboot\"],"
             "\"settings_volatile\":true,\"calibration_zero\":\"unknown\"}");
        return false;
    }
    if (request->command == CLI_STATUS) {
        printf("{\"type\":\"cli\",\"command\":\"status\",\"status\":\"ok\","
               "\"uptime_ms\":%" PRId64 ",\"free_heap\":%" PRIu32 ",\"stream\":%s,"
               "\"config_revision\":%" PRIu32 ",\"reading\":%s}\n",
               esp_timer_get_time() / 1000, esp_get_free_heap_size(),
               runtime->stream ? "true" : "false", runtime->revision,
               reading[0] ? reading : "null");
        return false;
    }
    if (request->command == CLI_GET) {
        if (request->parameter == CLI_PARAM_ALL) {
            printf("{\"type\":\"cli\",\"command\":\"get\",\"status\":\"ok\",\"config\":{"
                   "\"gpio\":%d,\"report_ms\":%" PRIu32 ",\"window_samples\":%u,"
                   "\"pulses_per_litre\":%.9g,\"stream\":%s,\"revision\":%" PRIu32 "},"
                   "\"persistent\":false}\n", runtime->sensor.gpio, runtime->sensor.report_ms,
                   runtime->sensor.window_samples, runtime->sensor.pulses_per_litre,
                   runtime->stream ? "true" : "false", runtime->revision);
        } else {
            double value = request->parameter == CLI_PARAM_REPORT_MS ? runtime->sensor.report_ms :
                request->parameter == CLI_PARAM_WINDOW_SAMPLES ? runtime->sensor.window_samples :
                runtime->sensor.pulses_per_litre;
            printf("{\"type\":\"cli\",\"command\":\"get\",\"status\":\"ok\","
                   "\"parameter\":\"%s\",\"value\":%.9g}\n",
                   cli_parameter_name(request->parameter), value);
        }
        return false;
    }
    if (request->command == CLI_SET) {
        if (request->parameter == CLI_PARAM_REPORT_MS) runtime->sensor.report_ms = request->value;
        else if (request->parameter == CLI_PARAM_WINDOW_SAMPLES) runtime->sensor.window_samples = request->value;
        else runtime->sensor.pulses_per_litre = request->value;
        ++runtime->revision;
        printf("{\"type\":\"cli\",\"command\":\"set\",\"status\":\"ok\","
               "\"parameter\":\"%s\",\"value\":%.9g,\"config_revision\":%" PRIu32 ","
               "\"persistent\":false}\n", cli_parameter_name(request->parameter),
               request->value, runtime->revision);
        return request->parameter != CLI_PARAM_PULSES_PER_LITRE;
    }
    if (request->command == CLI_STREAM) runtime->stream = request->value != 0;
    else if (request->command == CLI_BENCHMARK) flow_sensor_benchmark();
    else if (request->command == CLI_REBOOT) {
        puts("{\"type\":\"cli\",\"command\":\"reboot\",\"status\":\"ok\"}");
        vTaskDelay(pdMS_TO_TICKS(100));
        esp_restart();
    } else {
        wifi_action_t action = request->command == CLI_WIFI_SCAN ? WIFI_ACTION_SCAN :
            request->command == CLI_WIFI_RECONNECT ? WIFI_ACTION_RECONNECT :
            request->command == CLI_WIFI_AP_ON ? WIFI_ACTION_AP_ON :
            request->command == CLI_WIFI_AP_ONLY ? WIFI_ACTION_AP_ONLY :
            request->command == CLI_WIFI_STATUS ? WIFI_ACTION_STATUS : WIFI_ACTION_AUTO;
        esp_err_t error = wifi_request(action);
        printf("{\"type\":\"cli\",\"command\":\"%s\",\"status\":\"%s\",\"code\":%d}\n",
               name, error == ESP_OK ? "queued" : "error", error);
        return false;
    }
    printf("{\"type\":\"cli\",\"command\":\"%s\",\"status\":\"ok\"}\n", name);
    return false;
}

void app_main(void)
{
    setvbuf(stdout, NULL, _IOLBF, 0);
    /* Allow time for the serial bridge/native USB and a monitor to attach. */
    vTaskDelay(pdMS_TO_TICKS(3000));
    printf("{\"type\":\"boot\",\"board\":\"%s\",\"sensor\":\"ZJ-S201C\",\"pin\":\"%s\","
           "\"gpio\":%d,\"report_ms\":%" PRIu32 ",\"pulses_per_litre\":%.6f,"
           "\"calibrated\":%s,\"selftest\":%s}\n", app.board_name, app.sensor_pin, app.sensor.gpio,
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
    runtime_config_t runtime = {.sensor = app.sensor, .stream = app.cli.stream};
    commands = xQueueCreate(8, sizeof(cli_request_t));
    if (!commands) ESP_ERROR_CHECK(ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(cli_start(&app.cli, submit_command, NULL));
    uint64_t total = previous.count;
    uint32_t counts[FLOW_SENSOR_WINDOW_CAPACITY] = {0};
    uint64_t times[FLOW_SENSOR_WINDOW_CAPACITY] = {0};
    unsigned index = 0;
    TickType_t next_report = xTaskGetTickCount() + pdMS_TO_TICKS(runtime.sensor.report_ms);
    while (true) {
        TickType_t now = xTaskGetTickCount();
        TickType_t wait = (int32_t)(next_report - now) > 0 ? next_report - now : 0;
        cli_request_t request;
        if (xQueueReceive(commands, &request, wait) == pdTRUE && apply_command(&request, &runtime)) {
            memset(counts, 0, sizeof(counts));
            memset(times, 0, sizeof(times));
            index = 0;
            next_report = xTaskGetTickCount() + pdMS_TO_TICKS(runtime.sensor.report_ms);
        }
        if ((int32_t)(xTaskGetTickCount() - next_report) < 0) continue;
        next_report += pdMS_TO_TICKS(runtime.sensor.report_ms);
        int64_t work_start = esp_timer_get_time();
        uint32_t cycles_start = esp_cpu_get_cycle_count();
        flow_sensor_snapshot(&current);
        uint32_t delta = flow_count_delta(previous.count, current.count);
        uint64_t dt = current.time_us - previous.time_us;
        total += delta;
        counts[index] = delta;
        times[index] = dt;
        index = (index + 1) % runtime.sensor.window_samples;
        uint64_t window_pulses = 0, window_us = 0;
        for (unsigned i = 0; i < runtime.sensor.window_samples; ++i) {
            window_pulses += counts[i];
            window_us += times[i];
        }
        double hz = flow_frequency(window_pulses, window_us);
        double lpm = flow_lpm(hz, runtime.sensor.pulses_per_litre);
        double litres = flow_litres(total, runtime.sensor.pulses_per_litre);
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
        int length = snprintf(reading, sizeof(reading),
               "{\"type\":\"flow\",\"board\":\"%s\",\"gpio\":%d,\"uptime_us\":%" PRId64 ",\"dt_us\":%" PRIu64 ","
               "\"pulses\":%" PRIu32 ",\"total_pulses\":%" PRIu64 ",\"window_us\":%" PRIu64 ","
               "\"frequency_hz\":%.5f,\"flow_lpm\":%s,\"total_l\":%s,"
               "\"pulse\":%s,\"read_calc_format_us\":%" PRId64 ",\"read_calc_format_cycles\":%" PRIu32 ","
               "\"config_revision\":%" PRIu32 ",\"report_ms\":%" PRIu32 ",\"window_samples\":%u,"
               "\"pulses_per_litre\":%.9g}",
               app.board_name, runtime.sensor.gpio, current.time_us, dt, delta, total, window_us, hz, rate, volume,
               pulse, work_us, cycles, runtime.revision, runtime.sensor.report_ms,
               runtime.sensor.window_samples, runtime.sensor.pulses_per_litre);
        if (length <= 0 || (size_t)length >= sizeof(reading))
            ESP_ERROR_CHECK(ESP_ERR_INVALID_SIZE);
        ESP_ERROR_CHECK(wifi_publish_reading(reading, (size_t)length));
        if (runtime.stream) puts(reading);
        previous = current;
        if ((int32_t)(xTaskGetTickCount() - next_report) >= 0)
            next_report = xTaskGetTickCount() + pdMS_TO_TICKS(runtime.sensor.report_ms);
    }
}
