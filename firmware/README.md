# Robot firmware

ESP32 firmware for the differential-drive robots. It takes drive commands from the control host (`src/`), streams telemetry during recording, and in playback follows the recorded encoder ticks and yaw.

## Layout

| File | Responsibility |
| --- | --- |
| `robot/robot.ino` | `setup()` / `loop()`, failsafe |
| `robot/config.h` | Robot ID, ports, pins, drive tuning: edit per robot |
| `robot/state.h` | Shared runtime state (`RobotState g`) |
| `robot/net.*` | Wi-Fi, UDP command dispatch, telemetry |
| `robot/control.*` | Throttle/steering mixing, slew limit, playback following |
| `robot/motors.*` | H-bridge output (LEDC PWM) |
| `robot/encoders.*`, `encoder_math.h` | Quadrature encoders on the hardware pulse counter |
| `robot/imu.*` | MPU6050 yaw |
| `test/` | Host tests for logic that does not need hardware |

## Build and flash

Requires the Arduino-ESP32 core (2.x or 3.x), **ArduinoJson 7.x** and **MPU6050_light**.

```bash
cp firmware/robot/secrets.example.h firmware/robot/secrets.h   # then fill in Wi-Fi credentials
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/robot
arduino-cli upload  --fqbn esp32:esp32:esp32 -p /dev/ttyUSB0 firmware/robot
```

Set `ROBOT_ID` in `config.h` to the robot's entry in `src/config.py`. The robot must get the IP listed there; the firmware uses DHCP, so reserve the address on the router. Keep the robot still during boot while the gyro calibrates.

## Wire protocol (JSON over UDP)

Commands arrive on port 12345. Packets with `r` set to another robot are ignored.

| Packet | Meaning |
| --- | --- |
| `{"action": "reset"}` | Zero encoders and yaw |
| `{"action": "record_start"}` | Stop, zero sensors, restart telemetry from `seq` 0, enter record mode |
| `{"action": "record_stop"}` | Telemetry off, idle |
| `{"action": "play_start"}` / `"play_stop"` | Enter/leave playback |
| `{"r", "t", "s"[, "s1"]}` | Manual drive: throttle and steering in [-1, 1] |
| `{"r", "t", "s", "A", "B", "g"}` in playback | Follow recorded left/right ticks and yaw (deg) with `t`/`s` as feed-forward |

The motors stop when no command arrives for 300 ms.

Telemetry is sent every 100 ms to the host that last sent a command, on port 12346:
`{"r", "seq", "t_ms", "t", "s", "L", "R", "sp", "A", "B", "g", "s1"}`. `L`/`R` are the signed PWM outputs, `sp` is spin mode. The host stores these packets as recordings and sends them back during playback, so the field names on both sides must match.

`s1` is accepted and echoed for recording compatibility; this firmware drives no servo.

## Tests

```bash
bash scripts/check.sh firmware
```
