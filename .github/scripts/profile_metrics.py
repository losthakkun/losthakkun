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
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

README = os.path.join(os.path.dirname(__file__), "..", "..", "README.md")
START = "<!--START_SECTION:agent-impact-->"
END = "<!--END_SECTION:agent-impact-->"

WAKATIME_STATS = "https://wakatime.com/api/v1/users/current/stats/last_7_days"
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


def fetch_wakatime(api_key: str) -> dict[str, Any]:
    """Read the weekly stats aggregate.

    WakaTime builds this aggregate lazily: the first request after new
    heartbeats can answer without the breakdown lists. Retrying once returns
    the computed object, which is why the workflow also warms this endpoint up.
    """
    auth = base64.b64encode(api_key.encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    for _ in range(2):
        data = get_json(WAKATIME_STATS, headers).get("data", {})
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

    languages = waka.get("languages", [])[:4]
    if languages:
        rows.append(("top_surfaces", " · ".join(f"{lang['name']} {compact_duration(lang['total_seconds'])}" for lang in languages)))

    return rows


def search_count(token: str, query: str) -> int:
    payload = {
        "query": "query ($q: String!) { search(query: $q, type: ISSUE, first: 1) { issueCount } }",
        "variables": {"q": query},
    }
    body = post_json(GITHUB_GRAPHQL, payload, {"Authorization": f"bearer {token}"})
    return body["data"]["search"]["issueCount"]


def merged_pr_footprint(token: str, query: str) -> tuple[int, int, set[str]]:
    """Sum additions/deletions and count distinct repositories across merged PRs.

    Repository names are used only to size the footprint; they are never
    rendered, so private org repos stay private.
    """
    additions = deletions = 0
    repositories: set[str] = set()
    cursor: str | None = None

    for _ in range(6):  # up to 600 PRs, plenty for a 30-day window
        payload = {
            "query": """
              query ($q: String!, $cursor: String) {
                search(query: $q, type: ISSUE, first: 100, after: $cursor) {
                  nodes { ... on PullRequest { additions deletions repository { nameWithOwner } } }
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
            additions += node.get("additions") or 0
            deletions += node.get("deletions") or 0
            if node.get("repository"):
                repositories.add(node["repository"]["nameWithOwner"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    return additions, deletions, repositories


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
        bar = "█" * round(percent / 5) + "░" * (20 - round(percent / 5))
        lines.append(f"  {label.ljust(7)}  {window}  {f'{count:,}'.rjust(count_width)} commits  {bar}  {percent:4.1f}%")
    return lines


def render_delivery(token: str, login: str) -> tuple[list[tuple[str, str]], set[str], str]:
    since = (datetime.now(timezone.utc) - timedelta(days=DELIVERY_WINDOW_DAYS)).date().isoformat()
    now = datetime.now(timezone.utc)

    opened = search_count(token, f"is:pr author:{login} created:>={since}")
    merged = search_count(token, f"is:pr author:{login} is:merged merged:>={since}")
    reviewed = search_count(token, f"is:pr reviewed-by:{login} -author:{login} updated:>={since}")
    additions, deletions, repositories = merged_pr_footprint(
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
    waka: dict[str, Any], delivery: list[tuple[str, str]], rhythm: list[str], tz_name: str
) -> str:
    lines = ["```txt", "agent_workflow — last 7 days"]
    lines += format_rows(render_agent_workflow(waka))
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
    if updated == content:
        return False

    with open(README, "w", encoding="utf-8") as handle:
        handle.write(updated)
    return True


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
    rhythm = render_commit_rhythm(timestamps, tz_name)

    block = build_block(waka, delivery, rhythm, tz_name)

    if "--dry-run" in sys.argv:
        print(block)
        return 0

    print("README updated" if write_block(block) else "README already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
