"""
Unit tests for skills/classroom-poller/handler.py

All external calls (Google Classroom API, Google Calendar API, filesystem I/O)
are mocked — no real API keys are required.
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: add the skill directory to sys.path so handler can be imported.
# Use a module alias to avoid name-collision with receipt-to-sheets handler.
# ---------------------------------------------------------------------------
import importlib

SKILL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skills", "classroom-poller")
)

# Load classroom_poller_handler as a distinct module name so it never clashes
# with the receipt-to-sheets handler that test_receipt_to_sheets.py imports
# under the bare name "handler".
_spec = importlib.util.spec_from_file_location(
    "classroom_poller_handler",
    os.path.join(SKILL_DIR, "handler.py"),
)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)
sys.modules["classroom_poller_handler"] = handler


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_course(course_id="c1", name="Maths 101"):
    return {"id": course_id, "name": name}


def _make_assignment(
    assignment_id="a1",
    title="Homework 1",
    description="Solve problems 1-10",
    due_year=2026,
    due_month=6,
    due_day=15,
):
    a = {
        "id": assignment_id,
        "title": title,
        "description": description,
    }
    if due_year is not None:
        a["dueDate"] = {"year": due_year, "month": due_month, "day": due_day}
    return a


def _make_classroom_svc(courses=None, assignments=None):
    """
    Build a minimal mock Google Classroom service.

    The mock call chain for the Classroom API looks like:
      svc.courses().list(courseStates=[...]).execute()
      svc.courses().courseWork().list(courseId=...).execute()

    MagicMock chains every attribute access/call to a child mock, so we must
    carefully wire the two execute() endpoints.
    """
    courses = courses if courses is not None else [_make_course()]
    assignments = assignments if assignments is not None else [_make_assignment()]

    svc = MagicMock()

    # courses().list(...).execute() → {"courses": [...]}
    svc.courses.return_value.list.return_value.execute.return_value = {
        "courses": courses
    }

    # courses().courseWork().list(..., courseWorkStates=[...]).execute() → {"courseWork": [...]}
    svc.courses.return_value.courseWork.return_value.list.return_value.execute.return_value = {
        "courseWork": assignments
    }

    return svc


def _make_calendar_svc():
    """Build a minimal mock Google Calendar service."""
    svc = MagicMock()
    svc.events.return_value.insert.return_value.execute.return_value = {"id": "evt1"}
    return svc


# ---------------------------------------------------------------------------
# Tests: load_seen / save_seen round-trip
# ---------------------------------------------------------------------------

class TestLoadSaveSeen:
    def test_load_returns_empty_set_when_file_missing(self, tmp_path):
        path = str(tmp_path / "seen.json")
        result = handler.load_seen(path)
        assert result == set()

    def test_load_returns_correct_set_when_file_exists(self, tmp_path):
        path = tmp_path / "seen.json"
        path.write_text(json.dumps(["id1", "id2", "id3"]))
        result = handler.load_seen(str(path))
        assert result == {"id1", "id2", "id3"}

    def test_save_then_load_round_trip(self, tmp_path):
        path = str(tmp_path / "seen.json")
        original = {"abc", "def", "ghi"}
        handler.save_seen(original, path)
        loaded = handler.load_seen(path)
        assert loaded == original

    def test_save_creates_parent_directory(self, tmp_path):
        nested = tmp_path / "a" / "b" / "seen.json"
        handler.save_seen({"x"}, str(nested))
        assert nested.exists()
        assert json.loads(nested.read_text()) == ["x"]

    def test_load_returns_empty_set_on_corrupt_json(self, tmp_path):
        path = tmp_path / "seen.json"
        path.write_text("NOT VALID JSON {{{{")
        result = handler.load_seen(str(path))
        assert result == set()

    def test_save_writes_valid_json_list(self, tmp_path):
        path = tmp_path / "seen.json"
        handler.save_seen({"p", "q"}, str(path))
        raw = json.loads(path.read_text())
        assert isinstance(raw, list)
        assert set(raw) == {"p", "q"}


# ---------------------------------------------------------------------------
# Tests: _due_iso helper
# ---------------------------------------------------------------------------

class TestDueIso:
    def test_returns_iso_string_for_complete_due_date(self):
        cw = {"dueDate": {"year": 2026, "month": 6, "day": 5}}
        assert handler._due_iso(cw) == "2026-06-05"

    def test_returns_none_when_no_due_date_key(self):
        assert handler._due_iso({}) is None

    def test_returns_none_when_due_date_is_empty_dict(self):
        assert handler._due_iso({"dueDate": {}}) is None

    def test_returns_none_when_day_missing(self):
        cw = {"dueDate": {"year": 2026, "month": 6}}
        assert handler._due_iso(cw) is None

    def test_pads_month_and_day(self):
        cw = {"dueDate": {"year": 2026, "month": 1, "day": 3}}
        assert handler._due_iso(cw) == "2026-01-03"


# ---------------------------------------------------------------------------
# Tests: poll() — core business logic
# ---------------------------------------------------------------------------

class TestPoll:
    def test_new_assignment_triggers_notification(self):
        classroom_svc = _make_classroom_svc()
        calendar_svc = _make_calendar_svc()
        seen: set = set()

        notifications = handler.poll(classroom_svc, calendar_svc, seen)

        assert len(notifications) == 1
        assert "Homework 1" in notifications[0]
        assert "Maths 101" in notifications[0]

    def test_new_assignment_creates_calendar_event(self):
        classroom_svc = _make_classroom_svc()
        calendar_svc = _make_calendar_svc()
        seen: set = set()

        handler.poll(classroom_svc, calendar_svc, seen)

        # events().insert(calendarId=..., body=...) should have been called once
        insert_mock = calendar_svc.events.return_value.insert
        insert_mock.assert_called_once()
        call_kwargs = insert_mock.call_args[1]
        body = call_kwargs["body"]
        assert "Homework 1" in body["summary"]
        assert body["start"]["date"] == "2026-06-15"
        assert body["end"]["date"] == "2026-06-16"  # one day after start
        # 24h popup reminder
        assert body["reminders"]["useDefault"] is False
        overrides = body["reminders"]["overrides"]
        assert any(o["method"] == "popup" and o["minutes"] == 1440 for o in overrides)

    def test_already_seen_assignment_produces_no_notification(self):
        classroom_svc = _make_classroom_svc()
        calendar_svc = _make_calendar_svc()
        seen = {"a1"}  # already seen

        notifications = handler.poll(classroom_svc, calendar_svc, seen)

        assert notifications == []

    def test_already_seen_assignment_creates_no_calendar_event(self):
        classroom_svc = _make_classroom_svc()
        calendar_svc = _make_calendar_svc()
        seen = {"a1"}

        handler.poll(classroom_svc, calendar_svc, seen)

        calendar_svc.events.return_value.insert.assert_not_called()

    def test_assignment_with_no_due_date_sends_notification_no_calendar_event(self):
        """Assignment without dueDate: notification is produced but no Calendar event."""
        assignment = _make_assignment(
            assignment_id="a2",
            title="Essay Draft",
            description="Write a draft",
            due_year=None,
        )
        classroom_svc = _make_classroom_svc(assignments=[assignment])
        calendar_svc = _make_calendar_svc()
        seen: set = set()

        notifications = handler.poll(classroom_svc, calendar_svc, seen)

        assert len(notifications) == 1
        assert "Essay Draft" in notifications[0]
        assert "No due date" in notifications[0]
        calendar_svc.events.return_value.insert.assert_not_called()

    def test_assignment_id_added_to_seen_set(self):
        classroom_svc = _make_classroom_svc()
        calendar_svc = _make_calendar_svc()
        seen: set = set()

        handler.poll(classroom_svc, calendar_svc, seen)

        assert "a1" in seen

    def test_notification_includes_description_snippet(self):
        long_desc = "A" * 200
        assignment = _make_assignment(description=long_desc)
        classroom_svc = _make_classroom_svc(assignments=[assignment])
        calendar_svc = _make_calendar_svc()
        seen: set = set()

        notifications = handler.poll(classroom_svc, calendar_svc, seen)

        # Should truncate at 120 chars + "..."
        assert "A" * 120 in notifications[0]
        assert "..." in notifications[0]
        assert "A" * 200 not in notifications[0]

    def test_notification_short_description_not_truncated(self):
        short_desc = "Short desc"
        assignment = _make_assignment(description=short_desc)
        classroom_svc = _make_classroom_svc(assignments=[assignment])
        calendar_svc = _make_calendar_svc()
        seen: set = set()

        notifications = handler.poll(classroom_svc, calendar_svc, seen)

        assert "Short desc" in notifications[0]
        assert "..." not in notifications[0]

    def test_empty_list_when_no_new_assignments(self):
        classroom_svc = _make_classroom_svc()
        calendar_svc = _make_calendar_svc()
        seen = {"a1"}  # all assignments already seen

        notifications = handler.poll(classroom_svc, calendar_svc, seen)

        assert notifications == []

    def test_multiple_new_assignments_produce_multiple_notifications(self):
        assignments = [
            _make_assignment(assignment_id="x1", title="Task A"),
            _make_assignment(assignment_id="x2", title="Task B"),
        ]
        classroom_svc = _make_classroom_svc(assignments=assignments)
        calendar_svc = _make_calendar_svc()
        seen: set = set()

        notifications = handler.poll(classroom_svc, calendar_svc, seen)

        assert len(notifications) == 2
        titles = " ".join(notifications)
        assert "Task A" in titles
        assert "Task B" in titles

    def test_calendar_failure_does_not_suppress_notification(self):
        """If Calendar API raises, the notification must still be returned."""
        classroom_svc = _make_classroom_svc()
        calendar_svc = MagicMock()
        calendar_svc.events.return_value.insert.return_value.execute.side_effect = (
            Exception("API error")
        )
        seen: set = set()

        # Should not raise; notification should still be returned
        notifications = handler.poll(classroom_svc, calendar_svc, seen)

        assert len(notifications) == 1
        assert "Homework 1" in notifications[0]

    def test_no_courses_returns_empty_list(self):
        classroom_svc = _make_classroom_svc(courses=[], assignments=[])
        calendar_svc = _make_calendar_svc()
        seen: set = set()

        notifications = handler.poll(classroom_svc, calendar_svc, seen)

        assert notifications == []


# ---------------------------------------------------------------------------
# Tests: handle() — top-level entry point
# ---------------------------------------------------------------------------

class TestHandle:
    """
    handle() is tested by mocking get_classroom_service, get_calendar_service,
    load_seen, and save_seen at the module level.  This avoids wrestling with
    default-argument capture and filesystem state.
    """

    def _run_handle(self, initial_seen=None, assignments=None):
        """
        Run handle() with fully-mocked collaborators.

        Returns (notifications, save_seen_mock, saved_calls).
        """
        initial_seen = initial_seen if initial_seen is not None else set()
        courses = [_make_course()]
        assignments = assignments if assignments is not None else [_make_assignment()]

        classroom_svc = _make_classroom_svc(courses=courses, assignments=assignments)
        calendar_svc = _make_calendar_svc()

        save_mock = MagicMock()
        fake_creds = MagicMock()

        with patch.object(handler, "_get_credentials", return_value=fake_creds), \
             patch.object(handler, "get_classroom_service", return_value=classroom_svc), \
             patch.object(handler, "get_calendar_service", return_value=calendar_svc), \
             patch.object(handler, "load_seen", return_value=set(initial_seen)), \
             patch.object(handler, "save_seen", save_mock):
            result = handler.handle()

        return result, save_mock

    def test_handle_returns_list(self):
        result, _ = self._run_handle()
        assert isinstance(result, list)

    def test_handle_returns_notification_for_new_assignment(self):
        result, _ = self._run_handle()
        assert len(result) == 1
        assert "Homework 1" in result[0]

    def test_handle_returns_empty_list_when_nothing_new(self):
        result, _ = self._run_handle(initial_seen={"a1"})
        assert result == []

    def test_handle_calls_save_seen_with_updated_set(self):
        """handle() must call save_seen once with the assignment ID included."""
        _, save_mock = self._run_handle()

        save_mock.assert_called_once()
        saved_seen = save_mock.call_args[0][0]
        assert "a1" in saved_seen

    def test_handle_always_calls_save_seen_even_when_nothing_new(self):
        """save_seen is still called (to persist unchanged set), just no new IDs added."""
        _, save_mock = self._run_handle(initial_seen={"a1"})
        # save_seen is always called at the end of handle()
        save_mock.assert_called_once()

    def test_handle_accepts_none_context(self):
        """Cron invocations pass no context — handle(None) must not crash."""
        classroom_svc = _make_classroom_svc()
        calendar_svc = _make_calendar_svc()

        with patch.object(handler, "_get_credentials", return_value=MagicMock()), \
             patch.object(handler, "get_classroom_service", return_value=classroom_svc), \
             patch.object(handler, "get_calendar_service", return_value=calendar_svc), \
             patch.object(handler, "load_seen", return_value=set()), \
             patch.object(handler, "save_seen"):
            result = handler.handle(context=None)

        assert isinstance(result, list)

    def test_handle_with_no_assignments_returns_empty_list(self):
        result, _ = self._run_handle(assignments=[])
        assert result == []
