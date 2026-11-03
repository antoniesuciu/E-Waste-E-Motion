#!/usr/bin/env python3
import os
import json
import datetime
import threading
import uuid
import utils 
import time
import state
from copy import deepcopy
from flask import Flask, request, jsonify, render_template, send_from_directory, Response
from udp_manager import set_mode, drive, drivep, send_led_rid

import config
from utils import load_courses, save_courses, find_course, create_course, ensure_recordings_dir

# Ensure storage directory exists
ensure_recordings_dir()

playback_threads: dict[str, threading.Thread] = {}
playback_stop_events: dict[str, threading.Event] = {}

# Load stored courses
state.course_state['courses'].extend(load_courses())


def _ensure_controller_bucket_unlocked(ps, key: str):
    ctrls = ps.setdefault('controllers', {})
    return ctrls.setdefault(key, {
        'selected_robot': None,
        'axes': [],
        'buttons': [],
        'enabled': True,
        'disabled': False,
        'last_update': None,
    })

def _first_start_idx(ents, accept_seq=(0, 1), max_scan=200):
    """
    Find the first entry to start a move. Prefer seq in accept_seq.
    Limit scanning to max_scan entries to avoid pathological lists.
    Fallback: return 0 if list non-empty; None if empty.
    """
    if not ents:
        return None
    scan = ents[:max_scan]
    for i, e in enumerate(scan):
        telem = (e or {}).get('telemetry') or {}
        seq = telem.get('seq')
        if seq in accept_seq:
            return i
    return 0
    
def _assign_robot_to_controller_unlocked(ps, controller_key: str, robot: int | None):
    """
    Steal semantics:
      - If robot is None → just clear this controller’s selection.
      - If robot is an int → clear it from the other controller (if any) and assign here.
    Returns a snapshot of both controller selections.
    """
    ctrls = ps.setdefault('controllers', {})
    c_this = _ensure_controller_bucket_unlocked(ps, controller_key)
    c_other_key = '2' if controller_key == '1' else '1'
    c_other = _ensure_controller_bucket_unlocked(ps, c_other_key)

    if robot is None:
        c_this['selected_robot'] = None
    else:
        if c_other.get('selected_robot') == robot:
            c_other['selected_robot'] = None
        c_this['selected_robot'] = robot

    return {
        '1': ctrls['1'].get('selected_robot'),
        '2': ctrls['2'].get('selected_robot'),
    }


def _default_controller():
    return {
        'selected_robot': None,
        'axes': [],
        'buttons': [],
        'enabled': True,
        'disabled': False,
        'last_update': None,
    }

def _reset_play_state_unlocked(ps):
    """Rebuild play_state for the new 2-controller model."""
    ps['controllers'] = {
        '1': _default_controller(),
        '2': _default_controller(),
    }
    ps['telemetry'] = {}
    # Optional: if you’re 100% migrated, you can drop this cleanup.
    for k in ('selected_robot', 'axes', 'buttons', 'last_update'):
        ps.pop(k, None)

def _clear_all_controller_selections_unlocked(ps):
    """Only clear which robot each controller is mapped to."""
    controllers = ps.setdefault('controllers', {})
    for key in ('1', '2'):
        ctrl = controllers.setdefault(key, _default_controller())
        ctrl['selected_robot'] = None

# Flask app
def create_app():
    app = Flask(__name__, static_folder='../static', template_folder='../templates')
    
    @app.after_request
    def add_cors(resp):
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        return resp

    @app.route('/')
    def index():
        return render_template('index.html', robots=config.ROBOT_IDS)

            
    def _json_safe(x):
        if isinstance(x, dict):  return {k: _json_safe(v) for k,v in x.items()}
        if isinstance(x, list):  return [_json_safe(v) for v in x]
        if isinstance(x, set):   return [_json_safe(v) for v in x]   # sets -> lists
        if isinstance(x, datetime.datetime): return x.isoformat()
        return x

# ── /stream: SSE with new multi-controller play_state ───────────────────────────
    @app.route("/stream")
    def stream():
        def build_payload():
            with state.lock:
                play   = deepcopy(state.play_state)
                course = deepcopy(state.course_state)

            # compute dynamic course_time if sampling
            if course.get("sampling") and "sampling_start_time" in course:
                ct = time.time() - float(course["sampling_start_time"])
            else:
                ct = float(course.get("course_time", 0.0))

            course_payload = {
                "sampling": bool(course.get("sampling")),
                "course_time": max(0.0, float(ct)),
                "dt": course.get("dt"),
                "current_course": course.get("current_course"),
                "recording_robots": list(course.get("recording_robots", [])),
                "moves_len": len(course.get("moves", [])),
            }

            return _json_safe({
                "play": play,
                "course": course_payload,
            })


        def gen():
            yield f"data: {json.dumps(build_payload(), default=str)}\n\n"
            while True:
                time.sleep(0.2)  # ~5 Hz
                yield f"data: {json.dumps(build_payload(), default=str)}\n\n"

        resp = Response(gen(), mimetype="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        return resp


    # ── /robots: list available robot IDs and selected per controller ──────────────
    @app.route('/robots', methods=['GET'])
    def list_robots():
        with state.lock:
            controllers = state.play_state.get('controllers', {})
            # Map of controllerId -> selected robotId (or None)
            selected = {str(cid): controllers.get(cid, {}).get('selected_robot') for cid in controllers.keys()}
        return jsonify({
            'available': config.ROBOT_IDS,
            'selected': selected
        }), 200


    @app.route('/select_robot', methods=['POST'])
    def select_robot():
        data = request.get_json(force=True) or {}

        # controller: 1 or 2 (default 1)
        try:
            controller_num = int(data.get('controller', 1))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid controller id.'}), 400
        if controller_num not in (1, 2):
            return jsonify({'error': 'Controller must be 1 or 2.'}), 400
        controller_key = str(controller_num)

        raw_robot = data.get('robot', None)

        # Clear selection (none/null/standby/0) → OK
        if raw_robot is None or str(raw_robot).strip().lower() in {'none', 'null', 'standby', 'stand', 'off', '0'}:
            with state.lock:
                selected_map = _assign_robot_to_controller_unlocked(state.play_state, controller_key, None)
            return jsonify({'controller': controller_num, 'selected': None, 'selected_map': selected_map}), 200

        # Otherwise must be a valid robot id
        try:
            robot = int(raw_robot)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid robot id.'}), 400
        if robot not in config.ROBOT_IDS:
            return jsonify({'error': f'Robot {robot} not available.'}), 400

        # STEAL semantics: move robot to this controller, unassign from the other if needed
        with state.lock:
            selected_map = _assign_robot_to_controller_unlocked(state.play_state, controller_key, robot)

        return jsonify({'controller': controller_num, 'selected': robot, 'selected_map': selected_map}), 200




    # Course CRUD


    


    # --- Single-move playback -----------------------------------------------




    # ----------------------------------------------------------------------




    # Edit a course (metadata only: name, duration)

        # Delete a course and its recording
        




        
    









    

        
    return app


if __name__ == '__main__':

    import threading
    from controller_thread import controller_loop
    from telemetry_thread import start_telemetry_threads

    threading.Thread(target=controller_loop, daemon=True).start()
    start_telemetry_threads()
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    print('[INIT] Starting Flask on port 5000')
    create_app().run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
