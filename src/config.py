# per-robot network settings
ROBOT_ENDPOINTS = {
    1: { "ip": "192.168.0.101", "cmd_port": 12345, "telem_port": 12346 }, # erou
    2: { "ip": "192.168.0.102", "cmd_port": 12345, "telem_port": 12346 }, # oglinda
    3: { "ip": "192.168.0.103", "cmd_port": 12345, "telem_port": 12346 }, # fotoliu
    4: { "ip": "192.168.0.104", "cmd_port": 12345, "telem_port": 12346 }, # scannerul
    5: { "ip": "192.168.0.105", "cmd_port": 12345, "telem_port": 12346 }, # aspiratorul
    6: { "ip": "192.168.0.106", "cmd_port": 12345, "telem_port": 12346 }, # jucarie 1
    7: { "ip": "192.168.0.107", "cmd_port": 12345, "telem_port": 12346 }, # jucarie 2
    8: { "ip": "192.168.0.108", "cmd_port": 12345, "telem_port": 12346 }, # brat robotic
    9: { "ip": "192.168.0.109", "cmd_port": 12345, "telem_port": 12346 },
    10: { "ip": "192.168.0.150", "cmd_port": 12345, "telem_port": 12346 },    
    11:{ "ip": "192.168.0.111", "cmd_port": 12345, "telem_port": 12346 },    
    12:{ "ip": "192.168.0.111", "cmd_port": 12345, "telem_port": 12346 },    
    13:{ "ip": "192.168.0.111", "cmd_port": 12345, "telem_port": 12346 },    
    14:{ "ip": "192.168.0.111", "cmd_port": 12345, "telem_port": 12346 },
}

# Extra raw UDP targets to send when a robot is selected, without registering them in ROBOT_ENDPOINTS
# Keys are the selected robot IDs; values are a list of dicts with "ip", "port",
# and optional "robotId" used in the payload (if omitted, the selected rid is used).
FANOUT_EXTRA_TARGETS = {
    10: [
        {"ip": "192.168.0.151", "port": 12345},
        {"ip": "192.168.0.152", "port": 12345},
        {"ip": "192.168.0.153", "port": 12345},
    ],
}

# a handy list of valid robot IDs
ROBOT_IDS = list(ROBOT_ENDPOINTS.keys())

# file storage
RECORDINGS_DIR = '../recordings'
COURSES_FILE   = '../courses.json'

# controller settings (unchanged)
DEADZONE = 0.05
SEND_HZ  = 10
SEND_DT  = 1.0 / SEND_HZ

CONTROLLER_BY_PATH = {
    1: "/dev/input/by-path/platform-xhci-hcd.0-usb-0:1:1.0-joystick",  # Controller 1
    2: "/dev/input/by-path/platform-xhci-hcd.0-usb-0:2:1.0-joystick",  # Controller 2
}


# Whitelists for which robots should receive servo commands
SERVO_BOTH_ROBOTS = ['2','8']   # gets s1 and s2
SERVO_S1_ROBOTS   = ['3']        # gets only s1
SERVO_S2_ROBOTS   = []        # gets only s2

