import socket
import json
import threading
import time
import state
from config import ROBOT_ENDPOINTS

def telemetry_loop(port: int):
    """Listen for UDP telemetry and update play_state['telemetry'] per robot."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # optional: bigger buffer
    sock.bind(("", port))
    print(f"[TELEM] Listening on port {port}")

    while True:
        try:
            data, _ = sock.recvfrom(2048)  # allow room
        except Exception:
            continue

        try:
            pkt = json.loads(data.decode("utf-8"))
            rid_val = pkt.get("r")
            if rid_val is None:
                continue
            rid_int = int(rid_val)
            if rid_int not in ROBOT_ENDPOINTS:
                continue
            rid_key = str(rid_int)
        except Exception:
            continue

        # Store latest snapshot (and an optional last_seen)
        with state.lock:
            ps = state.play_state
            telem = ps.setdefault("telemetry", {})  # <-- key unified
            pkt["_last_seen_ms"] = int(time.time() * 1000)  # optional, handy
            telem[rid_key] = pkt

def start_telemetry_threads():
    """Spawn one telemetry listener per robot port."""
    for rid, ep in ROBOT_ENDPOINTS.items():
        threading.Thread(
            target=telemetry_loop,
            args=(ep["telem_port"],),
            daemon=True,
        ).start()
