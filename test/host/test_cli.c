#include "cli.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static cli_request_t parse(const char *line, cli_command_t command)
{
    cli_request_t result;
    const char *error = NULL;
    assert(cli_parse(line, &result, &error));
    assert(result.command == command);
    return result;
}

int main(void)
{
    const struct { const char *line; cli_command_t command; } commands[] = {
        {"help", CLI_HELP}, {"status", CLI_STATUS}, {"get", CLI_GET},
        {"wifi status", CLI_WIFI_STATUS}, {"wifi scan", CLI_WIFI_SCAN},
        {"wifi reconnect", CLI_WIFI_RECONNECT}, {"wifi ap on", CLI_WIFI_AP_ON},
        {"wifi ap only", CLI_WIFI_AP_ONLY}, {"wifi auto", CLI_WIFI_AUTO},
        {"benchmark", CLI_BENCHMARK}, {"reboot", CLI_REBOOT},
    };
    for (unsigned i = 0; i < sizeof(commands) / sizeof(commands[0]); ++i) {
        parse(commands[i].line, commands[i].command);
        assert(!strcmp(cli_command_name(commands[i].command), commands[i].line));
    }
    assert(parse(" get report_ms \t", CLI_GET).parameter == CLI_PARAM_REPORT_MS);
    assert(parse("set report_ms 50", CLI_SET).value == 50);
    assert(parse("set report_ms 10000", CLI_SET).value == 10000);
    assert(parse("set window_samples 1", CLI_SET).value == 1);
    assert(parse("set window_samples 32", CLI_SET).value == 32);
    assert(parse("set pulses_per_litre 450.25", CLI_SET).value == 450.25);
    assert(parse("set pulses_per_litre 0", CLI_SET).value == 0);
    assert(parse("set pulses_per_litre 1e9", CLI_SET).value == 1e9);
    assert(parse("stream on", CLI_STREAM).value == 1);
    assert(parse("stream off", CLI_STREAM).value == 0);
    const char *invalid[] = {"", "  ", "help extra", "set gpio 4", "set report_ms 49",
        "set report_ms 10001", "set report_ms 100.5", "set window_samples 0",
        "set window_samples 33", "set window_samples 1.5", "set pulses_per_litre -1",
        "set pulses_per_litre 1000000001", "set pulses_per_litre nan",
        "set pulses_per_litre inf", "set pulses_per_litre 1e999", "set report_ms 250x",
        "set report_ms 250 extra", "set", "get made_up", "wifi ap off", "wifi ap",
        "wifi only", "stream 1", "stream on extra", "status\x01", "reboot now"};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        cli_request_t out = {.command = CLI_REBOOT, .value = 123};
        const char *error;
        assert(!cli_parse(invalid[i], &out, &error));
        assert(error && out.command == CLI_REBOOT && out.value == 123);
    }
    cli_input_t input = {0};
    const char *line = "status\r\n";
    unsigned completed = 0;
    for (size_t i = 0; line[i]; ++i) {
        if (cli_input_feed(&input, line[i]) == CLI_INPUT_LINE) {
            ++completed;
            assert(!strcmp(input.line, "status"));
        }
    }
    assert(completed == 1);
    for (unsigned i = 0; i < 1000; ++i) assert(cli_input_feed(&input, 'x') == CLI_INPUT_WAIT);
    cli_input_feed(&input, 8); /* Overflow remains discarded even after backspace. */
    assert(cli_input_feed(&input, '\n') == CLI_INPUT_OVERFLOW);
    for (const char *p = "helx\bp"; *p; ++p) cli_input_feed(&input, *p);
    assert(cli_input_feed(&input, '\n') == CLI_INPUT_LINE);
    assert(!strcmp(input.line, "help"));
    cli_input_feed(&input, 'x');
    cli_input_feed(&input, 3);
    assert(cli_input_feed(&input, '\n') == CLI_INPUT_WAIT);
    cli_input_feed(&input, 0);
    assert(cli_input_feed(&input, '\n') == CLI_INPUT_OVERFLOW);
    char maximum[CLI_LINE_CAPACITY];
    memset(maximum, ' ', sizeof(maximum));
    memcpy(maximum, "help", 4);
    maximum[sizeof(maximum)-1] = '\0';
    for (size_t i = 0; maximum[i]; ++i) assert(cli_input_feed(&input, maximum[i]) == CLI_INPUT_WAIT);
    assert(cli_input_feed(&input, '\n') == CLI_INPUT_LINE);
    parse(input.line, CLI_HELP);
    puts("PASS: CLI commands, numeric bounds, nonfinite values, CR/LF, editing and overflow recovery");
    return 0;
}
