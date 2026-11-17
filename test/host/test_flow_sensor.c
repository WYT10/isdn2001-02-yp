#include "flow_sensor.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void close_to(double actual, double expected)
{
    assert(isfinite(actual));
    assert(fabs(actual - expected) <= 1e-9 * fmax(1.0, fabs(expected)));
}

int main(void)
{
    close_to(flow_frequency(0, 1000000), 0);
    close_to(flow_frequency(75, 1000000), 75);
    close_to(flow_frequency(15, 200000), 75);
    close_to(flow_frequency(1, 2000000), 0.5);
    assert(isnan(flow_frequency(1, 0)));
    /* Both possible calibration factors are test inputs, not sensor claims. */
    close_to(flow_lpm(75, 450), 10);
    close_to(flow_lpm(75, 300), 15);
    close_to(flow_litres(900, 450), 2);
    close_to(flow_litres(900, 300), 3);
    close_to(flow_litres(UINT64_C(450000000000), 450), 1000000000);
    assert(isnan(flow_lpm(1, 0)));
    assert(isnan(flow_lpm(1, -1)));
    assert(isnan(flow_lpm(-1, 300)));
    assert(isnan(flow_lpm(NAN, 300)));
    assert(isnan(flow_lpm(INFINITY, 300)));
    assert(isnan(flow_lpm(10, INFINITY)));
    assert(isnan(flow_litres(1, NAN)));
    assert(isnan(flow_litres(1, 0)));
    assert(flow_count_delta(UINT32_MAX - 15, 16) == 32);
    assert(flow_count_delta(123, 123) == 0);
    assert(flow_count_delta(29999, 30001) == 2);

    flow_timing_t timing = {0};
    assert(!flow_timing_edge(&timing, false, 10));
    assert(!flow_timing_edge(&timing, true, 100));
    assert(!flow_timing_edge(&timing, false, 140));
    assert(flow_timing_edge(&timing, true, 200));
    assert(timing.high == 40 && timing.period == 100);
    assert(!flow_timing_edge(&timing, true, 300)); /* Missing falling edge. */
    assert(!flow_timing_edge(&timing, false, 330));
    assert(!flow_timing_edge(&timing, false, 340)); /* Duplicate falling edge. */
    assert(!flow_timing_edge(&timing, true, 400));
    assert(!flow_timing_edge(&timing, false, 400)); /* Zero high time. */
    assert(!flow_timing_edge(&timing, true, 500));

    memset(&timing, 0, sizeof(timing));
    uint32_t start = UINT32_MAX - 30;
    flow_timing_edge(&timing, true, start);
    flow_timing_edge(&timing, false, start + 40);
    assert(flow_timing_edge(&timing, true, start + 100));
    assert(timing.high == 40 && timing.period == 100);

    /* Independent synthetic waveforms, varied duty and multiple tick wraps. */
    for (uint32_t period = 2; period < 10000; period += 13) {
        for (uint32_t high = 1; high < period; high += period / 7 + 1) {
            memset(&timing, 0, sizeof(timing));
            uint32_t tick = UINT32_MAX - period / 2;
            flow_timing_edge(&timing, true, tick);
            for (int cycle = 0; cycle < 10; ++cycle) {
                assert(!flow_timing_edge(&timing, false, tick + high));
                tick += period;
                assert(flow_timing_edge(&timing, true, tick));
                assert(timing.high == high && timing.period == period);
            }
        }
    }
    puts("PASS: flow conversion, invalid calibration, count wrap, timing and synthetic waveforms");
    return 0;
}
