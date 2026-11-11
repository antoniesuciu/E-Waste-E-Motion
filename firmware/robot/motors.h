// L298-style H-bridge for two drive motors.
#pragma once

void motorsBegin();
void motorsStop();
// Signed PWM per side, capped to PWM_CAP; nonzero values below minMag are raised to minMag.
void motorsDrive(int pwmL, int pwmR, int minMag);
