#!/usr/bin/env python3
"""Offline tests for profile_metrics rendering. No network, no dependencies.

Run: python .github/scripts/test_profile_metrics.py
"""

from __future__ import annotations

import importlib.util
import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)  # profile_metrics imports calendar_time as a sibling

spec = importlib.util.spec_from_file_location("profile_metrics", os.path.join(SCRIPTS_DIR, "profile_metrics.py"))
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)

import calendar_time as ct  # noqa: E402  (imported after sys.path is prepared)

TZ = "America/Mexico_City"  # UTC-6, so a UTC hour maps to local hour - 6
failures: list[str] = []


def check(condition: bool, description: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {description}")
    if not condition:
        failures.append(description)


def only_bucket(stamps: list[str]) -> list[str]:
    """Bucket labels holding 100% of the commits."""
    return [line.split()[0] for line in pm.render_commit_rhythm(stamps, TZ) if "100.0%" in line]


# Bucket boundaries: morning 06-12, daytime 12-18, evening 18-24, night 00-06
# local time. Each pair below is the first and last UTC instant of the bucket.
for expected, stamps in {
    "morning": ["2026-07-15T12:00:00Z", "2026-07-15T17:59:00Z"],
    "daytime": ["2026-07-15T18:00:00Z", "2026-07-15T23:59:00Z"],
    "evening": ["2026-07-16T00:00:00Z", "2026-07-16T05:59:00Z"],
    "night": ["2026-07-15T06:00:00Z", "2026-07-15T11:59:00Z"],
}.items():
    check(only_bucket(stamps) == [expected], f"{expected} bucket covers its local window")

check(pm.render_commit_rhythm([], TZ) == [], "no commits renders no rhythm group")
check(bool(pm.render_commit_rhythm(["2026-07-15T18:00:00Z"], "Not/AZone")), "unknown timezone falls back to UTC")

rhythm = pm.render_commit_rhythm(["2026-07-15T18:00:00Z"] * 3 + ["2026-07-15T12:00:00Z"], TZ)
check(len(rhythm) == 4, "every bucket is rendered, including empty ones")
check(any("75.0%" in line for line in rhythm), "percentages are shares of the total")

check(pm.humanize(1_220_548_025) == "1.22B", "humanize renders billions")
check(pm.humanize(999) == "999", "humanize leaves small numbers alone")
check(pm.compact_duration(88221.9) == "24h 30m", "compact_duration renders hours and minutes")
check(pm.format_rows([]) == ["  no activity tracked"], "empty groups say so instead of rendering blank")
check(
    pm.format_rows([("a", "1"), ("long_label", "2")]) == ["  a           1", "  long_label  2"],
    "row labels are padded to a common width",
)


# --- calendar classification ---------------------------------------------

RULES = ct.load_rules()
ME = "me@example.com"  # fixture only; the real address lives in a secret


def event(summary: str, hours: float = 1.0, attendees: int = 3, **extra) -> dict:
    start = "2026-07-15T10:00:00-06:00"
    end = f"2026-07-15T{10 + int(hours):02d}:{int(hours % 1 * 60):02d}:00-06:00"
    people = [{"email": ME, "self": True, "responseStatus": "accepted"}]
    people += [{"email": f"other{i}@example.com"} for i in range(attendees - 1)]
    return {"summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end}, "attendees": people, **extra}


check(ct.classify(event("1:1 con backend"), RULES) == "lider_tech", "a 1:1 is leadership time")
check(ct.classify(event("Sprint planning"), RULES) == "lider_tech", "planning is leadership time")
check(ct.classify(event("Postmortem del incidente"), RULES) == "it_soporte", "a postmortem is support time")
check(ct.classify(event("Revisar accesos del proveedor"), RULES) == "it_soporte", "vendor access is support time")
check(ct.classify(event("Almuerzo"), RULES) is None, "ignored keywords are not counted")
check(ct.classify(event("Focus block", attendees=1), RULES) is None, "solo focus blocks are not counted")
check(
    ct.classify(event("Charla con cliente", attendees=4), RULES) == "lider_tech",
    "an unmatched multi-attendee meeting falls back to the default bucket",
)
check(ct.classify(event("Cafe", attendees=1), RULES) is None, "an unmatched solo event is not counted")

check(ct.event_duration_hours(event("x", hours=1.5)) == 1.5, "duration is measured from start to end")
check(
    ct.event_duration_hours({"start": {"date": "2026-07-15"}, "end": {"date": "2026-07-16"}}) == 0.0,
    "all-day events contribute no hours",
)

check(not ct.is_countable(event("x", status="cancelled"), ME), "cancelled events are skipped")
check(not ct.is_countable(event("x", transparency="transparent"), ME), "events marked free are skipped")
declined = event("x")
declined["attendees"][0]["responseStatus"] = "declined"
check(not ct.is_countable(declined, ME), "declined invitations are skipped")
check(ct.is_countable(event("x"), ME), "an accepted invitation is countable")

totals = ct.aggregate([event("1:1", hours=1), event("Outage", hours=2), event("Almuerzo", hours=1)], RULES, ME)
check(totals == {"lider_tech": 1.0, "it_soporte": 2.0}, "aggregate sums hours per bucket and drops the rest")

# --- time split rendering -------------------------------------------------

waka_month = {"categories": [{"name": "AI Coding", "total_seconds": 3600 * 60}, {"name": "Meeting", "total_seconds": 3600 * 9}]}
split = pm.render_time_split(waka_month, {"lider_tech": 14.0, "it_soporte": 7.0}, 28)
check(len(split) == 3, "all three buckets render when all have time")
check(split[0].strip().startswith("lider_tech"), "leadership is listed first")
check("3h 30m/week" in split[0], "leadership averages 14h over 4 weeks to 3h30m")
check("15h 00m/week" in split[1], "development averages 60h over 4 weeks to 15h")
check(
    all("meeting" not in line.lower() for line in split),
    "WakaTime meeting time is excluded from the development bucket",
)
check(pm.render_time_split({"categories": []}, {}, 28) == [], "no data renders no time_split group")
check(
    "1:1" not in "".join(split) and "backend" not in "".join(split),
    "rendered output carries no event titles",
)

print()
if failures:
    print(f"{len(failures)} failure(s)")
    sys.exit(1)
print("all tests passed")
