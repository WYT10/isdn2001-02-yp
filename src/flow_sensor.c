#include "flow_sensor.h"
#include <math.h>

uint32_t flow_count_delta(uint32_t previous, uint32_t current)
{
    return current - previous;
}

double flow_frequency(uint64_t pulses, uint64_t elapsed_us)
{
    return elapsed_us ? (double)pulses * 1000000.0 / (double)elapsed_us : NAN;
}

double flow_lpm(double hz, double pulses_per_litre)
{
    return isfinite(hz) && hz >= 0 && isfinite(pulses_per_litre) && pulses_per_litre > 0
        ? hz * 60.0 / pulses_per_litre : NAN;
}

double flow_litres(uint64_t pulses, double pulses_per_litre)
{
    return isfinite(pulses_per_litre) && pulses_per_litre > 0
        ? (double)pulses / pulses_per_litre : NAN;
}

bool flow_timing_edge(flow_timing_t *s, bool rising, uint32_t ticks)
{
    if (!rising) {
        if (s->have_rise && !s->have_fall) {
            s->pending_high = ticks - s->rise;
            s->have_fall = true;
        } else {
            s->have_rise = false;
            s->have_fall = false;
        }
        return false;
    }
    uint32_t period = ticks - s->rise;
    bool valid = s->have_rise && s->have_fall && s->pending_high > 0
        && s->pending_high < period;
    if (valid) {
        s->period = period;
        s->high = s->pending_high;
    }
    s->rise = ticks;
    s->have_rise = true;
    s->have_fall = false;
    return valid;
}

#ifndef FLOW_SENSOR_HOST_TEST
#include "driver/gpio.h"
#include "driver/mcpwm_cap.h"
#include "driver/pulse_cnt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"
#include <string.h>
#include "driver/ledc.h"
#include "dsps_mulc.h"
#include "esp_cpu.h"
#include "freertos/task.h"
#include <inttypes.h>
#include <stdio.h>

static pcnt_unit_handle_t counter;
static pcnt_channel_handle_t counter_channel;
static mcpwm_cap_timer_handle_t capture_timer;
static mcpwm_cap_channel_handle_t capture_channel;
static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
static flow_timing_t timing;
static uint32_t capture_hz;
static int64_t last_edge_us;
static int64_t last_cycle_us;
static flow_sensor_config_t settings;

static bool on_capture(mcpwm_cap_channel_handle_t channel,
                       const mcpwm_capture_event_data_t *event, void *context)
{
    (void)channel;
    (void)context;
    int64_t now = esp_timer_get_time();
    portENTER_CRITICAL_ISR(&lock);
    if (now - last_edge_us > settings.stale_after_us) {
        timing.have_rise = false;
        timing.have_fall = false;
        last_cycle_us = 0;
    }
    last_edge_us = now;
    if (flow_timing_edge(&timing, event->cap_edge == MCPWM_CAP_EDGE_POS,
                         event->cap_value)) {
        last_cycle_us = now;
    }
    portEXIT_CRITICAL_ISR(&lock);
    return false;
}

void flow_sensor_start(const flow_sensor_config_t *config)
{
    if (!config || !GPIO_IS_VALID_GPIO(config->gpio)
        || !config->glitch_filter_ns || config->stale_after_us <= 0
        || !pdMS_TO_TICKS(config->report_ms) || !config->window_samples
        || config->window_samples > FLOW_SENSOR_WINDOW_CAPACITY
        || !isfinite(config->pulses_per_litre) || config->pulses_per_litre < 0) {
        ESP_ERROR_CHECK(ESP_ERR_INVALID_ARG);
        return;
    }
    if (counter) {
        ESP_ERROR_CHECK(ESP_ERR_INVALID_STATE);
        return;
    }
    settings = *config;
    memset(&timing, 0, sizeof(timing));
    last_cycle_us = last_edge_us = 0;
    capture_hz = 0;
    gpio_config_t pin = {
        .pin_bit_mask = 1ULL << settings.gpio,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = settings.pull_up ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&pin));
    pcnt_unit_config_t unit_config = {
        .low_limit = -30000, .high_limit = 30000,
        .flags.accum_count = true,
    };
    ESP_ERROR_CHECK(pcnt_new_unit(&unit_config, &counter));
    pcnt_chan_config_t channel = {.edge_gpio_num = settings.gpio, .level_gpio_num = -1};
    ESP_ERROR_CHECK(pcnt_new_channel(counter, &channel, &counter_channel));
    ESP_ERROR_CHECK(pcnt_channel_set_edge_action(counter_channel,
        PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD));
    ESP_ERROR_CHECK(pcnt_channel_set_level_action(counter_channel,
        PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_KEEP));
    pcnt_glitch_filter_config_t filter = {.max_glitch_ns = settings.glitch_filter_ns};
    ESP_ERROR_CHECK(pcnt_unit_set_glitch_filter(counter, &filter));
    ESP_ERROR_CHECK(pcnt_unit_add_watch_point(counter, 30000));
    ESP_ERROR_CHECK(pcnt_unit_add_watch_point(counter, -30000));
    ESP_ERROR_CHECK(pcnt_unit_enable(counter));
    ESP_ERROR_CHECK(pcnt_unit_clear_count(counter));
    if (settings.capture_timing) {
        mcpwm_capture_timer_config_t timer_config = {
            .group_id = 0, .clk_src = MCPWM_CAPTURE_CLK_SRC_DEFAULT,
        };
        ESP_ERROR_CHECK(mcpwm_new_capture_timer(&timer_config, &capture_timer));
        ESP_ERROR_CHECK(mcpwm_capture_timer_get_resolution(capture_timer, &capture_hz));
        mcpwm_capture_channel_config_t capture_config = {
            .gpio_num = settings.gpio, .prescale = 1,
            .flags.pos_edge = true, .flags.neg_edge = true,
        };
        ESP_ERROR_CHECK(mcpwm_new_capture_channel(capture_timer, &capture_config,
                                                 &capture_channel));
        mcpwm_capture_event_callbacks_t callbacks = {.on_cap = on_capture};
        ESP_ERROR_CHECK(mcpwm_capture_channel_register_event_callbacks(
            capture_channel, &callbacks, NULL));
        ESP_ERROR_CHECK(mcpwm_capture_timer_enable(capture_timer));
        ESP_ERROR_CHECK(mcpwm_capture_channel_enable(capture_channel));
        ESP_ERROR_CHECK(mcpwm_capture_timer_start(capture_timer));
    }
    ESP_ERROR_CHECK(pcnt_unit_start(counter));
}

void flow_sensor_snapshot(flow_sensor_snapshot_t *out)
{
    if (!out || !counter) {
        ESP_ERROR_CHECK(ESP_ERR_INVALID_STATE);
        return;
    }
    int count;
    int64_t before = esp_timer_get_time();
    ESP_ERROR_CHECK(pcnt_unit_get_count(counter, &count));
    int64_t after = esp_timer_get_time();
    out->count = (uint32_t)count;
    out->time_us = before + (after - before) / 2;
    portENTER_CRITICAL(&lock);
    out->period_ticks = timing.period;
    out->high_ticks = timing.high;
    out->capture_hz = capture_hz;
    out->timing_valid = last_cycle_us > 0 && after >= last_cycle_us
        && after - last_cycle_us < settings.stale_after_us && timing.period > 0;
    portEXIT_CRITICAL(&lock);
}

void flow_sensor_stop(void)
{
    ESP_ERROR_CHECK(pcnt_unit_stop(counter));
    if (capture_channel) {
        ESP_ERROR_CHECK(mcpwm_capture_channel_disable(capture_channel));
        ESP_ERROR_CHECK(mcpwm_capture_timer_stop(capture_timer));
        ESP_ERROR_CHECK(mcpwm_capture_timer_disable(capture_timer));
        ESP_ERROR_CHECK(mcpwm_del_capture_channel(capture_channel));
        ESP_ERROR_CHECK(mcpwm_del_capture_timer(capture_timer));
        capture_channel = NULL;
        capture_timer = NULL;
    }
    ESP_ERROR_CHECK(pcnt_unit_disable(counter));
    ESP_ERROR_CHECK(pcnt_del_channel(counter_channel));
    ESP_ERROR_CHECK(pcnt_del_unit(counter));
    counter_channel = NULL;
    counter = NULL;
}

static float input[256] __attribute__((aligned(16)));
static float ansi_output[256] __attribute__((aligned(16)));
static float dsp_output[256] __attribute__((aligned(16)));
static volatile float benchmark_sink;

void flow_sensor_benchmark(void)
{
    for (int i = 0; i < 256; ++i) input[i] = i * 0.25f;
    const int lengths[] = {1, 16, 256};
    for (unsigned j = 0; j < sizeof(lengths) / sizeof(lengths[0]); ++j) {
        int n = lengths[j];
        const float scale = 0.2f; /* Arbitrary test coefficient, not calibration. */
        ESP_ERROR_CHECK(dsps_mulc_f32_ansi(input, ansi_output, n, scale, 1, 1));
        ESP_ERROR_CHECK(dsps_mulc_f32(input, dsp_output, n, scale, 1, 1));
        float max_error = 0;
        bool correct = true;
        for (int i = 0; i < n; ++i) {
            float expected = input[i] * scale;
            float error = fmaxf(fabsf(expected - dsp_output[i]),
                                fabsf(expected - ansi_output[i]));
            correct = correct && isfinite(ansi_output[i]) && isfinite(dsp_output[i]);
            if (error > max_error) max_error = error;
        }
        uint32_t ansi_best = UINT32_MAX, dsp_best = UINT32_MAX;
        for (int trial = 0; trial < 7; ++trial) {
            uint32_t start = esp_cpu_get_cycle_count();
            for (int k = 0; k < 1000; ++k)
                dsps_mulc_f32_ansi(input, ansi_output, n, scale, 1, 1);
            uint32_t elapsed = esp_cpu_get_cycle_count() - start;
            if (elapsed < ansi_best) ansi_best = elapsed;
            start = esp_cpu_get_cycle_count();
            for (int k = 0; k < 1000; ++k)
                dsps_mulc_f32(input, dsp_output, n, scale, 1, 1);
            elapsed = esp_cpu_get_cycle_count() - start;
            if (elapsed < dsp_best) dsp_best = elapsed;
            benchmark_sink = ansi_output[n - 1] + dsp_output[n - 1];
            vTaskDelay(1);
        }
        printf("{\"type\":\"benchmark\",\"library\":\"esp-dsp-1.8.2\","
               "\"operation\":\"mulc_f32\",\"n\":%d,\"cpu_mhz_config\":%d,"
               "\"core\":%d,\"ansi_cycles_per_call\":%.3f,"
               "\"dsp_cycles_per_call\":%.3f,\"max_abs_error\":%.9g,"
               "\"pass\":%s}\n", n, CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ,
               xPortGetCoreID(), ansi_best / 1000.0, dsp_best / 1000.0,
               (double)max_error, correct && max_error <= 1e-6f ? "true" : "false");
    }
}

void flow_sensor_selftest(const flow_sensor_config_t *defaults, int test_gpio)
{
    if (!defaults || test_gpio == defaults->gpio) {
        ESP_ERROR_CHECK(ESP_ERR_INVALID_ARG);
        return;
    }
    const struct { uint32_t hz; uint32_t duty; uint32_t ms; bool timing; } cases[] = {
        {5, 102, 1500, true}, {75, 256, 1000, true},
        {150, 410, 1000, true}, {1000, 256, 1000, true},
        {20000, 256, 2000, false}, /* Crosses the 30000-count hardware limit. */
    };
    bool all_pass = true;
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        flow_sensor_config_t sensor = *defaults;
        sensor.gpio = test_gpio;
        sensor.capture_timing = cases[i].timing;
        flow_sensor_start(&sensor);
        ledc_timer_bit_t bits = cases[i].hz <= 1000 ? LEDC_TIMER_14_BIT : LEDC_TIMER_9_BIT;
        ledc_timer_config_t timer = {
            .speed_mode = LEDC_LOW_SPEED_MODE, .timer_num = LEDC_TIMER_0,
            .duty_resolution = bits, .freq_hz = cases[i].hz,
            .clk_cfg = LEDC_AUTO_CLK,
        };
        ESP_ERROR_CHECK(ledc_timer_config(&timer));
        ledc_channel_config_t channel = {
            .gpio_num = test_gpio, .speed_mode = LEDC_LOW_SPEED_MODE,
            .channel = LEDC_CHANNEL_0, .timer_sel = LEDC_TIMER_0,
            .duty = cases[i].duty << (bits - LEDC_TIMER_9_BIT),
        };
        ESP_ERROR_CHECK(ledc_channel_config(&channel));
        ESP_ERROR_CHECK(gpio_input_enable(test_gpio));
        vTaskDelay(pdMS_TO_TICKS(500));
        flow_sensor_snapshot_t begin, end;
        flow_sensor_snapshot(&begin);
        vTaskDelay(pdMS_TO_TICKS(cases[i].ms));
        flow_sensor_snapshot(&end);
        uint32_t pulses = flow_count_delta(begin.count, end.count);
        uint64_t dt = end.time_us - begin.time_us;
        uint32_t actual_hz = ledc_get_freq(LEDC_LOW_SPEED_MODE, LEDC_TIMER_0);
        double expected = actual_hz * (double)dt / 1e6;
        bool pass = fabs(pulses - expected) <= 2.0 + expected * 0.002;
        double duty = -1;
        double period_hz = -1;
        if (cases[i].timing) {
            duty = 100.0 * end.high_ticks / (end.period_ticks ? end.period_ticks : 1);
            period_hz = end.period_ticks ? (double)end.capture_hz / end.period_ticks : 0;
            pass = pass && end.timing_valid && fabs(period_hz - actual_hz) < actual_hz * 0.02
                && fabs(duty - 100.0 * cases[i].duty / 512.0) < 2.0;
        }
        ESP_ERROR_CHECK(ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0));
        vTaskDelay(pdMS_TO_TICKS(50));
        flow_sensor_snapshot(&begin);
        vTaskDelay(pdMS_TO_TICKS(sensor.stale_after_us / 1000 + 100));
        flow_sensor_snapshot(&end);
        bool stopped = end.count == begin.count && !end.timing_valid;
        pass = pass && stopped;
        all_pass = all_pass && pass;
        printf("{\"type\":\"selftest\",\"gpio\":%d,\"hz\":%" PRIu32 ","
               "\"pulses\":%" PRIu32 ",\"expected_pulses\":%.3f,"
               "\"period_hz\":%.3f,\"duty_pct\":%.3f,\"stopped\":%s,\"pass\":%s}\n",
               test_gpio, actual_hz, pulses, expected, period_hz, duty,
               stopped ? "true" : "false", pass ? "true" : "false");
        flow_sensor_stop();
        ESP_ERROR_CHECK(gpio_reset_pin(test_gpio));
    }
    printf("{\"type\":\"selftest_summary\",\"pass\":%s}\n", all_pass ? "true" : "false");
}
#endif
