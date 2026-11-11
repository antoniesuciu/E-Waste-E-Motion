#include <Arduino.h>
#include "config.h"
#include "motors.h"

// Arduino-ESP32 core 3.x replaced channel-based LEDC with pin-based calls.
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
#define LEDC_PIN_API 1
#else
#define LEDC_PIN_API 0
#endif

static void pwmWrite(uint8_t pin, uint8_t channel, uint32_t duty)
{
#if LEDC_PIN_API
    (void)channel;
    ledcWrite(pin, duty);
#else
    (void)pin;
    ledcWrite(channel, duty);
#endif
}

static int withMinMag(int pwm, int minMag)
{
    pwm = constrain(pwm, -PWM_CAP, PWM_CAP);
    if (pwm == 0 || abs(pwm) >= minMag)
        return pwm;
    return pwm > 0 ? minMag : -minMag;
}

static void driveSide(int pwm, uint8_t inA, uint8_t inB, uint8_t en, uint8_t ch)
{
    digitalWrite(inA, pwm >= 0 ? HIGH : LOW);
    digitalWrite(inB, pwm >= 0 ? LOW : HIGH);
    pwmWrite(en, ch, abs(pwm));
}

void motorsBegin()
{
    for (uint8_t pin : {PIN_IN1, PIN_IN2, PIN_IN3, PIN_IN4})
        pinMode(pin, OUTPUT);
#if LEDC_PIN_API
    ledcAttach(PIN_ENA, PWM_FREQ, PWM_RES_BITS);
    ledcAttach(PIN_ENB, PWM_FREQ, PWM_RES_BITS);
#else
    ledcSetup(PWM_CH_L, PWM_FREQ, PWM_RES_BITS);
    ledcAttachPin(PIN_ENA, PWM_CH_L);
    ledcSetup(PWM_CH_R, PWM_FREQ, PWM_RES_BITS);
    ledcAttachPin(PIN_ENB, PWM_CH_R);
#endif
    motorsStop();
}

void motorsStop()
{
    pwmWrite(PIN_ENA, PWM_CH_L, 0);
    pwmWrite(PIN_ENB, PWM_CH_R, 0);
    for (uint8_t pin : {PIN_IN1, PIN_IN2, PIN_IN3, PIN_IN4})
        digitalWrite(pin, LOW);
}

void motorsDrive(int pwmL, int pwmR, int minMag)
{
    driveSide(withMinMag(pwmL, minMag), PIN_IN1, PIN_IN2, PIN_ENA, PWM_CH_L);
    driveSide(withMinMag(pwmR, minMag), PIN_IN3, PIN_IN4, PIN_ENB, PWM_CH_R);
}
