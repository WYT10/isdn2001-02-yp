#pragma once
#include <stdbool.h>
#include <stdint.h>

enum { FLOW_SENSOR_WINDOW_CAPACITY = 32 };

typedef struct {
    int gpio;
    bool pull_up;
    bool capture_timing;
    uint32_t glitch_filter_ns;
    int64_t stale_after_us;
    uint32_t report_ms;
    unsigned window_samples;
    double pulses_per_litre;
} flow_sensor_config_t;

typedef struct {
    uint32_t count;
    int64_t time_us;
    uint32_t period_ticks;
    uint32_t high_ticks;
    uint32_t capture_hz;
    bool timing_valid;
} flow_sensor_snapshot_t;

/* One hardware sensor; start copies the configuration. */
void flow_sensor_start(const flow_sensor_config_t *config);
void flow_sensor_snapshot(flow_sensor_snapshot_t *out);

typedef struct {
    uint32_t rise;
    uint32_t pending_high;
    uint32_t period;
    uint32_t high;
    bool have_rise;
    bool have_fall;
} flow_timing_t;

uint32_t flow_count_delta(uint32_t previous, uint32_t current);
double flow_frequency(uint64_t pulses, uint64_t elapsed_us);
double flow_lpm(double hz, double pulses_per_litre);
double flow_litres(uint64_t pulses, double pulses_per_litre);
bool flow_timing_edge(flow_timing_t *state, bool rising, uint32_t ticks);
