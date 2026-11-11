// Quadrature encoders on the ESP32 hardware pulse counter (PCNT).
#pragma once

void encodersBegin();
void encodersUpdate(); // call every loop: folds 16-bit PCNT counts into 32-bit totals
void encodersZero();
long encoderA(); // left total ticks
long encoderB(); // right total ticks
