#!/usr/bin/env python3
"""Classify Google Calendar events into published activity buckets.

Only aggregated hours per bucket ever leave this module. Event titles,
attendees, and descriptions are read to classify and then discarded, so
nothing identifying reaches the public README.

Recurrence is expanded by Google (`singleEvents=true`) rather than here: a
locally written RRULE expander silently mishandles moved and cancelled
instances, and recurring 1:1s are exactly the time this metric is about.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Callable

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
EVENTS_ENDPOINT = "https://www.googleapis.com/calendar/v3/calendars/{calendar}/events"
RULES_PATH = os.path.join(os.path.dirname(__file__), "activity_rules.json")


def load_rules(path: str = RULES_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def event_duration_hours(event: dict[str, Any]) -> float:
    """Hours between start and end. All-day events return 0.

    All-day entries are holidays, PTO and travel markers, not time spent in an
    activity, so counting them would inflate every bucket they touch.
    """
    start = event.get("start", {}).get("dateTime")
    end = event.get("end", {}).get("dateTime")
    if not start or not end:
        return 0.0
    delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    return max(delta.total_seconds(), 0) / 3600


def is_countable(event: dict[str, Any], self_email: str) -> bool:
    """Whether the event represents time the user actually committed."""
    if event.get("status") == "cancelled":
        return False
    if event.get("transparency") == "transparent":  # marked free, not a commitment
        return False

    attendees = event.get("attendees") or []
    for attendee in attendees:
        if attendee.get("self") or attendee.get("email", "").lower() == self_email.lower():
            if attendee.get("responseStatus") == "declined":
                return False
    return True


def classify(event: dict[str, Any], rules: dict[str, Any]) -> str | None:
    """Return the bucket for an event, or None when it should not be counted."""
    summary = (event.get("summary") or "").lower()

    if any(word in summary for word in rules.get("ignore_keywords", [])):
        return None

    for bucket, config in rules.get("buckets", {}).items():
        if any(word in summary for word in config.get("keywords", [])):
            return bucket

    attendees = event.get("attendees") or []
    if len(attendees) >= rules.get("min_attendees_for_default", 2):
        return rules.get("default_bucket_for_meetings")

    return None


def aggregate(events: list[dict[str, Any]], rules: dict[str, Any], self_email: str) -> dict[str, float]:
    """Total hours per bucket across the given events."""
    totals: dict[str, float] = {bucket: 0.0 for bucket in rules.get("buckets", {})}
    for event in events:
        if not is_countable(event, self_email):
            continue
        bucket = classify(event, rules)
        if bucket is None:
            continue
        totals[bucket] = totals.get(bucket, 0.0) + event_duration_hours(event)
    return totals


def access_token(client_id: str, client_secret: str, refresh_token: str, post_json: Callable) -> str:
    payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    )
    body = post_json(TOKEN_ENDPOINT, payload, {"Content-Type": "application/x-www-form-urlencoded"})
    return body["access_token"]


def fetch_events(
    token: str, calendar: str, days: int, get_json: Callable, now: datetime
) -> list[dict[str, Any]]:
    """Page through the calendar with recurrences already expanded by Google."""
    events: list[dict[str, Any]] = []
    page_token: str | None = None
    base = EVENTS_ENDPOINT.format(calendar=urllib.parse.quote(calendar, safe=""))

    for _ in range(10):
        params = {
            "timeMin": (now - timedelta(days=days)).isoformat(),
            "timeMax": now.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "250",
            "eventTypes": "default",
        }
        if page_token:
            params["pageToken"] = page_token
        body = get_json(f"{base}?{urllib.parse.urlencode(params)}", {"Authorization": f"Bearer {token}"})
        events += body.get("items", [])
        page_token = body.get("nextPageToken")
        if not page_token:
            break

    return events
