import os
import json
import uuid
import datetime

from config import COURSES_FILE, RECORDINGS_DIR

# --- Course Persistence ---
def load_courses():
    if os.path.exists(COURSES_FILE):
        try:
            with open(COURSES_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_courses(courses_list):
    with open(COURSES_FILE, 'w') as f:
        json.dump(courses_list, f, indent=2)


def find_course(courses_list, course_id):
    return next((c for c in courses_list if c['id'] == course_id), None)


def count_robots_with_segments(timelines):
    return sum(1 for seg in timelines.values() if isinstance(seg, list) and seg)


def ensure_recordings_dir():
    os.makedirs(RECORDINGS_DIR, exist_ok=True)


def create_course(name, duration):
    return {
        'id': str(uuid.uuid4()),
        'name': name,
        'duration': duration,
        'robotCount': 0,
        'createdAt': datetime.datetime.utcnow().isoformat() + 'Z',
        'moves': []
    }
