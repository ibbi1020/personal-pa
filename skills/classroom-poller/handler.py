"""
classroom-poller skill handler

Polls Google Classroom for new assignments every 15 minutes (cron-triggered).
For each new assignment:
  - Creates a Google Calendar all-day event on the due date with a 24h popup reminder
  - Returns a notification string for the PA to forward (e.g. via WhatsApp)

Persists seen assignment IDs to ~/.openclaw/seen_assignments.json to avoid
duplicate notifications across invocations.
"""

import json
import os
import sys
from datetime import date, timedelta
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

SEEN_PATH = os.path.expanduser("~/.openclaw/seen_assignments.json")


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def load_seen(path: str = SEEN_PATH) -> set:
    """Load the set of already-seen assignment IDs from disk."""
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return set(data)
    except FileNotFoundError:
        return set()
    except (json.JSONDecodeError, TypeError):
        return set()


def save_seen(seen: set, path: str = SEEN_PATH) -> None:
    """Persist the set of seen assignment IDs to disk."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(list(seen), fh)


# ---------------------------------------------------------------------------
# Google API service factories
# ---------------------------------------------------------------------------

def _get_credentials() -> Credentials:
    token_path = os.environ.get(
        "GOOGLE_CREDENTIALS_PATH",
        os.path.expanduser("~/.openclaw/google_token.json"),
    )
    return Credentials.from_authorized_user_file(token_path, SCOPES)


def get_classroom_service(creds=None):
    if creds is None:
        creds = _get_credentials()
    return build("classroom", "v1", credentials=creds)


def get_calendar_service(creds=None):
    if creds is None:
        creds = _get_credentials()
    return build("calendar", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# Calendar helper
# ---------------------------------------------------------------------------

def create_calendar_event(
    calendar_svc, title: str, course_name: str, description: str, due_iso: str
) -> None:
    """Create an all-day Google Calendar event with a 24h popup reminder."""
    end_date = (date.fromisoformat(due_iso) + timedelta(days=1)).isoformat()
    event = {
        "summary": f"📚 {title}",
        "description": f"Course: {course_name}\n\n{description}",
        "start": {"date": due_iso},
        "end": {"date": end_date},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 1440}],  # 24 h
        },
    }
    calendar_svc.events().insert(calendarId="primary", body=event).execute()


# ---------------------------------------------------------------------------
# Core polling logic
# ---------------------------------------------------------------------------

def _due_iso(coursework: dict) -> Optional[str]:
    """Return an ISO date string ('YYYY-MM-DD') for the assignment due date, or None."""
    due_date = coursework.get("dueDate")
    if not due_date:
        return None
    year = due_date.get("year")
    month = due_date.get("month")
    day = due_date.get("day")
    if not (year and month and day):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def poll(classroom_svc, calendar_svc, seen: set) -> list[str]:
    """
    Fetch all active courses and their courseWork.
    For each assignment not yet in *seen*:
      - Record its ID in seen
      - Optionally create a Calendar event (skipped if no due date)
      - Build and return a notification string
    Mutates *seen* in place and returns a list of notification strings.
    """
    notifications: list[str] = []

    # Paginate through all active courses
    courses_response = classroom_svc.courses().list(courseStates=["ACTIVE"]).execute()
    all_courses = courses_response.get("courses", [])
    while "nextPageToken" in courses_response:
        courses_response = classroom_svc.courses().list(
            courseStates=["ACTIVE"], pageToken=courses_response["nextPageToken"]
        ).execute()
        all_courses.extend(courses_response.get("courses", []))

    for course in all_courses:
        course_id = course["id"]
        course_name = course.get("name", "Unknown Course")

        # Paginate through all published courseWork for this course
        cw_response = (
            classroom_svc.courses()
            .courseWork()
            .list(courseId=course_id, courseWorkStates=["PUBLISHED"])
            .execute()
        )
        assignments = cw_response.get("courseWork", [])
        while "nextPageToken" in cw_response:
            cw_response = (
                classroom_svc.courses()
                .courseWork()
                .list(
                    courseId=course_id,
                    courseWorkStates=["PUBLISHED"],
                    pageToken=cw_response["nextPageToken"],
                )
                .execute()
            )
            assignments.extend(cw_response.get("courseWork", []))

        for assignment in assignments:
            assignment_id = assignment.get("id", "")
            if assignment_id in seen:
                continue

            # Mark as seen immediately so partial failures don't re-notify
            seen.add(assignment_id)

            title = assignment.get("title", "Untitled")
            description = assignment.get("description", "")
            due_iso = _due_iso(assignment)

            # --- Calendar event (only when there is a due date) ---
            if due_iso:
                try:
                    create_calendar_event(
                        calendar_svc, title, course_name, description, due_iso
                    )
                except Exception as exc:
                    print(
                        f"[classroom-poller] calendar event creation failed for '{title}': {exc}",
                        file=sys.stderr,
                    )

            # --- Build notification string ---
            due_str = due_iso if due_iso else "No due date"
            snippet = description[:120] + ("..." if len(description) > 120 else "")
            lines = [
                f"📚 New assignment: {title}",
                f"Course: {course_name}",
                f"Due: {due_str}",
            ]
            if snippet:
                lines.append(snippet)
            notification = "\n".join(lines)
            notifications.append(notification)

    return notifications


# ---------------------------------------------------------------------------
# OpenClaw entry point
# ---------------------------------------------------------------------------

def handle(context=None) -> list[str]:
    """
    Cron-triggered entry point.  `context` may be None or carry no user message.
    Returns a list of notification strings (empty when nothing new was found).
    """
    seen = load_seen()

    creds = _get_credentials()
    classroom_svc = get_classroom_service(creds)
    calendar_svc = get_calendar_service(creds)

    notifications = poll(classroom_svc, calendar_svc, seen)

    save_seen(seen)

    return notifications
