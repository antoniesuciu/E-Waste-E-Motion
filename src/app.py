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
    @app.route('/api/move/run/<course_id>/<move_id>', methods=['POST'])
    def api_run_single_move(course_id, move_id):
        """
        Play only one recorded move. Works with in-memory unsaved moves or from disk.
        Times are retimed so this move starts immediately (t0 -> 0).
        """
        # Prefer in-memory if current course matches
        with state.lock:
            cs = state.course_state
            if cs.get('current_course') and cs['current_course'].get('id') == course_id:
                moves_src = deepcopy(cs.get('moves', []))
            else:
                moves_src = None

        if moves_src is None:
            # Load from saved file
            filepath = os.path.join(config.RECORDINGS_DIR, f"{course_id}.json")
            if not os.path.exists(filepath):
                return jsonify({'error': 'Recording not found.'}), 404
            with open(filepath, 'r') as f:
                moves_src = json.load(f)

        mv = next((m for m in moves_src if m.get('id') == move_id), None)
        if not mv:
            return jsonify({'error': 'Move not found.'}), 404

        rid = int(mv.get('robotId'))
        ents = list(mv.get('entries') or [])
        if not ents:
            return jsonify({'error': 'Move has no entries.'}), 400

        start_idx = _first_start_idx(ents, accept_seq=(0, 1))
        if start_idx is None:
            return jsonify({'error': 'Move has no entries.'}), 400
        ents = ents[start_idx:]



        # Retimestamp so this move starts at 0
        try:
            t0 = float(ents[0]['t'])
        except Exception:
            t0 = 0.0

        entries = []
        for e in ents:
            try:
                t_rel = float(e.get('t', 0.0)) - t0
            except Exception:
                continue
            entries.append((max(0.0, t_rel), rid, e.get('telemetry')))
        entries.sort(key=lambda x: x[0])

        token = f"move:{course_id}:{move_id}"
        if token in playback_threads and playback_threads[token].is_alive():
            return jsonify({'error': 'Move already running.'}), 400

        # Arm only this robot
        ep = config.ROBOT_ENDPOINTS[rid]
        set_mode(ep['ip'], 'reset')
        time.sleep(0.1)
        set_mode(ep['ip'], 'play_start')
        time.sleep(0.1)

        stop_event = threading.Event()
        playback_stop_events[token] = stop_event

        def playback(stop_evt: threading.Event):
            completed_naturally = False
            try:
                start = time.time()
                total = len(entries)
                print(f"[PlaybackMove:{move_id}] started with {total} entries for robot {rid}", flush=True)

                for idx, (t_rel, rrid, telem) in enumerate(entries, start=1):
                    if stop_evt.is_set():
                        print(f"[PlaybackMove:{move_id}] stopped at entry {idx}", flush=True)
                        break
                    delay = (start + t_rel) - time.time()
                    if delay > 0:
                        time.sleep(delay)

                    ep_local = config.ROBOT_ENDPOINTS[rrid]
                    if telem:
                        try:
                            # same s1/s2 logic as your course runner
                            s1_val = s2_val = None
                            if str(rrid) in config.SERVO_BOTH_ROBOTS:
                                s1_val = telem.get('s1'); s2_val = telem.get('s2')
                            elif str(rrid) in config.SERVO_S1_ROBOTS:
                                s1_val = telem.get('s1')
                            elif str(rrid) in config.SERVO_S2_ROBOTS:
                                s2_val = telem.get('s2')
                            led_val = telem.get('l') if isinstance(telem, dict) and 'l' in telem else None
                            t_ms_val = telem.get('t_ms') if isinstance(telem, dict) and 't_ms' in telem else None

                            if rid == 9:
                                if led_val is not None:
                                    send_led_rid(ep['ip'], rid, led_val, t_ms=t_ms_val)
                                # skip drivep entirely for robot 9
                            elif rid == 10:
                                # Drive primary
                                drivep(
                                    ep['ip'], rid,
                                    telem.get('g', 0),  telem.get('A', 0), telem.get('B', 0),
                                    telem.get('t', 0),  telem.get('s', 0),
                                    s1=s1_val, s2=s2_val, led=led_val, t_ms=t_ms_val
                                )
                                # Fan out LED if present
                                if led_val is not None:
                                    for tgt in config.FANOUT_EXTRA_TARGETS.get(10, []):
                                        try:
                                            send_led_rid(tgt['ip'], rid, led_val, t_ms=t_ms_val)
                                        except Exception as e:
                                            print(f"[PlaybackMove:{move_id}] fanout to {tgt['ip']} failed: {e}", flush=True)

                            else:
                                drivep(
                                    ep['ip'], rid,
                                    telem.get('g', 0),  telem.get('A', 0), telem.get('B', 0),
                                    telem.get('t', 0),  telem.get('s', 0),
                                    s1=s1_val, s2=s2_val, led=led_val, t_ms=t_ms_val
                                )
                        except Exception as e:
                            print(f"[PlaybackMove:{move_id}] ERROR: {e}", flush=True)
                else:
                    completed_naturally = True

                if completed_naturally:
                    try:
                        ep0 = config.ROBOT_ENDPOINTS[rid]
                        set_mode(ep0['ip'], 'play_stop')
                        time.sleep(0.05)
                        print(f"[PlaybackMove:{move_id}] sent play_stop to robot {rid}", flush=True)
                    except Exception as e:
                        print(f"[PlaybackMove:{move_id}] play_stop failed: {e}", flush=True)
            finally:
                playback_stop_events.pop(token, None)
                playback_threads.pop(token, None)
                print(f"[PlaybackMove:{move_id}] thread exiting", flush=True)

        thread = threading.Thread(target=playback, args=(stop_event,), daemon=True)
        playback_threads[token] = thread
        thread.start()

        return jsonify({'status': 'Playback started', 'courseId': course_id, 'moveId': move_id}), 200


    @app.route('/api/move/stop/<course_id>/<move_id>', methods=['POST'])
    def api_stop_single_move(course_id, move_id):
        token = f"move:{course_id}:{move_id}"
        stop_event = playback_stop_events.get(token)
        thread = playback_threads.get(token)
        if not stop_event or not thread:
            return jsonify({'error': 'Move not running.'}), 400

        # Try to send play_stop to that robot (best-effort)
        rid = None
        with state.lock:
            cs = state.course_state
            if cs.get('current_course') and cs['current_course'].get('id') == course_id:
                mv = next((m for m in cs.get('moves', []) if m.get('id') == move_id), None)
                if mv: rid = int(mv.get('robotId'))
        if rid is None:
            filepath = os.path.join(config.RECORDINGS_DIR, f"{course_id}.json")
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r') as f:
                        ms = json.load(f)
                    mv = next((m for m in ms if m.get('id') == move_id), None)
                    if mv: rid = int(mv.get('robotId'))
                except Exception:
                    pass
        if rid is not None:
            ep = config.ROBOT_ENDPOINTS[rid]
            try:
                set_mode(ep['ip'], 'play_stop')
                time.sleep(0.1)
            except Exception as e:
                print(f"[PlaybackMove:{move_id}] play_stop on stop failed: {e}", flush=True)

        stop_event.set()
        thread.join(timeout=0.1)
        return jsonify({'status': 'Playback stopping', 'courseId': course_id, 'moveId': move_id}), 200


    @app.route('/api/move/run/<course_id>/<move_id>/status', methods=['GET'])
    def api_move_status(course_id, move_id):
        token = f"move:{course_id}:{move_id}"
        th = playback_threads.get(token)
        running = bool(th and th.is_alive())
        return jsonify({'courseId': course_id, 'moveId': move_id, 'running': running}), 200
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
        
    @app.route('/api/robot/start-recording', methods=['POST'])
    def api_start_recording():
        data = request.get_json(force=True) or {}
        rid = int(data.get('robotId'))
        start_t = float(data.get('startTime', 0.0))

        move = {
            'id': str(uuid.uuid4()),
            'robotId': rid,
            'startT': start_t,
            'endT': None,
            'entries': []
        }
        with state.lock:
            cs = state.course_state
        
            # record this new segment
            cs['moves'].append(move)
            # mark this robot as actively recording
            cs.setdefault('recording_robots', set()).add(rid)

            # turn on sampling if this is the first active robot
            if not cs.get('sampling'):
                cs['sampling'] = True
                # wall-clock base so t == start_t right now
                cs['sampling_start_time'] = time.time() - start_t

            # (optional) keep a last-known course_time for non-sampling display
            cs['course_time'] = start_t

        ep = config.ROBOT_ENDPOINTS[rid]
        set_mode(ep['ip'], 'reset')
        time.sleep(0.2)  # small settle for IMU zeroing
        set_mode(ep['ip'], 'record_start')
        return jsonify(move), 200


    @app.route('/api/robot/stop-recording', methods=['POST'])
    def api_stop_recording():
        data = request.get_json(force=True) or {}
        rid = int(data.get('robotId'))

        with state.lock:
            cs = state.course_state
            _clear_all_controller_selections_unlocked(state.play_state)
            # compute current t from wall-clock base (fallback to stored course_time)
            if cs.get('sampling') and 'sampling_start_time' in cs:
                t_now = round(time.time() - cs['sampling_start_time'], 3)
            else:
                t_now = float(cs.get('course_time', 0.0))

            # close the latest open move for this robot
            for move in reversed(cs.get('moves', [])):
                if move['robotId'] == rid and move.get('endT') is None:
                    move['endT'] = t_now
                    break

            # stop recording this robot
            cs.get('recording_robots', set()).discard(rid)

            # if no robots still recording, end sampling and clear base
            if not cs.get('recording_robots'):
                cs['sampling'] = False
                cs.pop('sampling_start_time', None)
                cs['course_time'] = t_now  # freeze display at final time

        ep = config.ROBOT_ENDPOINTS[rid]
        set_mode(ep['ip'], 'record_stop')
        return jsonify({'status': 'stopped'}), 200


        
    @app.route('/api/moves/<move_id>', methods=['DELETE'])
    def api_delete_move(move_id):
        with state.lock:
            ms = state.course_state['moves']
            state.course_state['moves'] = [m for m in ms if m['id'] != move_id]
        return jsonify({'status': 'deleted'}), 200
    
    @app.route('/api/course/save', methods=['POST'])
    def api_save_course():
        data = request.get_json(force=True) or {}
        cs = state.course_state
        if cs['current_course'] is None:
            return jsonify({'error': 'No active course'}), 400

        # Persist updated name/duration
        if 'name' in data:
            cs['current_course']['name'] = data['name']
        if 'duration' in data:
            cs['current_course']['duration'] = data['duration']

        # Write out moves
        filepath = os.path.join(config.RECORDINGS_DIR, f"{cs['current_course']['id']}.json")
        with open(filepath, 'w') as f:
            json.dump(cs['moves'], f, indent=2)

        # Append course metadata and update robot count
        if cs['current_course'] not in cs['courses']:
            cs['courses'].append(cs['current_course'])
        # count unique robots with moves
        cs['current_course']['robotCount'] = len({m['robotId'] for m in cs['moves']})
        
        cs['current_course']['moves'] = list(cs['moves'])
        
        save_courses(cs['courses'])

        # Reset recording state
        with state.lock:
            cs['recording_robots'].clear()
            cs['sampling'] = False
            cs['course_time'] = 0.0
            cs['moves'].clear()

        return jsonify({
            'filename': f"{cs['current_course']['id']}.json",
            'courseId': cs['current_course']['id']
        }), 200

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

    @app.route('/api/run/<course_id>/status', methods=['GET'])
    def api_run_status(course_id):
        """
        Returns whether the given course is currently playing.
        True if we still have a thread and it's alive; false otherwise.
        """
        thread = playback_threads.get(course_id)
        running = bool(thread and thread.is_alive())
        return jsonify({'courseId': course_id, 'running': running}), 200


    @app.route('/api/run/<course_id>', methods=['POST'])
    def api_run_course(course_id):
        data = request.get_json(silent=True) or {}
        course = utils.find_course(state.course_state['courses'], course_id)
        if not course:
            return jsonify({'error': 'Course not found.'}), 404

        # Load recorded moves
        filepath = os.path.join(config.RECORDINGS_DIR, f"{course_id}.json")
        try:
            with open(filepath, 'r') as f:
                moves = json.load(f)
        except FileNotFoundError:
            return jsonify({'error': 'Recording not found.'}), 404

        # --- NEW: per-move trim + reset marker 0.4s before trimmed start ---
        trimmed_moves = []
        reset_markers = []  # (t_reset, rid, {'action':'reset'})
        for move in moves:
            rid = move.get('robotId')
            ents = move.get('entries', []) or []
            # find first seq==0
            start_idx = _first_start_idx(ents, accept_seq=(0, 1))
            if start_idx is None:
                continue 
            m = dict(move)
            m['entries'] = ents[start_idx:]
            trimmed_moves.append(m)

            # reset marker 0.4s before first kept entry (min 0.0)
            try:
                t0 = float(m['entries'][0]['t'])
            except Exception:
                continue
            t_reset = max(0.0, t0 - 0.4)
            reset_markers.append((t_reset, rid, {'action': 'reset'}))
        moves = trimmed_moves
        # --------------------------------------------------------------------

        # Flatten and sort entries by recorded timestamp t
        entries = []
        # include reset markers
        entries.extend(reset_markers)

        for move in moves:
            rid = move['robotId']
            for entry in move.get('entries', []):
                t = entry.get('t')
                if t is None:
                    continue
                telem = entry.get('telemetry')
                entries.append((float(t), rid, telem))

        entries.sort(key=lambda e: e[0])

        if course_id in playback_threads and playback_threads[course_id].is_alive():
            return jsonify({'error': 'Course already running.'}), 400

        robots_in_run = sorted({rid for _, rid, _ in entries})
        first_robot = robots_in_run[0] if robots_in_run else None  # <-- needed

        # One-time reset + arm (kept)
        for rid in robots_in_run:
            ep = config.ROBOT_ENDPOINTS[rid]
            set_mode(ep['ip'], 'reset')
            time.sleep(0.1)
            set_mode(ep['ip'], 'play_start')
            time.sleep(0.05)

        stop_event = threading.Event()
        playback_stop_events[course_id] = stop_event

        def playback(stop_evt: threading.Event):
            completed_naturally = False
            try:
                start = time.time()
                total = len(entries)
                print(f"[Playback:{course_id}] started with {total} entries", flush=True)

                for idx, (t, rid, telem) in enumerate(entries, start=1):
                    if stop_evt.is_set():
                        print(f"[Playback:{course_id}] stopped at entry {idx}", flush=True)
                        break

                    scheduled = start + t
                    delay = scheduled - time.time()
                    print(f"[Playback:{course_id} {idx}/{total}] sleeping {delay:.3f}s …", flush=True)
                    if delay > 0:
                        time.sleep(delay)

                    ep = config.ROBOT_ENDPOINTS[rid]

                    if telem:
                        # NEW: action marker
                        if isinstance(telem, dict) and telem.get('action') == 'reset':
                            try:
                                set_mode(ep['ip'], 'reset')
                                print(f"[Playback:{course_id} {idx}/{total}] action reset → robot {rid}", flush=True)
                            except Exception as e:
                                print(f"[Playback:{course_id}] reset action failed: {e}", flush=True)
                            continue

                        # Normal drive packet
                        try:
                            s1_val = s2_val = None
                            if str(rid) in config.SERVO_BOTH_ROBOTS:
                                s1_val = telem.get('s1')
                                s2_val = telem.get('s2')
                            elif str(rid) in config.SERVO_S1_ROBOTS:
                                s1_val = telem.get('s1')
                            elif str(rid) in config.SERVO_S2_ROBOTS:
                                s2_val = telem.get('s2')
                                                    # Optional LED command (only if present in the log)
                            led_val = telem.get('l') if isinstance(telem, dict) and 'l' in telem else None

                            # Optional timestamp for smoother ramps
                            t_ms_val = telem.get('t_ms') if isinstance(telem, dict) and 't_ms' in telem else None
                            if rid == 9:
                                if led_val is not None:
                                    send_led_rid(ep['ip'], rid, led_val, t_ms=t_ms_val)
                                # skip drivep entirely for robot 9
                            elif rid == 10:
                                # --- primary target (same as default flow) ---
                                if led_val is not None:
                                    send_led_rid(ep['ip'], rid, led_val, t_ms=t_ms_val)
                                # --- fan out to extra targets for robot 10 ---
                                for tgt in config.FANOUT_EXTRA_TARGETS.get(10, []):
                                    try:
                                        if led_val is not None:
                                            send_led_rid(tgt['ip'], rid, led_val, t_ms=t_ms_val)
                                    except Exception as e:
                                        print(f"[Playback:{course_id}] fanout to {tgt['ip']} failed: {e}", flush=True)
                            else:
                                drivep(
                                    ep['ip'], rid,
                                    telem.get('g', 0),  telem.get('A', 0), telem.get('B', 0),
                                    telem.get('t', 0),  telem.get('s', 0),
                                    s1=s1_val, s2=s2_val, led=led_val, t_ms=t_ms_val
                                )
                            print(f"[Playback:{course_id} {idx}/{total}] sent {telem}", flush=True)
                        except Exception as e:
                            print(f"[Playback:{course_id}] ERROR: {e}", flush=True)
                else:
                    completed_naturally = True

                # Send play_stop to ALL robots that were in this run if we finished naturally
                if completed_naturally:
                    for rid_stop in robots_in_run:
                        try:
                            ep0 = config.ROBOT_ENDPOINTS[rid_stop]
                            set_mode(ep0['ip'], 'play_stop')
                            time.sleep(0.03)  # tiny stagger so we don't blast the NIC
                            print(f"[Playback:{course_id}] sent play_stop to robot {rid_stop}", flush=True)
                        except Exception as e:
                            print(f"[Playback:{course_id}] play_stop to robot {rid_stop} failed: {e}", flush=True)

            finally:
                # Cleanup always
                playback_stop_events.pop(course_id, None)
                playback_threads.pop(course_id, None)
                print(f"[Playback:{course_id}] thread exiting", flush=True)

        thread = threading.Thread(target=playback, args=(stop_event,), daemon=True)
        playback_threads[course_id] = thread
        thread.start()

        return jsonify({'status': 'Playback started', 'courseId': course_id}), 200




    
    @app.route('/api/stop/<course_id>', methods=['POST'])
    def api_stop_course(course_id):
        stop_event = playback_stop_events.get(course_id)
        thread     = playback_threads.get(course_id)

        if not stop_event or not thread:
            print(f"[Playback:{course_id}] stop requested but no running thread found", flush=True)
            return jsonify({'error': 'Course not running.'}), 400
    
        for rid, ep in config.ROBOT_ENDPOINTS.items():
            try:
                set_mode(ep['ip'], 'play_stop')
                time.sleep(0.02)
            except Exception:
                pass
            
        print(f"[Playback:{course_id}] stop requested → setting stop_event", flush=True)
        stop_event.set()

        # Give the thread a moment to notice and exit
        thread.join(timeout=0.1)

        if thread.is_alive():
            print(f"[Playback:{course_id}] WARNING: thread still alive after stop", flush=True)
        else:
            print(f"[Playback:{course_id}] confirmed stopped", flush=True)

        return jsonify({'status': 'Playback stopping', 'courseId': course_id}), 200

        
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
