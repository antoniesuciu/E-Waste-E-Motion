// Drive logic: throttle/steering mixing, slew limiting, playback following.
#pragma once

void controlManual(float thr, float str);
// Feed-forward from the recorded thr/str plus feedback towards recorded encoder ticks and yaw.
void controlPlayback(float thr, float str, long targetA, long targetB, float targetYaw);
void controlStop();
