import threading
from copy import deepcopy
from config import SEND_DT

lock = threading.Lock()

# One play object with two controllers inside it.
# Keys "1" and "2" are strings so JSON/SSE is straightforward.
play_state = {
    "controllers": {
        "1": {
            "selected_robot": None,   # prefer an int robotId (or None)
            "axes": [],               # list[float]
            "buttons": [],            # list[int] or list[bool]
            "enabled": True,
            "disabled": False,
            "last_update": None,      # monotonic or wall time
        },
        "2": {
            "selected_robot": None,
            "axes": [],
            "buttons": [],
            "enabled": True,
            "disabled": False,
            "last_update": None,
        },
    },
    # Latest telemetry per robot (as received from ESPs)
    # e.g. { "1": {...}, "2": {...} }
    "telemetry": {}
}

course_state = {
    "current_course": None,
    "courses": [],
    "recording_robots": set(),   # convert to list in /stream
    "moves": [],
    "sampling": False,
    "course_time": 0.0,
    "dt": SEND_DT,
}
