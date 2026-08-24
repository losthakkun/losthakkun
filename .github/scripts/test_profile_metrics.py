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

check(pm.text_bar(0) == "⬛" * 20, "an empty bar is all track")
check(pm.text_bar(100) == "🟦" * 20, "a full bar is all fill")
check(pm.text_bar(50) == "🟦" * 10 + "⬛" * 10, "half is half")
check(len(pm.text_bar(37)) == 20, "every bar is the same width, so the trailing column stays aligned")
check(
    "█" not in "".join(pm.render_commit_rhythm(["2026-07-15T18:00:00Z"], TZ)),
    "the rhythm group uses the same palette as the waka section, not the old ASCII bar",
)
check(
    any("1 commit " in line for line in pm.render_commit_rhythm(["2026-07-15T18:00:00Z"], TZ)),
    "a single commit is singular, padded to keep the column width",
)

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

# --- token exchange contract ----------------------------------------------
# Google's token endpoint answers 400 to a JSON body. access_token must hand
# the poster a mapping to be form-encoded, never a pre-serialized string, and
# the poster it is given must be the form one.

seen: dict = {}


def fake_post_form(url: str, form) -> dict:
    seen["url"] = url
    seen["form"] = form
    return {"access_token": "ya29.fake"}


token = ct.access_token("cid", "csecret", "1//refresh", fake_post_form)
check(token == "ya29.fake", "access_token returns the access token from the response")
check(isinstance(seen["form"], dict), "access_token passes a mapping, not a serialized body")
check(seen["form"].get("grant_type") == "refresh_token", "the refresh grant type is requested")
check(seen["form"].get("refresh_token") == "1//refresh", "the refresh token is forwarded")
check(seen["url"] == ct.TOKEN_ENDPOINT, "the request targets Google's token endpoint")
check(
    pm.post_form.__doc__ and "form-urlencoded" in pm.post_form.__doc__,
    "profile_metrics exposes a form poster for the token exchange",
)

# --- publication gate -----------------------------------------------------
# The gate must be checked before any credential lookup or network call, so a
# disabled group costs nothing and cannot fail the run.

for value in ("", "0", "false", "no"):
    os.environ["PUBLISH_TIME_SPLIT"] = value
    check(pm.build_time_split("irrelevant", TZ) == [], f"time_split stays unpublished for {value!r}")
os.environ["PUBLISH_TIME_SPLIT"] = "true"
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)
os.environ.pop("GOOGLE_REFRESH_TOKEN", None)
check(
    pm.build_time_split("irrelevant", TZ) == [],
    "an enabled gate without credentials still degrades instead of failing",
)
os.environ.pop("PUBLISH_TIME_SPLIT", None)

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

# --- derived statistics ---------------------------------------------------

check(pm.median([3]) == 3, "median of one value is that value")
check(pm.median([1, 2, 3, 4]) == 2.5, "median of an even count averages the middle pair")
check(pm.median([]) == 0.0, "median of nothing is zero instead of raising")

# --- agent leverage -------------------------------------------------------
# Leverage and context cost are ratios over data already fetched. They must
# stay silent on samples too small to mean anything rather than print a number
# that swings wildly day to day.

WAKA = {
    "categories": [{"name": "AI Coding", "total_seconds": 3600 * 10, "percent": 98.5}],
    "ai_sessions": 29,
    "ai_prompt_events_total": 100,
    "ai_additions": 10_000,
    "ai_deletions": 13,
    "ai_input_tokens": 5_000_000,
    "ai_output_tokens": 1_000_000,
    "languages": [{"name": "PHP", "total_seconds": 3600 * 6}],
}
agent_rows = dict(pm.render_agent_workflow({**WAKA, "ai_model_line_changes": {"Opus": 9000, "Haiku": 1000}}))
check(
    agent_rows["model_mix"] == "Opus 90% · Haiku 10% · main loop only",
    "the model mix says which layer it measures, since subagent routing is not attributed",
)

agent_rows = dict(pm.render_agent_workflow(WAKA))
check(agent_rows["leverage"] == "1,000 lines per agent hour · 100 lines per prompt", "leverage divides lines by agent hours and prompts")
check(agent_rows["context_cost"] == "500 tokens in per generated line", "context cost divides input tokens by generated lines")
check(
    "leverage" not in dict(pm.render_agent_workflow({**WAKA, "categories": [{"name": "AI Coding", "total_seconds": 600, "percent": 5}]})),
    "leverage stays silent below an hour of agent time",
)
check("context_cost" not in dict(pm.render_agent_workflow({**WAKA, "ai_additions": 0})), "context cost needs generated lines")

# --- delivery flow --------------------------------------------------------

PRS = [
    {"created_at": "2026-08-01T10:00:00Z", "merged_at": "2026-08-01T12:00:00Z", "size": 100},
    {"created_at": "2026-08-02T10:00:00Z", "merged_at": "2026-08-02T14:00:00Z", "size": 300},
    {"created_at": "2026-08-03T10:00:00Z", "merged_at": "2026-08-03T16:00:00Z", "size": 200},
]
flow = dict(pm.render_flow(PRS))
check(flow["pr_size"] == "median 200 lines per merged PR", "PR size is the median churn per merged PR")
check("lead_time" not in flow, "open-to-merge lead time is not published")
check(pm.render_flow([]) == [], "no merged PRs renders no flow rows")
check(
    pm.render_flow([{"created_at": "2026-08-01T10:00:00Z", "merged_at": None, "size": 10}]) == [],
    "an unmerged PR contributes no churn",
)

# 2026-08-01T05:00Z is 2026-07-31 locally in UTC-6, so these are two days.
check(
    pm.active_days_row(["2026-08-01T05:00:00Z", "2026-08-01T18:00:00Z"], TZ, 30) == ("active_days", "2 of 30 days"),
    "active days are counted as distinct local dates",
)
check(
    pm.active_days_row(["2026-08-01T18:00:00Z", "2026-08-01T19:00:00Z"], TZ, 30) == ("active_days", "1 of 30 days"),
    "two commits on the same local day count once",
)
check(pm.active_days_row([], TZ, 30) is None, "no commits renders no active_days row")

# --- waka bar recolor -----------------------------------------------------
# The upstream action only offers █░, ⣿⣀ and ⬛⬜. On a dark theme its ⬜ empty
# block is the loudest thing in the bar, which reads as an inverted gauge, so
# the filled half becomes blue and the empty half recedes.

RAW = "PHP  6 hrs  ⬛⬛⬜⬜⬜  39.26 %"
recolored = pm.recolor_bars(RAW)
check(recolored == "PHP  6 hrs  🟦🟦⬛⬛⬛  39.26 %", "filled blocks turn blue and empty blocks recede")
check(pm.recolor_bars(recolored) == recolored, "recoloring is idempotent, so a rerun cannot repaint the bar")
check(pm.recolor_bars("no bars here") == "no bars here", "text without bars is untouched")
check(len(recolored) == len(RAW), "the bar keeps its width, so column alignment survives")

SECTION = f"before\n<!--START_SECTION:waka-->\n{RAW}\n<!--END_SECTION:waka-->\nafter ⬜"
patched = pm.recolor_waka_section(SECTION)
check("🟦🟦⬛⬛⬛" in patched, "the waka section is recolored in place")
check(patched.endswith("after ⬜"), "content outside the markers is left alone")
check(pm.recolor_waka_section("no markers ⬜") == "no markers ⬜", "a README without the waka section is unchanged")

print()
if failures:
    print(f"{len(failures)} failure(s)")
    sys.exit(1)
print("all tests passed")
