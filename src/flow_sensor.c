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

#include "driver/gpio.h"
#include "driver/mcpwm_cap.h"
#include "driver/pulse_cnt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"
#include <string.h>

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
