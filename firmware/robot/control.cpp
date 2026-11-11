#include <Arduino.h>
#include <math.h>
#include "config.h"
#include "state.h"
#include "motors.h"
#include "encoders.h"
#include "imu.h"
#include "control.h"

struct Profile {
    float kTurn;
    int minMag;
    int slew;
    bool spin;
};

// Spin only when actually steering: at rest the large spin kick would turn
// small playback corrections into 150-PWM jolts.
static Profile profileFor(float thr, float str)
{
    if (fabsf(thr) < SPIN_THR_THRESH && str != 0.0f)
        return {K_TURN_SPIN, MIN_PWM_MAG_SPIN, MAX_DPWM_SPIN, true};
    return {K_TURN, MIN_PWM_MAG, MAX_DPWM, false};
}

static float sanitize(float v, float deadband)
{
    v = constrain(v, -1.0f, 1.0f);
    return fabsf(v) < deadband ? 0.0f : v;
}

static int slewToward(int current, int target, int step)
{
    target = constrain(target, -PWM_CAP, PWM_CAP);
    return constrain(target, current - step, current + step);
}

static void mix(float thr, float str, const Profile &p, int &left, int &right)
{
    left = (int)lroundf((K_THR * thr + p.kTurn * str) * PWM_CAP);
    right = (int)lroundf((K_THR * thr - p.kTurn * str) * PWM_CAP);
}

static void apply(int targetL, int targetR, const Profile &p)
{
    g.pwmL = slewToward(g.pwmL, targetL, p.slew);
    g.pwmR = slewToward(g.pwmR, targetR, p.slew);
    g.spin = p.spin;
    motorsDrive(g.pwmL, g.pwmR, p.minMag);
}

static int tickFeedback(long target, long now, int sign)
{
    long err = target - now;
    if (labs(err) <= TICK_DEADBAND)
        return 0;
    return sign * (int)lroundf(KP_TICK * err);
}

void controlManual(float thr, float str)
{
    thr = sanitize(thr, DEAD_BAND_THR);
    str = sanitize(str, DEAD_BAND_STR);
    Profile p = profileFor(thr, str);
    int l, r;
    mix(thr, str, p, l, r);
    apply(l, r, p);
}

void controlPlayback(float thr, float str, long targetA, long targetB, float targetYaw)
{
    thr = sanitize(thr, DEAD_BAND_THR);
    str = sanitize(str, DEAD_BAND_STR);
    Profile p = profileFor(thr, str);
    int l, r;
    mix(thr, str, p, l, r);

    l += tickFeedback(targetA, encoderA(), TICK_TO_PWM_SIGN_A);
    r += tickFeedback(targetB, encoderB(), TICK_TO_PWM_SIGN_B);

    float yawErr = remainderf(targetYaw - imuYaw(), 360.0f); // shortest way round, [-180, 180]
    int trim = constrain((int)lroundf(KP_YAW * yawErr), -YAW_PWM_LIM, YAW_PWM_LIM);
    apply(l + trim, r - trim, p);
}

void controlStop()
{
    motorsStop();
    g.pwmL = g.pwmR = 0;
}
