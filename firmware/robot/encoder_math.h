/* Pure encoder arithmetic, kept free of Arduino headers so it can be tested on the host. */
#ifndef ENCODER_MATH_H
#define ENCODER_MATH_H
#include <stdint.h>

/* PCNT resets to 0 when the count reaches +/-PCNT_LIMIT, so the counter is
 * modulo PCNT_LIMIT, not a free-running int16. */
#define PCNT_LIMIT 30000

/* Ticks moved between two raw PCNT samples. Valid while |true delta| < PCNT_LIMIT/2. */
static inline int32_t pcnt_delta(int16_t prev, int16_t cur)
{
    int32_t d = (int32_t)cur - (int32_t)prev;
    if (d > PCNT_LIMIT / 2)
        d -= PCNT_LIMIT;
    else if (d < -PCNT_LIMIT / 2)
        d += PCNT_LIMIT;
    return d;
}

#endif
