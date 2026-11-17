#pragma once
#include <stdbool.h>
#include <stddef.h>

enum { CLI_LINE_CAPACITY = 96 };

typedef enum {
    CLI_HELP, CLI_STATUS, CLI_GET, CLI_SET, CLI_STREAM,
    CLI_WIFI_STATUS, CLI_WIFI_SCAN, CLI_WIFI_RECONNECT,
    CLI_WIFI_AP_ON, CLI_WIFI_AP_ONLY, CLI_WIFI_AUTO,
    CLI_BENCHMARK, CLI_REBOOT,
} cli_command_t;

typedef enum {
    CLI_PARAM_ALL, CLI_PARAM_REPORT_MS, CLI_PARAM_WINDOW_SAMPLES,
    CLI_PARAM_PULSES_PER_LITRE,
} cli_parameter_t;

typedef struct {
    cli_command_t command;
    cli_parameter_t parameter;
    double value;
} cli_request_t;

typedef struct {
    char line[CLI_LINE_CAPACITY];
    size_t length;
    bool discard;
} cli_input_t;

typedef enum { CLI_INPUT_WAIT, CLI_INPUT_LINE, CLI_INPUT_OVERFLOW } cli_input_result_t;

/* Portable parser and bounded byte framer, also compiled by the native tests. */
bool cli_parse(const char *line, cli_request_t *out, const char **error);
cli_input_result_t cli_input_feed(cli_input_t *input, unsigned char byte);
const char *cli_command_name(cli_command_t command);
const char *cli_parameter_name(cli_parameter_t parameter);

#ifndef CLI_HOST_TEST
#include "esp_err.h"
typedef struct { bool enabled; bool stream; } cli_settings_t;
typedef bool (*cli_submit_t)(const cli_request_t *request, void *context);
esp_err_t cli_start(const cli_settings_t *settings, cli_submit_t submit, void *context);
#endif
