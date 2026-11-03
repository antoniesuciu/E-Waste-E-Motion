# Control-system architecture

This describes the archived source, before modernization.

## Runtime

`src/app.py` exposes a Flask app factory and a hardware entry point. Running it as a script starts a Pygame controller loop and UDP telemetry listeners, then Flask on `0.0.0.0:5000`. Calling the factory alone omits those threads.

`state.py` holds controller selections, telemetry, recording state, and course data in process-wide dictionaries guarded by a shared lock in many operations. Playback runs in per-course or per-move daemon threads with stop events. Use one server process; this state is not shared across workers.

`controller_thread.py` reads two Linux joystick paths. It applies deadzones, sends commands at a configured 10 Hz, and appends telemetry snapshots while recording. The browser chooses robot assignments; it does not read the physical controllers itself. The same robot can be assigned to only one controller at a time: selecting it on the other controller transfers the assignment.

`telemetry_thread.py` receives UDP JSON, checks the `r` field against configured robot IDs, and stores each robot's latest packet. `/stream` sends controller and course state to the browser approximately every 200 ms.

## Storage

Launch from `src/`: `COURSES_FILE` and `RECORDINGS_DIR` are working-directory-relative paths. Course metadata and embedded moves live in `../courses.json`; individual course recordings live in `../recordings/<course-id>.json`.

A course contains an ID, name, duration, creation timestamp, robot count, and moves. A move contains a robot ID, start/end times, and entries with a timestamp `t` and a telemetry snapshot. Some snapshots are `null` when no telemetry was available. Playback trims leading entries to a sequence marker when one is found.

The original example is stored separately under `examples/`. Root-level runtime data is ignored so rehearsals do not modify the preserved recording.

## Browser and build

The frontend uses React 19, React Router 6, Tailwind 4, Radix components, and Vite 5, with versions resolved by the archived npm lockfile. Routes cover the dashboard, live controller display, and course editor. API requests and event streams use the same origin as Flask.

Vite builds from `frontend/src/main.tsx` into root-level `static/`. Flask's template references fixed `bundle.js` and `style.css` names. The build does not empty its output directory, so obsolete output can accumulate locally. Generated assets are not tracked.

## Device protocol

Command packets are JSON over UDP, normally on port 12345. Telemetry is configured on port 12346. `udp_manager.py` encodes mode changes (`action`), drive/playback values (`r`, `t`, `s`, `g`, `A`, `B`), optional servo values (`s1`, `s2`), LED codes (`l`), and device timestamps (`t_ms`). The controller loop also has device-specific trigger and brightness fields.

Robot 9 has LED-only handling. Robot 10 has special lighting/brightness handling, with extra LED targets in `FANOUT_EXTRA_TARGETS`. Servo whitelists and joystick paths are in `src/config.py`. The root `config.json` is a preserved device configuration artifact; the current Python modules do not load it.

Firmware, electrical design, motor calibration, and physical network setup are not included. A configured robot ID is a software target, not evidence of a distinct physical robot in the production.

## Baseline limitations

These are source-level findings, not a claim that the archived production failed:

- **Robot lists differ.** Backend configuration has IDs 1–14; controller selection renders 1–15; the timeline renders tracks 1–10. Backend validation rejects ID 15.
- **Controller toggles are local UI state.** They do not disable the Pygame sender. Clearing a selection affects the backend assignment; a display toggle is not an emergency stop.
- **Telemetry listeners share ports.** Startup creates one listener per endpoint even when several endpoints use the same telemetry port. Their sockets use `SO_REUSEADDR`; this is not a single coordinated receiver.
- **Browser deep links lack a Flask fallback.** Navigate from `/`; refreshing a frontend route such as `/live` can return a server 404.
- **Thread stop timing is best-effort.** Playback uses sleeps between entries and short joins on stop requests. Stop responsiveness has not been measured on hardware.
- **Storage and state are local.** Relative paths, JSON writes, and process-global state assume one control host and one process. The archive does not provide a multi-user concurrency model.
- **Server settings are for a trusted network.** The hardware entry point enables Flask debug mode, binds all interfaces, and sets permissive CORS. There is no authentication layer.
- **No archived type-check setup.** Vite transpiles TypeScript without checking types. The ZIP contains no `tsconfig.json`; duplicate `.ts` and `.tsx` event-stream hooks are preserved.

Future changes should address these in separate commits with appropriate tests. This import deliberately preserves the working project's implementation.
