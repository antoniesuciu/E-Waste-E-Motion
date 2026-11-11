// Differential-drive robot firmware (ESP32): UDP drive commands, recording
// telemetry, and playback that follows recorded encoder ticks and yaw.
#include <WiFi.h>
#include "config.h"
#include "state.h"
#include "motors.h"
#include "encoders.h"
#include "imu.h"
#include "control.h"
#include "net.h"

RobotState g;

void setup()
{
    Serial.begin(115200);
    delay(300);
    Serial.printf("[ESP] Robot %d booting, MAC %s\n", ROBOT_ID, WiFi.macAddress().c_str());

    motorsBegin();
    netBegin();
    if (!imuBegin())
        Serial.println("[ESP][ERROR] MPU6050 not found; yaw will read 0");
    encodersBegin();
    imuZero(300);

    g.lastCmdMs = millis();
}

void loop()
{
    encodersUpdate();
    imuUpdate();
    netReceive();

    if (millis() - g.lastCmdMs > CMD_TIMEOUT_MS)
        controlStop(); // failsafe; the next command slews up from 0

    netSendTelemetry();
}
