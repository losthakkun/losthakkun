#!/usr/bin/env python3
"""Offline tests for profile_metrics rendering. No network, no dependencies.

Run: python .github/scripts/test_profile_metrics.py
"""

from __future__ import annotations

import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location(
    "profile_metrics", os.path.join(os.path.dirname(__file__), "profile_metrics.py")
)
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)

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

print()
if failures:
    print(f"{len(failures)} failure(s)")
    sys.exit(1)
print("all tests passed")
