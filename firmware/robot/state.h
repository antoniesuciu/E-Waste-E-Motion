// Shared runtime state, owned by robot.ino.
#pragma once
#include <stdint.h>

enum class Mode { Idle, Play, Record };

struct RobotState {
    Mode mode = Mode::Idle;
    float thr = 0.0f; // last commanded throttle [-1, 1]
    float str = 0.0f; // last commanded steering [-1, 1]
    float s1 = 0.0f;  // servo value echoed in telemetry so recordings keep their shape
    int pwmL = 0;     // last slewed PWM, signed
    int pwmR = 0;
    bool spin = false;
    bool telemetryOn = true;
    uint32_t lastCmdMs = 0;
};

extern RobotState g;
