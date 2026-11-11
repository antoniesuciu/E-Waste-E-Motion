/* Host test for PCNT wrap handling: cc -std=c99 -Wall -Werror test_encoder_math.c && ./a.out */
#include <assert.h>
#include <stdio.h>
#include "../robot/encoder_math.h"

int main(void)
{
    assert(pcnt_delta(0, 0) == 0);
    assert(pcnt_delta(100, 140) == 40);
    assert(pcnt_delta(140, 100) == -40);
    /* Forward through the reset: 29995 -> (30000 => 0) -> 3 is 8 ticks. */
    assert(pcnt_delta(29995, 3) == 8);
    /* Backward through the reset: -29995 -> (-30000 => 0) -> -3 is -8 ticks. */
    assert(pcnt_delta(-29995, -3) == -8);
    /* Crossing zero normally is not a wrap. */
    assert(pcnt_delta(-5, 5) == 10);

    /* Accumulating many steps across several resets stays exact. */
    long total = 0;
    int raw = 0, prev = 0;
    for (int i = 0; i < 100000; i++) {
        raw = (raw + 7) % PCNT_LIMIT;
        total += pcnt_delta((short)prev, (short)raw);
        prev = raw;
    }
    assert(total == 700000L);

    puts("encoder_math: ok");
    return 0;
}
