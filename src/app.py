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
    @app.route('/api/courses', methods=['GET'])
    def api_get_courses():
        return jsonify(state.course_state['courses']), 200

    @app.route('/api/courses', methods=['POST'])
    def api_create_course():
        data = request.get_json(force=True) or {}
        name = data.get('name', '')
        duration = data.get('duration', 0)
        course = create_course(name, duration)

        with state.lock:
            cs = state.course_state
            ps = state.play_state

            # course reset
            cs['current_course'] = course
            cs['course_time'] = 0.0
            cs['recording_robots'].clear()
            cs['sampling'] = False
            cs['moves'].clear()

            # play_state reset → two controllers, no selection by default
            ps['controllers'] = {
                '1': {
                    'selected_robot': None,
                    'axes': [],
                    'buttons': [],
                    'enabled': True,
                    'disabled': False,
                    'last_update': None,
                },
                '2': {
                    'selected_robot': None,
                    'axes': [],
                    'buttons': [],
                    'enabled': True,
                    'disabled': False,
                    'last_update': None,
                },
            }
            ps['telemetry'] = {}

            # clean up any legacy single-controller keys if they exist
            for k in ('selected_robot', 'axes', 'buttons', 'last_update'):
                ps.pop(k, None)

        return jsonify(course), 201

    
    @app.route('/api/courses/<course_id>', methods=['GET'])
    def api_get_course(course_id):
        course = find_course(state.course_state['courses'], course_id)
        if course:
            # Load saved moves
            filepath = os.path.join(config.RECORDINGS_DIR, f"{course_id}.json")
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    course['moves'] = json.load(f)
                course['robotCount'] = len({m['robotId'] for m in course['moves']})
            else:
                course['moves'] = []
            return jsonify(course), 200
        return jsonify({'error': 'Course not found.'}), 404


    # --- Single-move playback -----------------------------------------------




    # ----------------------------------------------------------------------


    @app.route('/api/course/edit/<course_id>/begin', methods=['POST'])
    def api_begin_edit_course(course_id):
        # load course metadata
        courses_list = load_courses()
        course = find_course(courses_list, course_id)
        if not course:
            return jsonify({'error': 'Course not found.'}), 404

        # load moves file (if any)
        filepath = os.path.join(config.RECORDINGS_DIR, f"{course_id}.json")
        moves = []
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                moves = json.load(f)

        # set as current course and prime in-memory state
        with state.lock:
            cs = state.course_state

            # active course
            cs['current_course'] = deepcopy(course)

            # fresh editing state
            cs['moves'] = moves
            cs['recording_robots'] = set()
            cs['sampling'] = False
            cs['course_time'] = 0.0
            cs.pop('sampling_start_time', None)

            # two-controller fresh state
            _reset_play_state_unlocked(state.play_state)

        # include robotCount for convenience
        course_out = dict(course)
        course_out['moves'] = moves
        course_out['robotCount'] = len({m.get('robotId') for m in moves})

        return jsonify(course_out), 200


    # Edit a course (metadata only: name, duration)
    @app.route('/api/courses/<course_id>', methods=['PATCH', 'PUT'])
    def api_update_course(course_id):
        data = request.get_json(force=True) or {}

        # Only allow fields you already persist
        allowed = {'name', 'duration'}
        unknown = set(data.keys()) - allowed
        if unknown:
            return jsonify({'error': f'Unknown fields: {sorted(unknown)}'}), 400

        # For PUT, require both fields
        if request.method == 'PUT':
            missing = [k for k in allowed if k not in data]
            if missing:
                return jsonify({'error': f'Missing fields for PUT: {missing}'}), 400

        # Basic type normalization
        if 'duration' in data:
            try:
                # accept int/float/str → float
                data['duration'] = float(data['duration'])
            except (TypeError, ValueError):
                return jsonify({'error': 'duration must be a number'}), 400

        with state.lock:
            courses_list = state.course_state['courses']
            course = find_course(courses_list, course_id)
            if not course:
                return jsonify({'error': 'Course not found.'}), 404

            # Merge updates
            updated = dict(course)
            for k in allowed:
                if k in data:
                    updated[k] = data[k]

            # Update in-memory list
            for i, c in enumerate(courses_list):
                if c.get('id') == course_id:
                    courses_list[i] = updated
                    break

            # If this is also the active course, mirror the change
            cc = state.course_state.get('current_course')
            if cc and cc.get('id') == course_id:
                for k in allowed:
                    if k in data:
                        cc[k] = data[k]

            # Persist to courses.json
            save_courses(courses_list)

        return jsonify(updated), 200

        # Delete a course and its recording
    @app.route('/api/courses/<course_id>', methods=['DELETE'])
    def api_delete_course(course_id):
        # Remove from courses.json
        courses_list = load_courses()
        course = find_course(courses_list, course_id)
        if not course:
            return jsonify({'error': 'Course not found.'}), 404
        updated = [c for c in courses_list if c['id'] != course_id]
        save_courses(updated)
        # Also update in-memory state list
        state.course_state['courses'] = updated
        # Delete associated moves file
        filepath = os.path.join(config.RECORDINGS_DIR, f"{course_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'status': 'deleted'}), 200
        




        
    

    @app.route('/api/course/load/<course_id>', methods=['GET'])
    def api_load_course_file(course_id):
        filepath = os.path.join(config.RECORDINGS_DIR, f"{course_id}.json")
        if not os.path.exists(filepath):
            return jsonify({'error': 'Course file not found'}), 404
        with open(filepath, 'r') as f:
            moves = json.load(f)
        return jsonify({'id': course_id, 'moves': moves}), 200

    @app.route('/api/course/download/<course_id>', methods=['GET'])
    def api_download_course(course_id):
        return send_from_directory(config.RECORDINGS_DIR, f"{course_id}.json", as_attachment=True)







    

        
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
