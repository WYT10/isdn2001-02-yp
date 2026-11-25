#include "cli.h"
#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

const char *cli_command_name(cli_command_t command)
{
    static const char *const names[] = {
        "help", "status", "get", "set", "stream", "wifi status", "wifi scan",
        "wifi reconnect", "wifi ap on", "wifi ap only", "wifi auto", "reboot",
    };
    return (unsigned)command < sizeof(names) / sizeof(names[0]) ? names[command] : "unknown";
}

const char *cli_parameter_name(cli_parameter_t parameter)
{
    static const char *const names[] = {"all", "report_ms", "window_samples", "pulses_per_litre"};
    return (unsigned)parameter < sizeof(names) / sizeof(names[0]) ? names[parameter] : "unknown";
}

cli_input_result_t cli_input_feed(cli_input_t *input, unsigned char byte)
{
    if (byte == '\r' || byte == '\n') {
        bool overflow = input->discard;
        size_t length = input->length;
        input->line[length] = '\0';
        input->length = 0;
        input->discard = false;
        return overflow ? CLI_INPUT_OVERFLOW : length ? CLI_INPUT_LINE : CLI_INPUT_WAIT;
    }
    if (byte == 3) {
        input->length = 0;
        input->discard = false;
    } else if (input->discard) {
        return CLI_INPUT_WAIT;
    } else if (byte == 8 || byte == 127) {
        if (input->length) --input->length;
    } else if (byte == '\t' || (byte >= 32 && byte <= 126)) {
        if (input->length + 1 < sizeof(input->line)) input->line[input->length++] = byte;
        else input->discard = true;
    } else {
        /* Never execute a truncated prefix of a binary/invalid line. */
        input->discard = true;
    }
    return CLI_INPUT_WAIT;
}

bool cli_parse(const char *line, cli_request_t *out, const char **error)
{
    if (error) *error = "unknown command; send help";
    if (!line || !out) return false;
    size_t length = strlen(line);
    if (!length || length >= CLI_LINE_CAPACITY) return false;
    char copy[CLI_LINE_CAPACITY];
    memcpy(copy, line, length + 1);
    char *args[4] = {0};
    unsigned count = 0;
    for (char *p = copy; *p;) {
        if (*p == ' ' || *p == '\t') { ++p; continue; }
        if (count == 4) return false;
        args[count++] = p;
        while (*p && *p != ' ' && *p != '\t') {
            if ((unsigned char)*p < 32 || (unsigned char)*p > 126) return false;
            ++p;
        }
        if (*p) *p++ = '\0';
    }
    if (!count) return false;
    cli_request_t request = {0};
    if (count == 1) {
        const cli_command_t commands[] = {CLI_HELP, CLI_STATUS, CLI_GET, CLI_REBOOT};
        for (unsigned i = 0; i < sizeof(commands) / sizeof(commands[0]); ++i)
            if (!strcmp(args[0], cli_command_name(commands[i]))) {
                request.command = commands[i];
                *out = request;
                return true;
            }
    }
    if (!strcmp(args[0], "wifi")) {
        if (count == 2) {
            if (!strcmp(args[1], "status")) request.command = CLI_WIFI_STATUS;
            else if (!strcmp(args[1], "scan")) request.command = CLI_WIFI_SCAN;
            else if (!strcmp(args[1], "reconnect")) request.command = CLI_WIFI_RECONNECT;
            else if (!strcmp(args[1], "auto")) request.command = CLI_WIFI_AUTO;
            else return false;
        } else if (count == 3 && !strcmp(args[1], "ap")) {
            if (!strcmp(args[2], "on")) request.command = CLI_WIFI_AP_ON;
            else if (!strcmp(args[2], "only")) request.command = CLI_WIFI_AP_ONLY;
            else return false;
        } else return false;
    } else if (count == 2 && !strcmp(args[0], "stream")) {
        request.command = CLI_STREAM;
        if (!strcmp(args[1], "on")) request.value = 1;
        else if (strcmp(args[1], "off")) return false;
    } else if ((!strcmp(args[0], "get") && count == 2) ||
               (!strcmp(args[0], "set") && count == 3)) {
        for (cli_parameter_t p = CLI_PARAM_REPORT_MS; p <= CLI_PARAM_PULSES_PER_LITRE; ++p)
            if (!strcmp(args[1], cli_parameter_name(p))) request.parameter = p;
        if (request.parameter == CLI_PARAM_ALL) {
            if (error) *error = "unknown parameter";
            return false;
        }
        request.command = count == 2 ? CLI_GET : CLI_SET;
        if (count == 3) {
            char *end;
            errno = 0;
            request.value = strtod(args[2], &end);
            double minimum = request.parameter == CLI_PARAM_REPORT_MS ? 50 :
                             request.parameter == CLI_PARAM_WINDOW_SAMPLES ? 1 : 0;
            double maximum = request.parameter == CLI_PARAM_REPORT_MS ? 10000 :
                             request.parameter == CLI_PARAM_WINDOW_SAMPLES ? 32 : 1e9;
            if (error) *error = "invalid value: report_ms 50..10000, window_samples 1..32, pulses_per_litre 0..1e9";
            if (errno || end == args[2] || *end || !isfinite(request.value) ||
                request.value < minimum || request.value > maximum ||
                (request.parameter != CLI_PARAM_PULSES_PER_LITRE && floor(request.value) != request.value))
                return false;
        }
    } else return false;
    *out = request;
    return true;
}

#include <stdio.h>
#include "sdkconfig.h"
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
#include "driver/usb_serial_jtag.h"
#else
#include "driver/uart.h"
#endif
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static cli_submit_t submit;
static void *submit_context;
static bool started;

static void cli_task(void *context)
{
    (void)context;
    cli_input_t input = {0};
    unsigned char bytes[64];
    printf("{\"type\":\"cli\",\"status\":\"ready\",\"transport\":\"%s\","
           "\"hint\":\"send help followed by Enter\",\"max_line\":%d}\n",
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
           "usb_serial_jtag",
#else
           "uart",
#endif
           CLI_LINE_CAPACITY - 1);
    while (true) {
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
        int count = usb_serial_jtag_read_bytes(bytes, sizeof(bytes), pdMS_TO_TICKS(50));
#else
        int count = uart_read_bytes(CONFIG_ESP_CONSOLE_UART_NUM, bytes, sizeof(bytes), pdMS_TO_TICKS(50));
#endif
        for (int i = 0; i < count; ++i) {
            cli_input_result_t result = cli_input_feed(&input, bytes[i]);
            if (result == CLI_INPUT_OVERFLOW) {
                puts("{\"type\":\"cli\",\"status\":\"error\",\"error\":\"line too long or invalid byte; command discarded\"}");
            } else if (result == CLI_INPUT_LINE) {
                cli_request_t request;
                const char *error;
                if (!cli_parse(input.line, &request, &error))
                    printf("{\"type\":\"cli\",\"status\":\"error\",\"error\":\"%s\"}\n", error);
                else if (!submit(&request, submit_context))
                    puts("{\"type\":\"cli\",\"status\":\"error\",\"error\":\"command queue full; retry\"}");
            }
        }
        if (count > 0) vTaskDelay(1);
    }
}

esp_err_t cli_start(const cli_settings_t *settings, cli_submit_t callback, void *context)
{
    if (!settings || !callback) return ESP_ERR_INVALID_ARG;
    if (!settings->enabled) return ESP_OK;
    if (started) return ESP_ERR_INVALID_STATE;
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
    if (!usb_serial_jtag_is_driver_installed()) {
        usb_serial_jtag_driver_config_t config = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
        config.rx_buffer_size = 512;
        esp_err_t error = usb_serial_jtag_driver_install(&config);
        if (error != ESP_OK) return error;
    }
#else
    const uart_port_t port = CONFIG_ESP_CONSOLE_UART_NUM;
    if (!uart_is_driver_installed(port)) {
        uart_config_t config = {
            .baud_rate = CONFIG_ESP_CONSOLE_UART_BAUDRATE,
            .data_bits = UART_DATA_8_BITS,
            .parity = UART_PARITY_DISABLE,
            .stop_bits = UART_STOP_BITS_1,
            .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
            .source_clk = UART_SCLK_DEFAULT,
        };
        esp_err_t error = uart_param_config(port, &config);
        if (error != ESP_OK) return error;
#if CONFIG_ESP_CONSOLE_UART_CUSTOM
        error = uart_set_pin(port, CONFIG_ESP_CONSOLE_UART_TX_GPIO, CONFIG_ESP_CONSOLE_UART_RX_GPIO,
                             UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
        if (error != ESP_OK) return error;
#endif
        error = uart_driver_install(port, 512, 0, 0, NULL, 0);
        if (error != ESP_OK) return error;
    }
#endif
    /* Read through the driver, keep existing stdout/ESP log transport unchanged. */
    submit = callback;
    submit_context = context;
    if (xTaskCreate(cli_task, "cli", 4096, NULL, 2, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    started = true;
    return ESP_OK;
}
