import time
import socket
import json
import datetime
import pygame
import state
import config
import os

def _js_index_for(by_path: str) -> int | None:
    """Resolve /dev/input/by-path/...-joystick -> /dev/input/jsN, return N."""
    try:
        real = os.path.realpath(by_path)   # e.g. /dev/input/js0
        base = os.path.basename(real)      # "js0"
        if base.startswith("js"):
            return int(base[2:])
    except Exception:
        pass
    return None

def _open_joystick(by_path: str, retries: int = 20, delay: float = 0.1):
    """Retry a little to survive hotplug/boot race."""
    idx = None
    for _ in range(retries):
        idx = _js_index_for(by_path)
        if idx is not None:
            break
        time.sleep(delay)
    if idx is None:
        return None, None
    joy = pygame.joystick.Joystick(idx)
    joy.init()
    return joy, idx

def apply_deadzone(value, dz=config.DEADZONE):
    return 0.0 if abs(value) < dz else round(value, 3)

# Button indices (override in config if different)
BTN_A  = getattr(config, "BTN_A", 0)
BTN_B  = getattr(config, "BTN_B", 1)
BTN_X  = getattr(config, "BTN_X", 2)
BTN_Y  = getattr(config, "BTN_Y", 3)
BTN_LB = getattr(config, "BTN_LB", 4)
BTN_RB = getattr(config, "BTN_RB", 5)

def _axis_safe(joy, axis_idx, default=0.0):
    try:
        return joy.get_axis(axis_idx) if axis_idx < joy.get_numaxes() else default
    except Exception:
        return default

def _to_01(v):
    """Map typical axis [-1..+1] or [0..1] into clean [0..1]."""
    if v < 0.0 or v > 1.0:
        v = 0.5 * (v + 1.0)  # [-1..1] -> [0..1]
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)

def _norm_ids(lst):
    return {str(x) for x in lst}

ALLOWED_S1 = _norm_ids(getattr(config, "SERVO_S1_ROBOTS", [])) | _norm_ids(getattr(config, "SERVO_BOTH_ROBOTS", []))
ALLOWED_S2 = _norm_ids(getattr(config, "SERVO_S2_ROBOTS", [])) | _norm_ids(getattr(config, "SERVO_BOTH_ROBOTS", []))

BUTTON_COUNT_HINT = getattr(config, "BUTTON_COUNT_HINT", 12)

# Axes config
SERVO1_AXIS   = getattr(config, "SERVO1_AXIS", 3)  # right stick X
SERVO2_AXIS   = getattr(config, "SERVO2_AXIS", 4)  # right stick Y
SERVO_DZ      = getattr(config, "SERVO_DZ", 0.35)
SERVO1_INVERT = getattr(config, "SERVO1_INVERT", False)
SERVO2_INVERT = getattr(config, "SERVO2_INVERT", False)

TRIGGER3_AXIS = getattr(config, "TRIGGER3_AXIS", 2)   # LT
TRIGGER4_AXIS = getattr(config, "TRIGGER4_AXIS", 5)   # RT
TRIGGER_DZ    = getattr(config, "TRIGGER_DZ", 0.05)

# LED fanout extras (LED-only)
FANOUT_EXTRA_TARGETS = getattr(config, "FANOUT_EXTRA_TARGETS", {})

def _get(arr, i, default=0):
    return arr[i] if 0 <= i < len(arr) else default

# ===== Robot-10 brightness via RAW right stick X (no fade_ms, led optional) =====
BRIGHT_SEND_INTERVAL_MS = 100   # min interval between brightness packets
BRIGHT_EPS_0_255        = 8     # min change to trigger send (0..255 scale)
BRIGHT_DEADZONE         = 0.08  # |axis| below this → ignore

def _axis_to_brightness_0_255(v):
    # v in [-1..+1] => 0..255  (-1->0, 0->128, +1->255)
    br = int(round((v + 1.0) * 0.5 * 255.0))
    return 0 if br < 0 else (255 if br > 255 else br)

def controller_loop():
    # Init pygame + open the exact devices for C1/C2
    pygame.init()
    pygame.joystick.init()

    c1_path = getattr(config, "CONTROLLER_BY_PATH", {}).get(1)
    c2_path = getattr(config, "CONTROLLER_BY_PATH", {}).get(2)

    joy1, js1 = _open_joystick(c1_path) if c1_path else (None, None)
    joy2, js2 = _open_joystick(c2_path) if c2_path else (None, None)

    joysticks = {1: joy1, 2: joy2}

    if not (joy1 or joy2):
        print(f"[CTRL][ERROR] No joystick at configured paths:\n  C1={c1_path}\n  C2={c2_path}")
        return

    print(f"[CTRL] C1 -> {c1_path or 'N/A'} (js{js1 if js1 is not None else 'X'})")
    print(f"[CTRL] C2 -> {c2_path or 'N/A'} (js{js2 if js2 is not None else 'X'})")

    # Ensure play_state structure exists
    with state.lock:
        ps = state.play_state
        controllers = ps.setdefault('controllers', {})
        for cid in ('1', '2'):
            controllers.setdefault(cid, {
                'selected_robot': None,
                'axes': [],
                'buttons': [],
                'enabled': True,
                'disabled': False,
                'last_update': None,
                'servo_axes': [0.0, 0.0],
            })
        ps.setdefault('telemetry', {})  # keep name consistent

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    prev_buttons = {1: [0] * BUTTON_COUNT_HINT, 2: [0] * BUTTON_COUNT_HINT}

    # Brightness last-sent state (per controller → robot 10 only)
    last_brightness_sent = {1: 128, 2: 128}
    last_brightness_ms   = {1: 0,   2: 0}

    while True:
        pygame.event.pump()
        now_iso = datetime.datetime.utcnow().isoformat() + 'Z'
        now_ms = int(time.time() * 1000)

        for controller_id in (1, 2):
            joy = joysticks.get(controller_id)
            if joy:
                try:
                    # Left stick (drive for normal robots)
                    raw_x = joy.get_axis(0)
                    raw_y = joy.get_axis(1)
                    x = apply_deadzone(raw_x)
                    y = apply_deadzone(raw_y)

                    # Buttons
                    buttons = [joy.get_button(i) for i in range(joy.get_numbuttons())]

                    # Right stick axes
                    s1_raw = _axis_safe(joy, SERVO1_AXIS, 0.0)  # RAW for robot 10 brightness
                    s2_raw = _axis_safe(joy, SERVO2_AXIS, 0.0)

                    # For non-10 robots, servo-processed versions
                    s1 = apply_deadzone(s1_raw, dz=SERVO_DZ)
                    s2 = apply_deadzone(s2_raw, dz=SERVO_DZ)
                    if SERVO1_INVERT: s1 = -s1
                    if SERVO2_INVERT: s2 = -s2
                    s1 = round(s1, 3)
                    s2 = round(s2, 3)

                    # Triggers
                    t3_raw = _axis_safe(joy, TRIGGER3_AXIS, 0.0)
                    t4_raw = _axis_safe(joy, TRIGGER4_AXIS, 0.0)
                    s3 = _to_01(t3_raw)
                    s4 = _to_01(t4_raw)
                    s3 = 0.0 if s3 < TRIGGER_DZ else round(s3, 3)
                    s4 = 0.0 if s4 < TRIGGER_DZ else round(s4, 3)
                except Exception:
                    x, y, buttons = 0.0, 0.0, prev_buttons[controller_id]
                    s1_raw = s2_raw = 0.0
                    s1 = s2 = 0.0
                    s3 = s4 = 0.0
            else:
                x, y, buttons = 0.0, 0.0, prev_buttons[controller_id]
                s1_raw = s2_raw = 0.0
                s1 = s2 = 0.0
                s3 = s4 = 0.0

            # Update play_state (for the UI)
            with state.lock:
                ps = state.play_state
                ctrl = ps['controllers'][str(controller_id)]
                ctrl['axes'] = [x, y]
                ctrl['buttons'] = buttons
                ctrl['servo_axes'] = [s1, s2]
                ctrl['last_update'] = now_iso
                rid = ctrl.get('selected_robot')

            # Button release edges for LED
            old    = prev_buttons[controller_id]
            a_rel  = _get(old, BTN_A, 0)  == 1 and _get(buttons, BTN_A, 0)  == 0
            x_rel  = _get(old, BTN_X, 0)  == 1 and _get(buttons, BTN_X, 0)  == 0
            y_rel  = _get(old, BTN_Y, 0)  == 1 and _get(buttons, BTN_Y, 0)  == 0
            b_rel  = _get(old, BTN_B, 0)  == 1 and _get(buttons, BTN_B, 0)  == 0
            lb_rel = _get(old, BTN_LB, 0) == 1 and _get(buttons, BTN_LB, 0) == 0
            rb_rel = _get(old, BTN_RB, 0) == 1 and _get(buttons, BTN_RB, 0) == 0

            led_code = None
            if   a_rel:  led_code = 4  # end/normal
            elif x_rel:  led_code = 1
            elif y_rel:  led_code = 2
            elif b_rel:  led_code = 3
            elif lb_rel: led_code = 5
            elif rb_rel: led_code = 6

            # No selected robot → skip
            if rid is None or rid not in config.ROBOT_ENDPOINTS:
                prev_buttons[controller_id] = buttons
                continue

            # ===== RID 10: LED-only + Brightness from RAW right-stick X =====
            if rid == 10:
                # 1) LED event → LED-only to 10 and extras
                if led_code is not None:
                    ep10 = config.ROBOT_ENDPOINTS[10]
                    led_payload_10 = {'r': 10, 'l': led_code}
                    try:
                        sock.sendto(json.dumps(led_payload_10).encode('utf-8'),
                                    (ep10['ip'], ep10['cmd_port']))
                        print(f"[CTRL] C{controller_id} → R10", led_payload_10)
                    except Exception as e:
                        print(f"[CTRL][ERROR] C{controller_id} send to {(ep10['ip'], ep10['cmd_port'])} failed: {e}")

                    # Fanout extras for 10 (LED-only)
                    extras = FANOUT_EXTRA_TARGETS.get(10, [])
                    for extra in extras:
                        ip = extra.get("ip"); port = extra.get("port")
                        if not ip or not port:
                            continue
                        try:
                            sock.sendto(json.dumps(led_payload_10).encode('utf-8'), (ip, port))
                            print(f"[CTRL] C{controller_id} → EXTRA {ip}:{port}", led_payload_10)
                        except Exception as e:
                            print(f"[CTRL][ERROR] C{controller_id} send to EXTRA {(ip, port)} failed: {e}")

                # 2) Brightness from raw X (optional; no 'l' in payload)
                try:
                    if abs(s1_raw) >= BRIGHT_DEADZONE:
                        br = _axis_to_brightness_0_255(s1_raw)
                        due = (now_ms - last_brightness_ms[controller_id]) >= BRIGHT_SEND_INTERVAL_MS
                        changed = abs(br - last_brightness_sent[controller_id]) >= BRIGHT_EPS_0_255
                        if due and changed:
                            payload = {'r': 10, 'b': br}
                            ep10 = config.ROBOT_ENDPOINTS[10]
                            try:
                                sock.sendto(json.dumps(payload).encode('utf-8'),
                                            (ep10['ip'], ep10['cmd_port']))
                                print(f"[CTRL] C{controller_id} → R10 (bright)", payload)
                                last_brightness_sent[controller_id] = br
                                last_brightness_ms[controller_id] = now_ms
                            except Exception as e:
                                print(f"[CTRL][ERROR] C{controller_id} send bright to {(ep10['ip'], ep10['cmd_port'])} failed: {e}")
                    # If near center: send nothing (keep last brightness)
                except Exception as e:
                    print(f"[CTRL][WARN] Brightness block error: {e}")

                prev_buttons[controller_id] = buttons
                continue

            # ===== RID 9: LED-only (no throttle/steering/servos) =====
            if rid == 9:
                if led_code is not None:
                    ep9 = config.ROBOT_ENDPOINTS[9]
                    led_payload_9 = {'r': 9, 'l': led_code}
                    try:
                        sock.sendto(json.dumps(led_payload_9).encode('utf-8'),
                                    (ep9['ip'], ep9['cmd_port']))
                        print(f"[CTRL] C{controller_id} → R9", led_payload_9)
                    except Exception as e:
                        print(f"[CTRL][ERROR] C{controller_id} send to {(ep9['ip'], ep9['cmd_port'])} failed: {e}")

                    # Optional fanout for 9
                    extras9 = FANOUT_EXTRA_TARGETS.get(9, [])
                    for extra in extras9:
                        ip = extra.get("ip"); port = extra.get("port")
                        if not ip or not port:
                            continue
                        try:
                            sock.sendto(json.dumps(led_payload_9).encode('utf-8'), (ip, port))
                            print(f"[CTRL] C{controller_id} → EXTRA {ip}:{port}", led_payload_9)
                        except Exception as e:
                            print(f"[CTRL][ERROR] C{controller_id} send to EXTRA {(ip, port)} failed: {e}")

                prev_buttons[controller_id] = buttons
                continue

            # ===== Normal robots =====
            ep = config.ROBOT_ENDPOINTS[rid]
            payload = {
                'r': rid,
                't': -y,
                's': x,
            }

            rid_key = str(rid)
            if rid_key in ALLOWED_S1:
                payload['s1'] = s1
            if rid_key in ALLOWED_S2:
                payload['s2'] = s2

            # Triggers s3/s4 only for robot 8
            if rid == 8:
                payload['s3'] = s3
                payload['s4'] = s4

            if led_code is not None:
                # Use short key for LED to match ESPs that expect 'l'
                payload['l'] = led_code

            target = (ep['ip'], ep['cmd_port'])
            try:
                sock.sendto(json.dumps(payload).encode('utf-8'), target)
                print(f"[CTRL] C{controller_id} → R{rid}", payload)
            except Exception as e:
                print(f"[CTRL][ERROR] C{controller_id} send to {target} failed: {e}")

            # Extra LED fanout (LED-only) for that robot
            extras = FANOUT_EXTRA_TARGETS.get(rid, [])
            if led_code is not None and extras:
                for extra in extras:
                    ip = extra.get("ip"); port = extra.get("port")
                    if not ip or not port:
                        continue
                    led_payload = {'r': rid, 'l': led_code}
                    try:
                        sock.sendto(json.dumps(led_payload).encode('utf-8'), (ip, port))
                        print(f"[CTRL] C{controller_id} → EXTRA {ip}:{port}", led_payload)
                    except Exception as e:
                        print(f"[CTRL][ERROR] C{controller_id} send to EXTRA {(ip, port)} failed: {e}")

            prev_buttons[controller_id] = buttons

        # ===== Recording append =====
        with state.lock:
            cs = state.course_state
            if cs['sampling'] and cs['current_course']:
                timestamp = round(cs['course_time'], 3)
                for r in cs['recording_robots']:
                    for move in reversed(cs['moves']):
                        if move['robotId'] == r and move.get('endT') is None:
                            entry = {
                                't': timestamp,
                                'telemetry': state.play_state['telemetry'].get(str(r))
                            }
                            move.setdefault('entries', []).append(entry)
                            break
                cs['course_time'] += cs['dt']

        time.sleep(config.SEND_DT)
