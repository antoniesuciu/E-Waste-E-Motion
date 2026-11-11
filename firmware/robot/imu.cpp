#include <Arduino.h>
#include <Wire.h>
#include <MPU6050_light.h>
#include "imu.h"

static MPU6050 mpu(Wire);
static bool ok = false;
static float yawOffset = 0.0f;

bool imuBegin()
{
    Wire.begin();
    ok = mpu.begin() == 0;
    if (ok)
        mpu.calcGyroOffsets(); // robot must be still during boot
    return ok;
}

void imuUpdate()
{
    if (ok)
        mpu.update();
}

void imuZero(uint16_t settleMs)
{
    uint32_t t0 = millis();
    while (millis() - t0 < settleMs) {
        imuUpdate();
        delay(2);
    }
    imuUpdate();
    yawOffset = ok ? mpu.getAngleZ() : 0.0f;
}

float imuYaw() { return ok ? mpu.getAngleZ() - yawOffset : 0.0f; }
