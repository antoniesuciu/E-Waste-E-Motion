// Robot identity, network, pins and drive tuning. Edit this file per robot.
#pragma once
#include <Arduino.h>
#include <IPAddress.h>

#if __has_include("secrets.h")
#include "secrets.h" // WIFI_SSID, WIFI_PASS (gitignored)
#else
#error "Copy secrets.example.h to secrets.h and fill in the Wi-Fi credentials."
#endif

// ======== IDENTITY / NETWORK ========
constexpr int ROBOT_ID = 3;                     // must match src/config.py ROBOT_ENDPOINTS
const IPAddress DEFAULT_SERVER_IP(192, 168, 0, 120); // telemetry target until the first command arrives
constexpr uint16_t CMD_PORT = 12345;            // commands from the control host
constexpr uint16_t TELEM_PORT = 12346;          // telemetry to the control host
constexpr uint32_t CMD_TIMEOUT_MS = 300;        // failsafe: stop if no command for this long
constexpr uint32_t TELEMETRY_INTERVAL_MS = 100;
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 20000;

// ======== DRIVE TUNING ========
// Inputs are floats in [-1, +1].
constexpr float DEAD_BAND_THR = 0.03f;
constexpr float DEAD_BAND_STR = 0.03f;
constexpr float K_THR = 1.00f;  // forward/back gain
constexpr float K_TURN = 0.60f; // turning gain
constexpr int PWM_CAP = 255;
constexpr int MIN_PWM_MAG = 40; // overcome static friction
constexpr int MAX_DPWM = 60;    // slew limit per update

// Spin mode: near-zero throttle with steering -> in-place rotation.
constexpr float SPIN_THR_THRESH = 0.12f;
constexpr float K_TURN_SPIN = 0.8f;
constexpr int MIN_PWM_MAG_SPIN = 150;
constexpr int MAX_DPWM_SPIN = 120;

// ======== PLAYBACK FOLLOWING ========
constexpr float KP_TICK = 0.8f;      // encoder tick error -> PWM
constexpr long TICK_DEADBAND = 3;    // ignore tiny tick errors so a parked robot doesn't hunt
constexpr float KP_YAW = 0.5f;       // yaw error (deg) -> PWM
constexpr int YAW_PWM_LIM = 50;
constexpr int TICK_TO_PWM_SIGN_A = +1; // left, depends on wiring
constexpr int TICK_TO_PWM_SIGN_B = -1; // right, depends on wiring

// ======== PINS ========
constexpr uint8_t PIN_ENA = 14; // left PWM
constexpr uint8_t PIN_IN1 = 26; // left direction A
constexpr uint8_t PIN_IN2 = 27; // left direction B
constexpr uint8_t PIN_ENB = 25; // right PWM
constexpr uint8_t PIN_IN3 = 33; // right direction A
constexpr uint8_t PIN_IN4 = 32; // right direction B

constexpr uint8_t PIN_ENC_L_A = 36; // input-only pins: encoders need external pull-ups
constexpr uint8_t PIN_ENC_L_B = 39;
constexpr uint8_t PIN_ENC_R_A = 34;
constexpr uint8_t PIN_ENC_R_B = 35;

// ======== PWM (LEDC) ========
constexpr uint32_t PWM_FREQ = 5000;
constexpr uint8_t PWM_RES_BITS = 8; // 0..255
constexpr uint8_t PWM_CH_L = 0;     // used only on ESP32 Arduino core 2.x
constexpr uint8_t PWM_CH_R = 1;

// ~12.5 us glitch filter (1000 APB cycles at 80 MHz). Raise if encoders still bounce.
constexpr uint16_t PCNT_GLITCH_CYCLES = 1000;
