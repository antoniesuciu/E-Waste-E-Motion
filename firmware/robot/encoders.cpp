#include <Arduino.h>
#include "driver/pcnt.h" // legacy PCNT driver; deprecated (still present) in ESP-IDF 5 / Arduino core 3
#include "config.h"
#include "encoders.h"
#include "encoder_math.h"

static constexpr pcnt_unit_t UNIT_L = PCNT_UNIT_0;
static constexpr pcnt_unit_t UNIT_R = PCNT_UNIT_1;

static long ticksL = 0, ticksR = 0;
static int16_t lastL = 0, lastR = 0;

// A is the pulse input, B the direction level: counts both A edges (x2 decoding).
static void configureUnit(pcnt_unit_t unit, uint8_t pinA, uint8_t pinB)
{
    pcnt_config_t cfg = {};
    cfg.pulse_gpio_num = pinA;
    cfg.ctrl_gpio_num = pinB;
    cfg.unit = unit;
    cfg.channel = PCNT_CHANNEL_0;
    cfg.pos_mode = PCNT_COUNT_INC;      // rising A: +1
    cfg.neg_mode = PCNT_COUNT_DEC;      // falling A: -1
    cfg.lctrl_mode = PCNT_MODE_REVERSE; // B low: reverse
    cfg.hctrl_mode = PCNT_MODE_KEEP;    // B high: keep
    cfg.counter_h_lim = PCNT_LIMIT;
    cfg.counter_l_lim = -PCNT_LIMIT;
    pcnt_unit_config(&cfg);

    pcnt_set_filter_value(unit, PCNT_GLITCH_CYCLES);
    pcnt_filter_enable(unit);
    pcnt_counter_pause(unit);
    pcnt_counter_clear(unit);
    pcnt_counter_resume(unit);
}

void encodersBegin()
{
    pinMode(PIN_ENC_L_A, INPUT);
    pinMode(PIN_ENC_L_B, INPUT);
    pinMode(PIN_ENC_R_A, INPUT);
    pinMode(PIN_ENC_R_B, INPUT);
    configureUnit(UNIT_L, PIN_ENC_L_A, PIN_ENC_L_B);
    configureUnit(UNIT_R, PIN_ENC_R_A, PIN_ENC_R_B);
    encodersZero();
}

void encodersUpdate()
{
    int16_t curL = 0, curR = 0;
    pcnt_get_counter_value(UNIT_L, &curL);
    pcnt_get_counter_value(UNIT_R, &curR);
    ticksL += pcnt_delta(lastL, curL);
    ticksR += pcnt_delta(lastR, curR);
    lastL = curL;
    lastR = curR;
}

void encodersZero()
{
    for (pcnt_unit_t u : {UNIT_L, UNIT_R}) {
        pcnt_counter_pause(u);
        pcnt_counter_clear(u);
        pcnt_counter_resume(u);
    }
    lastL = lastR = 0;
    ticksL = ticksR = 0;
}

long encoderA() { return ticksL; }
long encoderB() { return ticksR; }
