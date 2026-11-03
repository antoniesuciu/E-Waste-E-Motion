"""Software checks: isolated storage, no joystick loops or real UDP traffic."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config
import state
import udp_manager


class ControlAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # app.py loads storage on import. Redirect it before that happens.
        cls.storage = tempfile.TemporaryDirectory()
        cls.paths = patch.multiple(
            config,
            COURSES_FILE=str(Path(cls.storage.name) / "courses.json"),
            RECORDINGS_DIR=str(Path(cls.storage.name) / "recordings"),
        )
        cls.paths.start()
        import app
        cls.module = app
        cls.initial_play = copy.deepcopy(state.play_state)
        cls.initial_course = copy.deepcopy(state.course_state)

    @classmethod
    def tearDownClass(cls):
        cls.paths.stop()
        cls.storage.cleanup()

    def setUp(self):
        state.play_state.clear()
        state.play_state.update(copy.deepcopy(self.initial_play))
        state.course_state.clear()
        state.course_state.update(copy.deepcopy(self.initial_course))
        Path(config.COURSES_FILE).write_text("[]")
        for path in Path(config.RECORDINGS_DIR).glob("*.json"):
            path.unlink()
        self.client = self.module.create_app().test_client()
        # Any unexpected network use fails the test.
        self.network = patch("socket.socket", side_effect=AssertionError("Unexpected socket"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_dashboard_template_and_robot_inventory(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/static/bundle.js", response.data)
        robots = self.client.get("/robots").get_json()
        self.assertEqual(robots["available"], config.ROBOT_IDS)
        self.assertEqual(robots["selected"], {"1": None, "2": None})

    def test_selection_transfers_robot_between_controllers(self):
        for cid in (1, 2):
            response = self.client.post("/select_robot", json={"controller": cid, "robot": 1})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["selected_map"], {"1": None, "2": 1})
        response = self.client.post("/select_robot", json={"controller": 2, "robot": None})
        self.assertEqual(response.get_json()["selected_map"], {"1": None, "2": None})

    def test_invalid_selection_does_not_change_state(self):
        before = copy.deepcopy(state.play_state)
        for payload in ({"controller": 3, "robot": 1}, {"controller": 1, "robot": 999}):
            self.assertEqual(self.client.post("/select_robot", json=payload).status_code, 400)
        self.assertEqual(state.play_state, before)

    def test_course_save_reload_edit_and_delete(self):
        response = self.client.post("/api/courses", json={"name": "Test cue", "duration": 30})
        self.assertEqual(response.status_code, 201)
        cid = response.get_json()["id"]
        # Model a captured segment, without starting the hardware recorder.
        state.course_state["moves"].append({
            "id": "test-move", "robotId": 1, "startT": 0.0, "endT": 0.1,
            "entries": [{"t": 0.0, "telemetry": {"r": 1, "seq": 0, "t": 0.5, "s": 0.0}}],
        })
        self.assertEqual(self.client.post("/api/course/save", json={"name": "Saved cue"}).status_code, 200)
        self.assertEqual(len(json.loads(Path(config.COURSES_FILE).read_text())), 1)
        response = self.client.post(f"/api/course/edit/{cid}/begin")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["moves"][0]["id"], "test-move")
        response = self.client.patch(f"/api/courses/{cid}", json={"name": "Renamed", "duration": "12.5"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["duration"], 12.5)
        self.assertEqual(self.client.get(f"/api/courses/{cid}").get_json()["name"], "Renamed")
        self.assertEqual(self.client.delete(f"/api/courses/{cid}").status_code, 200)
        self.assertEqual(self.client.get("/api/courses").get_json(), [])
        self.assertFalse((Path(config.RECORDINGS_DIR) / f"{cid}.json").exists())

    def test_event_stream_serializes_sets_and_controller_state(self):
        state.course_state["recording_robots"] = {1, 2}
        response = self.client.get("/stream", buffered=False)
        try:
            self.assertEqual(response.mimetype, "text/event-stream")
            frame = next(response.response).decode()
            payload = json.loads(frame.removeprefix("data: ").strip())
            self.assertEqual(set(payload["course"]["recording_robots"]), {1, 2})
            self.assertEqual(set(payload["play"]["controllers"]), {"1", "2"})
        finally:
            response.close()

    def test_archived_example_loads_into_editor(self):
        courses = json.loads((ROOT / "examples/courses.json").read_text())
        Path(config.COURSES_FILE).write_text(json.dumps(courses))
        for course in courses:
            cid = course["id"]
            recording = (ROOT / "examples/recordings" / f"{cid}.json").read_text()
            (Path(config.RECORDINGS_DIR) / f"{cid}.json").write_text(recording)
            response = self.client.post(f"/api/course/edit/{cid}/begin")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["moves"], json.loads(recording))


class UDPPayloadTest(unittest.TestCase):
    def test_playback_payload_preserves_optional_servo_and_light_fields(self):
        with patch.object(udp_manager.socket, "socket") as factory:
            udp_manager.drivep("192.0.2.1", 8, 2.5, 12, 14, 0.4, -0.2, s1=0.0, s2=1.0, led=5, t_ms=200)
        encoded, target = factory.return_value.sendto.call_args.args
        self.assertEqual(target, ("192.0.2.1", 12345))
        self.assertEqual(json.loads(encoded), {
            "r": 8, "g": 2.5, "A": 12, "B": 14, "t": 0.4, "s": -0.2,
            "s1": 0.0, "s2": 1.0, "l": 5, "t_ms": 200,
        })
        factory.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
