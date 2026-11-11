#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoJson.h> // v7
#include "config.h"
#include "state.h"
#include "control.h"
#include "encoders.h"
#include "imu.h"
#include "net.h"

static WiFiUDP udp;
static IPAddress telemDest = DEFAULT_SERVER_IP;
static uint32_t telemSeq = 0;
static uint32_t lastTelemMs = 0;

void netBegin()
{
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false); // modem sleep delays UDP by 100+ ms, enough to trip the failsafe
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.printf("[ESP] Connecting to %s", WIFI_SSID);
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < WIFI_CONNECT_TIMEOUT_MS) {
        delay(500);
        Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED)
        Serial.printf(" connected, IP=%s\n", WiFi.localIP().toString().c_str());
    else
        Serial.println(" failed; the driver keeps retrying in the background");

    udp.begin(CMD_PORT);
    Serial.printf("[ESP] Listening on UDP %u\n", CMD_PORT);
}

// Zero encoders and yaw; playback targets are relative to this point.
static void zeroSensors()
{
    encodersZero();
    imuZero(200);
}

static void handleAction(const char *act)
{
    g.lastCmdMs = millis();

    if (!strcmp(act, "reset")) {
        zeroSensors();
        Serial.println("[ESP] reset: encoders + yaw zeroed");
    } else if (!strcmp(act, "play_start")) {
        controlStop();
        g.mode = Mode::Play;
        Serial.println("[ESP] play_start");
    } else if (!strcmp(act, "play_stop")) {
        controlStop();
        g.mode = Mode::Idle;
        Serial.println("[ESP] play_stop");
    } else if (!strcmp(act, "record_start") || !strcmp(act, "telem_start")) {
        controlStop();
        g.thr = g.str = 0.0f;
        g.spin = false;
        zeroSensors();
        telemSeq = 0; // the host trims recordings to the first seq 0/1 packet
        lastTelemMs = millis();
        g.telemetryOn = true;
        g.mode = Mode::Record;
        Serial.println("[ESP] record_start: sensors zeroed, telemetry on");
    } else if (!strcmp(act, "record_stop") || !strcmp(act, "telem_stop")) {
        g.telemetryOn = false;
        g.mode = Mode::Idle;
        Serial.println("[ESP] record_stop: telemetry off");
    } else {
        Serial.printf("[ESP][WARN] unknown action '%s'\n", act);
    }
}

void netReceive()
{
    if (udp.parsePacket() <= 0)
        return;

    char buf[512];
    int n = udp.read(buf, sizeof(buf));
    if (n <= 0)
        return;

    JsonDocument doc;
    if (deserializeJson(doc, buf, n)) {
        Serial.println("[ESP][WARN] JSON parse error");
        return;
    }
    if (!doc["r"].isNull() && doc["r"].as<int>() != ROBOT_ID)
        return;

    telemDest = udp.remoteIP(); // reply to whichever host is controlling us

    if (const char *act = doc["action"]) {
        handleAction(act);
        return;
    }

    if (!doc["s1"].isNull())
        g.s1 = doc["s1"].as<float>();

    bool hasDrive = !doc["t"].isNull() && !doc["s"].isNull();
    bool hasTarget = !doc["A"].isNull() && !doc["B"].isNull() && !doc["g"].isNull();

    if (g.mode == Mode::Play && hasTarget) {
        g.thr = doc["t"] | 0.0f;
        g.str = doc["s"] | 0.0f;
        g.lastCmdMs = millis();
        controlPlayback(g.thr, g.str, doc["A"].as<long>(), doc["B"].as<long>(), doc["g"].as<float>());
    } else if (hasDrive) {
        g.thr = doc["t"].as<float>();
        g.str = doc["s"].as<float>();
        g.lastCmdMs = millis();
        controlManual(g.thr, g.str);
    }
}

void netSendTelemetry()
{
    if (!g.telemetryOn)
        return;
    uint32_t now = millis();
    if (now - lastTelemMs < TELEMETRY_INTERVAL_MS)
        return;
    lastTelemMs = now;

    JsonDocument t;
    t["r"] = ROBOT_ID;
    t["seq"] = telemSeq++;
    t["t_ms"] = now;
    t["t"] = g.thr;
    t["s"] = g.str;
    t["L"] = g.pwmL;
    t["R"] = g.pwmR;
    t["sp"] = g.spin;
    t["A"] = encoderA();
    t["B"] = encoderB();
    t["g"] = imuYaw();
    t["s1"] = g.s1;

    char buf[256];
    size_t n = serializeJson(t, buf, sizeof(buf));
    udp.beginPacket(telemDest, TELEM_PORT);
    udp.write(reinterpret_cast<const uint8_t *>(buf), n);
    udp.endPacket();
}
