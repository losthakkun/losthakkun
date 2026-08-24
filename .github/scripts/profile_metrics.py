#!/usr/bin/env python3
"""Render agent-workflow and delivery metrics into the profile README.

Data sources:
  - WakaTime  /users/current/stats/last_7_days  (AI-coding fields: sessions,
    prompts, generated lines, per-model line changes, language breakdown)
  - GitHub GraphQL search + contributionsCollection (aggregate delivery counts,
    private contributions included, repository names never published)

Usage:
  profile_metrics.py            # rewrite README.md between the markers
  profile_metrics.py --dry-run  # print the rendered block, touch nothing
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import calendar_time

README = os.path.join(os.path.dirname(__file__), "..", "..", "README.md")
START = "<!--START_SECTION:agent-impact-->"
END = "<!--END_SECTION:agent-impact-->"

WAKATIME_STATS = "https://wakatime.com/api/v1/users/current/stats/{range}"
GITHUB_GRAPHQL = "https://api.github.com/graphql"
DELIVERY_WINDOW_DAYS = 30
DEFAULT_TIMEZONE = "America/Mexico_City"
RETRYABLE_STATUS = frozenset({403, 408, 429, 499})


def request_json(request: urllib.request.Request, timeout: int, attempts: int = 4) -> dict:
    """Send a request, retrying transient transport failures with backoff.

    A scheduled job gets one shot per day, so a dropped connection must not
    silently blank the README.
    """
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError) as error:
            # 403/429 are GitHub's secondary rate limits, 499 comes from proxies
            # that drop the connection; everything else below 500 is our fault
            # and will not fix itself on a retry.
            if isinstance(error, urllib.error.HTTPError) and error.code not in RETRYABLE_STATUS and error.code < 500:
                raise
            last_error = error
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request to {request.full_url} failed after {attempts} attempts: {last_error}")


def post_json(url: str, payload: dict, headers: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={**headers, "Content-Type": "application/json"}
    )
    return request_json(request, timeout=30)


def post_form(url: str, form: dict) -> dict:
    """POST application/x-www-form-urlencoded. OAuth token endpoints require it."""
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return request_json(request, timeout=30)


def get_json(url: str, headers: dict) -> dict:
    return request_json(urllib.request.Request(url, headers=headers), timeout=60)


def humanize(count: int) -> str:
    """1220548025 -> '1.22B'. Keeps token counts readable in a fixed-width block."""
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if abs(count) >= limit:
            return f"{count / limit:.2f}".rstrip("0").rstrip(".") + suffix
    return str(count)


def compact_duration(seconds: float) -> str:
    """87865 -> '24h 24m'."""
    total_minutes = int(seconds // 60)
    return f"{total_minutes // 60}h {total_minutes % 60:02d}m"


def median(values: list[float]) -> float:
    """Median, or 0.0 for an empty sample.

    The median rather than the mean: one long-running PR left open over a
    weekend should not redefine the typical lead time.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def parse_timestamp(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def fetch_wakatime(api_key: str, stats_range: str = "last_7_days") -> dict[str, Any]:
    """Read a stats aggregate.

    WakaTime builds these aggregates lazily: the first request after new
    heartbeats can answer without the breakdown lists. Retrying once returns
    the computed object, which is why the workflow also warms this endpoint up.
    """
    auth = base64.b64encode(api_key.encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    url = WAKATIME_STATS.format(range=stats_range)
    for _ in range(2):
        data = get_json(url, headers).get("data", {})
        if data.get("languages"):
            return data
    return data


def render_agent_workflow(waka: dict[str, Any]) -> list[tuple[str, str]]:
    categories = {category["name"]: category for category in waka.get("categories", [])}
    ai_category = categories.get("AI Coding")

    rows: list[tuple[str, str]] = []

    sessions = waka.get("ai_sessions", 0)
    prompts = waka.get("ai_prompt_events_total", 0)
    prompt_length = waka.get("ai_prompt_length_avg", 0)
    if sessions or prompts:
        rows.append(
            ("sessions", f"{sessions} sessions · {prompts} prompts · {humanize(prompt_length)} chars per prompt")
        )

    if ai_category:
        rows.append(
            (
                "agent_time",
                f"{compact_duration(ai_category['total_seconds'])} ({ai_category['percent']}% of tracked time)",
            )
        )

    additions = waka.get("ai_additions", 0)
    deletions = waka.get("ai_deletions", 0)
    if additions or deletions:
        rows.append(("lines_generated", f"+{additions:,} / -{deletions:,}"))

    line_changes = waka.get("ai_model_line_changes", {})
    total_lines = sum(line_changes.values())
    if total_lines:
        ranked = sorted(line_changes.items(), key=lambda item: item[1], reverse=True)
        mix = " · ".join(f"{name} {value / total_lines * 100:.0f}%" for name, value in ranked if value / total_lines >= 0.01)
        rows.append(("model_mix", mix))

    tokens_in = waka.get("ai_input_tokens", 0)
    tokens_out = waka.get("ai_output_tokens", 0)
    if tokens_in or tokens_out:
        rows.append(("context_moved", f"{humanize(tokens_in)} tokens in · {humanize(tokens_out)} tokens out"))

    # Leverage is the metric that actually describes agent-first work: not how
    # much time went in, but how much shipped per unit of it. Both ratios stay
    # silent under an hour of agent time, where they swing too hard to mean
    # anything.
    agent_seconds = ai_category["total_seconds"] if ai_category else 0
    if additions and agent_seconds >= 3600:
        leverage = f"{additions / (agent_seconds / 3600):,.0f} lines per agent hour"
        if prompts:
            leverage += f" · {additions / prompts:,.0f} lines per prompt"
        rows.append(("leverage", leverage))

    if additions and tokens_in:
        rows.append(("context_cost", f"{tokens_in / additions:,.0f} tokens in per generated line"))

    languages = waka.get("languages", [])[:4]
    if languages:
        rows.append(("top_surfaces", " · ".join(f"{lang['name']} {compact_duration(lang['total_seconds'])}" for lang in languages)))

    return rows


def render_flow(prs: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Delivery flow over the merged PRs already fetched for the footprint.

    Batch size says how the work moves rather than how much of it there is,
    and it comes free from data the footprint query already returns.

    Open-to-merge lead time is deliberately not published. In an agentic
    workflow the review happens inside the loop, before the pull request
    exists, so the PR-to-merge span measures none of it — and a median of a
    couple of minutes invites exactly the wrong inference about whether the
    work was reviewed at all.
    """
    # An unmerged PR contributes nothing: its churn has not landed.
    shipped = [pr for pr in prs if pr.get("merged_at")]
    sizes = [pr["size"] for pr in shipped if pr.get("size")]

    if not sizes:
        return []
    return [("pr_size", f"median {median(sizes):,.0f} lines per merged PR")]


def active_days_row(timestamps: list[str], tz_name: str, days: int) -> tuple[str, str] | None:
    """Distinct local days carrying at least one commit.

    Consistency is worth publishing on its own: a month of steady delivery and
    a month with one enormous push produce the same commit count.
    """
    if not timestamps:
        return None
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc
    unique = {parse_timestamp(stamp).astimezone(tz).date() for stamp in timestamps}
    return ("active_days", f"{len(unique)} of {days} days")


def search_count(token: str, query: str) -> int:
    payload = {
        "query": "query ($q: String!) { search(query: $q, type: ISSUE, first: 1) { issueCount } }",
        "variables": {"q": query},
    }
    body = post_json(GITHUB_GRAPHQL, payload, {"Authorization": f"bearer {token}"})
    return body["data"]["search"]["issueCount"]


def merged_pr_footprint(token: str, query: str) -> tuple[int, int, set[str], list[dict[str, Any]]]:
    """Sum additions/deletions, count distinct repositories, and time each merged PR.

    Repository names are used only to size the footprint; they are never
    rendered, so private org repos stay private. createdAt/mergedAt ride along
    on the same query so flow metrics cost no extra requests.
    """
    additions = deletions = 0
    repositories: set[str] = set()
    prs: list[dict[str, Any]] = []
    cursor: str | None = None

    for _ in range(6):  # up to 600 PRs, plenty for a 30-day window
        payload = {
            "query": """
              query ($q: String!, $cursor: String) {
                search(query: $q, type: ISSUE, first: 100, after: $cursor) {
                  nodes {
                    ... on PullRequest {
                      additions
                      deletions
                      createdAt
                      mergedAt
                      repository { nameWithOwner }
                    }
                  }
                  pageInfo { hasNextPage endCursor }
                }
              }
            """,
            "variables": {"q": query, "cursor": cursor},
        }
        page = post_json(GITHUB_GRAPHQL, payload, {"Authorization": f"bearer {token}"})["data"]["search"]
        for node in page["nodes"]:
            if not node:
                continue
            node_additions = node.get("additions") or 0
            node_deletions = node.get("deletions") or 0
            additions += node_additions
            deletions += node_deletions
            if node.get("repository"):
                repositories.add(node["repository"]["nameWithOwner"])
            prs.append(
                {
                    "created_at": node.get("createdAt"),
                    "merged_at": node.get("mergedAt"),
                    "size": node_additions + node_deletions,
                }
            )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    return additions, deletions, repositories, prs


# The upstream waka-readme-stats action offers only █░, ⣿⣀ and ⬛⬜. On a dark
# theme the ⬜ empty block is the brightest thing in the row, so a bar at 3%
# reads as nearly full. Repainting the filled half blue and letting the empty
# half recede restores the gauge.
BAR_FILLED, BAR_EMPTY = "⬛", "⬜"
BAR_PALETTE = str.maketrans({BAR_FILLED: "🟦", BAR_EMPTY: "⬛"})
WAKA_SECTION = re.compile(
    r"(<!--START_SECTION:waka-->)(.*?)(<!--END_SECTION:waka-->)", re.DOTALL
)


def recolor_bars(text: str) -> str:
    """Repaint the action's progress bars, once.

    Guarded on the presence of the action's empty block: after a repaint none
    remains, so a rerun is a no-op. Without that guard the single-pass
    translation would repaint the already-recoloured empty blocks as filled
    ones and every bar would read 100%.
    """
    if BAR_EMPTY not in text:
        return text
    return text.translate(BAR_PALETTE)


TEXT_BAR_WIDTH = 20


def text_bar(percent: float, width: int = TEXT_BAR_WIDTH) -> str:
    """A progress bar in the same palette the waka section is repainted to.

    The groups this script renders and the group the upstream action renders sit
    a few lines apart in the README, so they have to speak the same visual
    language. All bars are the same width, which keeps the trailing percentage
    column aligned even though the blocks are wider than a monospace cell.
    """
    filled = round(percent / (100 / width))
    return "🟦" * filled + "⬛" * (width - filled)


def recolor_waka_section(content: str) -> str:
    """Apply the palette inside the waka markers and nowhere else.

    The action rewrites that section wholesale on every run, so this has to run
    after it — which is exactly where this script sits in the workflow.
    """
    return WAKA_SECTION.sub(lambda match: match[1] + recolor_bars(match[2]) + match[3], content)


def user_node_id(token: str, login: str) -> str:
    payload = {"query": "query ($login: String!) { user(login: $login) { id } }", "variables": {"login": login}}
    return post_json(GITHUB_GRAPHQL, payload, {"Authorization": f"bearer {token}"})["data"]["user"]["id"]


def commit_hours(token: str, author_id: str, repositories: set[str], since: str) -> list[str]:
    """Collect committedDate for the author's commits on each repo's default branch.

    Default-branch history is what actually shipped: squash and merge commits
    all land there, and unmerged branch work is deliberately excluded.
    """
    query = """
      query ($owner: String!, $name: String!, $author: ID!, $since: GitTimestamp!, $cursor: String) {
        repository(owner: $owner, name: $name) {
          defaultBranchRef {
            target {
              ... on Commit {
                history(author: {id: $author}, since: $since, first: 100, after: $cursor) {
                  nodes { committedDate }
                  pageInfo { hasNextPage endCursor }
                }
              }
            }
          }
        }
      }
    """
    timestamps: list[str] = []

    for repository in sorted(repositories):
        owner, _, name = repository.partition("/")
        cursor: str | None = None
        for _ in range(6):  # up to 600 commits per repository
            payload = {
                "query": query,
                "variables": {"owner": owner, "name": name, "author": author_id, "since": since, "cursor": cursor},
            }
            branch = post_json(GITHUB_GRAPHQL, payload, {"Authorization": f"bearer {token}"})["data"]["repository"][
                "defaultBranchRef"
            ]
            if not branch or not branch.get("target"):
                break
            history = branch["target"]["history"]
            timestamps += [node["committedDate"] for node in history["nodes"] if node]
            if not history["pageInfo"]["hasNextPage"]:
                break
            cursor = history["pageInfo"]["endCursor"]

    return timestamps


# Buckets match the convention used by waka-readme-stats, so the numbers stay
# comparable with the widely published version of this metric.
RHYTHM_BUCKETS = (("morning", "06-12"), ("daytime", "12-18"), ("evening", "18-24"), ("night", "00-06"))


def render_commit_rhythm(timestamps: list[str], tz_name: str) -> list[str]:
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc

    buckets = [0] * 4
    for stamp in timestamps:
        local_hour = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(tz).hour
        # 0-5 is night, which sits last in the rendered day, hence the shift.
        buckets[(local_hour // 6 - 1) % 4] += 1

    total = sum(buckets)
    if not total:
        return []

    count_width = max(len(f"{count:,}") for count in buckets)
    lines = []
    for (label, window), count in zip(RHYTHM_BUCKETS, buckets):
        percent = count / total * 100
        # Padded so a single commit reads correctly without shifting the column.
        noun = "commit " if count == 1 else "commits"
        lines.append(
            f"  {label.ljust(7)}  {window}  {f'{count:,}'.rjust(count_width)} {noun}  {text_bar(percent)}  {percent:4.1f}%"
        )
    return lines


# WakaTime categories that describe leadership or support work rather than
# building. They are excluded from the development bucket so that heartbeats
# sent with `--category meeting` can never inflate it.
NON_DEV_WAKA_CATEGORIES = frozenset(
    {"meeting", "planning", "advising", "communicating", "supporting", "code reviewing", "learning"}
)


def development_hours(waka: dict[str, Any]) -> float:
    return (
        sum(
            category["total_seconds"]
            for category in waka.get("categories", [])
            if category["name"].lower() not in NON_DEV_WAKA_CATEGORIES
        )
        / 3600
    )


def render_time_split(waka: dict[str, Any], calendar_totals: dict[str, float], days: int) -> list[str]:
    """Weekly average hours per activity bucket.

    Development comes from WakaTime (measured at the keyboard), leadership and
    support from the calendar. The two sources can overlap when a meeting runs
    while an agent is working, so these are shares of attention, not a
    partition of the day — the group header says weekly average for that reason.
    """
    hours = {"desarrollo": development_hours(waka), **calendar_totals}
    hours = {bucket: value for bucket, value in hours.items() if value > 0}
    if not hours:
        return []

    weeks = days / 7
    total = sum(hours.values())
    order = ["lider_tech", "desarrollo", "it_soporte"]
    ranked = sorted(hours.items(), key=lambda item: order.index(item[0]) if item[0] in order else len(order))

    label_width = max(len(bucket) for bucket, _ in ranked)
    weekly = {bucket: value / weeks for bucket, value in ranked}
    value_width = max(len(f"{int(value)}h {int(value % 1 * 60):02d}m") for value in weekly.values())

    lines = []
    for bucket, value in ranked:
        per_week = weekly[bucket]
        percent = value / total * 100
        rendered = f"{int(per_week)}h {int(per_week % 1 * 60):02d}m".rjust(value_width)
        lines.append(f"  {bucket.ljust(label_width)}  {rendered}/week  {text_bar(percent)}  {percent:4.1f}%")
    return lines


def render_delivery(token: str, login: str) -> tuple[list[tuple[str, str]], set[str], str]:
    since = (datetime.now(timezone.utc) - timedelta(days=DELIVERY_WINDOW_DAYS)).date().isoformat()
    now = datetime.now(timezone.utc)

    opened = search_count(token, f"is:pr author:{login} created:>={since}")
    merged = search_count(token, f"is:pr author:{login} is:merged merged:>={since}")
    reviewed = search_count(token, f"is:pr reviewed-by:{login} -author:{login} updated:>={since}")
    additions, deletions, repositories, prs = merged_pr_footprint(
        token, f"is:pr author:{login} is:merged merged:>={since}"
    )

    payload = {
        "query": """
          query ($login: String!, $from: DateTime!, $to: DateTime!) {
            user(login: $login) {
              contributionsCollection(from: $from, to: $to) {
                totalCommitContributions
                restrictedContributionsCount
              }
            }
          }
        """,
        "variables": {
            "login": login,
            "from": (now - timedelta(days=DELIVERY_WINDOW_DAYS)).isoformat(),
            "to": now.isoformat(),
        },
    }
    contributions = post_json(GITHUB_GRAPHQL, payload, {"Authorization": f"bearer {token}"})["data"]["user"][
        "contributionsCollection"
    ]
    total_contributions = (
        contributions["totalCommitContributions"] + contributions["restrictedContributionsCount"]
    )

    rows: list[tuple[str, str]] = []
    if opened:
        rows.append(("prs_opened", str(opened)))
    if merged:
        merge_rate = f" ({merged / opened * 100:.0f}% of opened)" if opened else ""
        rows.append(("prs_merged", f"{merged}{merge_rate}"))
    rows += render_flow(prs)
    if additions or deletions:
        rows.append(("lines_shipped", f"+{additions:,} / -{deletions:,}"))
    if repositories:
        rows.append(("active_repos", str(len(repositories))))
    if reviewed:
        rows.append(("reviews_given", str(reviewed)))
    if total_contributions:
        rows.append(("contributions", f"{total_contributions:,} (private included)"))

    return rows, repositories, since


def format_rows(rows: list[tuple[str, str]]) -> list[str]:
    if not rows:
        return ["  no activity tracked"]
    width = max(len(label) for label, _ in rows)
    return [f"  {label.ljust(width)}  {value}" for label, value in rows]


def build_block(
    waka: dict[str, Any],
    delivery: list[tuple[str, str]],
    rhythm: list[str],
    time_split: list[str],
    tz_name: str,
) -> str:
    lines = ["```txt", "agent_workflow — last 7 days"]
    lines += format_rows(render_agent_workflow(waka))
    if time_split:
        lines += ["", f"time_split — last {DELIVERY_WINDOW_DAYS} days · weekly average"]
        lines += time_split
    lines += ["", f"delivery — last {DELIVERY_WINDOW_DAYS} days"]
    lines += format_rows(delivery)
    if rhythm:
        lines += ["", f"commit_rhythm — last {DELIVERY_WINDOW_DAYS} days · {tz_name}"]
        lines += rhythm
    lines += ["```", "", f"_Updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"]
    return "\n".join(lines)


def write_block(block: str) -> bool:
    with open(README, encoding="utf-8") as handle:
        content = handle.read()

    pattern = re.compile(f"{re.escape(START)}.*?{re.escape(END)}", re.DOTALL)
    if not pattern.search(content):
        raise SystemExit(f"markers {START} / {END} not found in README.md")

    updated = pattern.sub(f"{START}\n{block}\n{END}", content)
    # The waka action ran earlier in the same job and rewrote its own section
    # with the upstream palette, so repaint it while the file is already open.
    updated = recolor_waka_section(updated)
    if updated == content:
        return False

    with open(README, "w", encoding="utf-8") as handle:
        handle.write(updated)
    return True


def build_time_split(wakatime_key: str, tz_name: str) -> list[str]:
    """Render the activity split, or nothing at all when the calendar is not wired up.

    A missing calendar credential is a normal state, not a failure: the rest of
    the metrics must keep publishing on the daily schedule either way.
    """
    if os.environ.get("PUBLISH_TIME_SPLIT", "").strip().lower() not in {"1", "true", "yes"}:
        # Held back on purpose. Calendar hours and keyboard hours are not
        # commensurable: the percentages imply a partition of the working day
        # that neither source measures, which read as under-reporting the
        # leadership work that happens in reviews rather than in meetings.
        # Credentials stay configured; flip the PUBLISH_TIME_SPLIT variable to
        # publish once the remaining sources are settled.
        print("time_split disabled (PUBLISH_TIME_SPLIT is not set)", file=sys.stderr)
        return []

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
    self_email = os.environ.get("GOOGLE_CALENDAR_EMAIL", "")
    calendar = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

    if not (client_id and client_secret and refresh_token):
        print("calendar credentials absent, skipping time_split", file=sys.stderr)
        return []

    try:
        waka_month = fetch_wakatime(wakatime_key, "last_30_days")
        token = calendar_time.access_token(client_id, client_secret, refresh_token, post_form)
        now = datetime.now(ZoneInfo(tz_name) if tz_name else timezone.utc)
        events = calendar_time.fetch_events(token, calendar, DELIVERY_WINDOW_DAYS, get_json, now)
        totals = calendar_time.aggregate(events, calendar_time.load_rules(), self_email)
        print(f"classified {len(events)} calendar events", file=sys.stderr)
        return render_time_split(waka_month, totals, DELIVERY_WINDOW_DAYS)
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, RuntimeError) as error:
        print(f"calendar lookup failed, skipping time_split: {error}", file=sys.stderr)
        return []


def main() -> int:
    wakatime_key = os.environ.get("WAKATIME_API_KEY")
    github_token = os.environ.get("GH_TOKEN")
    login = os.environ.get("GH_LOGIN", "losthakkun")

    if not wakatime_key or not github_token:
        raise SystemExit("WAKATIME_API_KEY and GH_TOKEN are required")

    try:
        waka = fetch_wakatime(wakatime_key)
    except urllib.error.HTTPError as error:
        print(f"wakatime request failed: {error}", file=sys.stderr)
        waka = {}

    delivery, repositories, since = render_delivery(github_token, login)

    tz_name = waka.get("timezone") or DEFAULT_TIMEZONE
    timestamps = commit_hours(
        github_token, user_node_id(github_token, login), repositories, f"{since}T00:00:00Z"
    )
    cadence = active_days_row(timestamps, tz_name, DELIVERY_WINDOW_DAYS)
    if cadence:
        delivery.append(cadence)

    rhythm = render_commit_rhythm(timestamps, tz_name)
    time_split = build_time_split(wakatime_key, tz_name)

    block = build_block(waka, delivery, rhythm, time_split, tz_name)

    if "--dry-run" in sys.argv:
        print(block)
        return 0

    print("README updated" if write_block(block) else "README already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
