// MPU6050 yaw. getAngleZ integrates the gyro between updates, so call imuUpdate every loop.
#pragma once
#include <stdint.h>

bool imuBegin();              // false if the MPU6050 does not answer
void imuUpdate();
void imuZero(uint16_t settleMs); // settle, then make the current heading 0
float imuYaw();               // degrees, cumulative (not wrapped)
