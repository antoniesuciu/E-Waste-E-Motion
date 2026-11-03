# pi_commands.py
import socket
import json
import time

CMD_PORT = 12345

def _send_udp(payload: dict, ip: str, port: int = CMD_PORT) -> None:
    """
    Send a fire-and-forget UDP packet containing the JSON payload,
    with debug prints showing exactly what’s sent.
    """
    data = json.dumps(payload).encode('utf-8')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        print(f"[PI] → UDP {ip}:{port} | {payload}")
        sent = sock.sendto(data, (ip, port))
        print(f"[PI]   sent {sent} bytes")
    except Exception as e:
        print(f"[PI][ERROR] sendto → {ip}:{port} failed: {e}")
    finally:
        sock.close()


def set_mode(ip: str, action: str) -> None:
    """
    Switch the ESP into one of:
      'record_start', 'record_stop',
      'download_start', 'download_stop',
      'reset', 'play_start', 'play_stop'
    """
    if action not in {
        'record_start', 'record_stop',
        'download_start', 'download_stop',
        'reset', 'play_start', 'play_stop'
    }:
        raise ValueError(f"Invalid action: {action}")
    print(f"[PI] set_mode → {action}")
    _send_udp({'action': action}, ip)

def send_led_rid(ip: str, robot_id: int, led: int, t_ms: int | None = None, **extra) -> None:
    """
    Send: {"robotId": <rid>, "led": <int>[, "t_ms": <int>]}
    Use for robot 9 during playback ticks (LED-only).
    """
    payload = {"r": int(robot_id), "l": int(led)}
    if t_ms is not None:
        payload["t_ms"] = int(t_ms)
    payload.update({k: v for k, v in extra.items() if v is not None})
    print(f"[PI] led_rid → {payload}")
    _send_udp(payload, ip)
    

def drive(ip: str, robot_id: int, throttle: float, steering: float) -> None:
    """
    Send a single drive update.
    """
    payload = {
        'r': robot_id,
        't': float(throttle),
        's': float(steering)
    }
    print(f"[PI] drive → robot {robot_id}, thr={throttle:.3f}, str={steering:.3f}")
    _send_udp(payload, ip)


def drivep(ip: str, robot_id: int, gyro: float, encA: int, encB: int,
           throttle: float, steering: float, s1=None, s2=None, led=None, t_ms=None) -> None:
    """
    Send a single playback/drive tick with encoders & gyro.
    Fields match the ESP:
      r, g, A, B, t, s
    Optional:
      s1, s2, l, t_ms
    """
    payload = {
        'r': int(robot_id),
        'g': float(gyro),
        'A': int(encA),
        'B': int(encB),
        't': float(throttle),
        's': float(steering)
    }
    if s1  is not None: payload['s1'] = float(s1)
    if s2  is not None: payload['s2'] = float(s2)
    if led is not None: payload['l']  = int(led)
    if t_ms is not None: payload['t_ms'] = int(t_ms)

    print(f"[PI] drivep → r={robot_id} A={encA} B={encB} g={gyro:.2f} "
          f"t={throttle:.3f} s={steering:.3f}"
          f"{'' if s1 is None else f' s1={s1:.3f}'}"
          f"{'' if s2 is None else f' s2={s2:.3f}'}"
          f"{'' if led is None else f' l={led}'}"
          f"{'' if t_ms is None else f' t_ms={t_ms}'}")
    _send_udp(payload, ip)
