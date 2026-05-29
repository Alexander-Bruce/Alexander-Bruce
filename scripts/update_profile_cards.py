#!/usr/bin/env python3
"""Generate local SVG stat cards for the GitHub profile README."""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
USERNAME = os.environ.get("PROFILE_USERNAME", "Alexander-Bruce")
TOKEN = os.environ.get("GITHUB_TOKEN")
CARD_W = 390
CARD_H = 170


LANG_COLORS = {
    "Java": "#b07219",
    "C++": "#f34b7d",
    "Vue": "#41b883",
    "HTML": "#e34c26",
    "Python": "#3572A5",
    "JavaScript": "#f1e05a",
    "PowerShell": "#012456",
    "TypeScript": "#3178c6",
    "CSS": "#563d7c",
}

TYPE_COLORS = {
    "fix": "#cf222e",
    "feat": "#2da44e",
    "docs": "#0969da",
    "chore": "#bf8700",
    "style": "#8250df",
    "ci": "#1f883d",
    "test": "#fb8500",
    "refactor": "#6f42c1",
    "other": "#6e7781",
}

PROJECT_COLORS = ["#0969da", "#2da44e", "#8250df", "#bf8700", "#cf222e", "#6e7781"]


def request_json(url: str, *, method: str = "GET", body: dict | None = None) -> dict | list:
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required")

    data = None
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-card-generator",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub request failed: {exc.code} {detail}") from exc


def paged_rest(url: str) -> list[dict]:
    items: list[dict] = []
    page = 1
    joiner = "&" if "?" in url else "?"
    while True:
        batch = request_json(f"{url}{joiner}per_page=100&page={page}")
        if not isinstance(batch, list) or not batch:
            return items
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1


def graphql(query: str, variables: dict) -> dict:
    result = request_json(
        "https://api.github.com/graphql",
        method="POST",
        body={"query": query, "variables": variables},
    )
    if result.get("errors"):
        raise RuntimeError(json.dumps(result["errors"], indent=2))
    return result["data"]


def pct(value: float, total: float) -> float:
    return 0.0 if total <= 0 else value * 100.0 / total


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def progress_bar(x: int, y: int, width: int, value: float, max_value: float, color: str) -> str:
    filled = 0 if max_value <= 0 else max(6, round(width * value / max_value))
    filled = min(width, filled)
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="10" rx="5" fill="#eaeef2"/>'
        f'<rect x="{x}" y="{y}" width="{filled}" height="10" rx="5" fill="{color}"/>'
    )


def card(title: str, body: str, desc: str, gradient: bool = False) -> str:
    fill = 'fill="url(#bg)"' if gradient else 'fill="#ffffff"'
    defs = ""
    if gradient:
        defs = """
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="390" y2="170" gradientUnits="userSpaceOnUse">
      <stop stop-color="#f8fbff"/>
      <stop offset="1" stop-color="#f4fbf7"/>
    </linearGradient>
  </defs>"""
    return f"""<svg width="{CARD_W}" height="{CARD_H}" viewBox="0 0 {CARD_W} {CARD_H}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">{escape(title)}</title>
  <desc id="desc">{escape(desc)}</desc>{defs}
  <rect x="0.5" y="0.5" width="389" height="169" rx="10" {fill} stroke="#d0d7de"/>
  <text x="24" y="34" fill="#0969da" font-family="Segoe UI, Arial, sans-serif" font-size="18" font-weight="700">{escape(title)}</text>
{body}
</svg>
"""


def stacked_bar(items: list[tuple[str, float, str]], x: int = 24, y: int = 55, width: int = 342) -> str:
    parts = [f'<rect x="{x}" y="{y}" width="{width}" height="11" rx="5.5" fill="#eaeef2"/>']
    cursor = x
    for index, (_, percent, color) in enumerate(items):
        segment = round(width * percent / 100.0, 1)
        if segment <= 0:
            continue
        rx = ' rx="5.5"' if index == 0 else ""
        parts.append(f'<rect x="{cursor:.1f}" y="{y}" width="{segment:.1f}" height="11"{rx} fill="{color}"/>')
        cursor += segment
    return "\n    ".join(parts)


def collect_data() -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=365)
    query = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    login
    followers { totalCount }
    following { totalCount }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC) { totalCount }
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalRepositoryContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
      commitContributionsByRepository(maxRepositories: 20) {
        contributions { totalCount }
        repository { name nameWithOwner }
      }
      pullRequestContributionsByRepository(maxRepositories: 20) {
        contributions { totalCount }
        repository { name nameWithOwner }
      }
      pullRequestReviewContributionsByRepository(maxRepositories: 20) {
        contributions { totalCount }
        repository { name nameWithOwner }
      }
      issueContributionsByRepository(maxRepositories: 20) {
        contributions { totalCount }
        repository { name nameWithOwner }
      }
    }
  }
}
"""
    gql = graphql(
        query,
        {
            "login": USERNAME,
            "from": since.isoformat().replace("+00:00", "Z"),
            "to": now.isoformat().replace("+00:00", "Z"),
        },
    )["user"]

    repos = paged_rest(f"https://api.github.com/users/{USERNAME}/repos?type=owner&sort=updated")
    stars = sum(repo.get("stargazers_count", 0) for repo in repos)
    forks = sum(repo.get("forks_count", 0) for repo in repos)

    language_bytes: Counter[str] = Counter()
    for repo in repos:
        langs = request_json(repo["languages_url"])
        for language, byte_count in langs.items():
            language_bytes[language] += int(byte_count)

    commit_types: Counter[str] = Counter()
    commit_total = 0
    since_query = since.isoformat().replace("+00:00", "Z")
    for repo in repos:
        commits = paged_rest(
            f"https://api.github.com/repos/{USERNAME}/{repo['name']}/commits?since={since_query}"
        )
        for commit in commits:
            author = commit.get("author") or {}
            if author.get("login") and author.get("login") != USERNAME:
                continue
            message = commit["commit"]["message"].splitlines()[0]
            commit_types[classify_commit(message)] += 1
            commit_total += 1

    collection = gql["contributionsCollection"]
    days = [
        day
        for week in collection["contributionCalendar"]["weeks"]
        for day in week["contributionDays"]
    ]
    days.sort(key=lambda item: item["date"])
    streak = streak_stats(days)

    project_counts: Counter[str] = Counter()
    for key in [
        "commitContributionsByRepository",
        "pullRequestContributionsByRepository",
        "pullRequestReviewContributionsByRepository",
        "issueContributionsByRepository",
    ]:
        for item in collection[key]:
            name = item["repository"]["name"]
            project_counts[name] += int(item["contributions"]["totalCount"])

    return {
        "generated_at": now.date().isoformat(),
        "followers": gql["followers"]["totalCount"],
        "following": gql["following"]["totalCount"],
        "public_repos": gql["repositories"]["totalCount"],
        "stars": stars,
        "forks": forks,
        "contributions": collection["contributionCalendar"]["totalContributions"],
        "activity": {
            "Commits": collection["totalCommitContributions"],
            "Repositories": collection["totalRepositoryContributions"],
            "Pull requests": collection["totalPullRequestContributions"],
            "Reviews": collection["totalPullRequestReviewContributions"],
            "Issues": collection["totalIssueContributions"],
        },
        "streak": streak,
        "languages": language_bytes,
        "commit_types": commit_types,
        "commit_total": commit_total,
        "projects": project_counts,
    }


def classify_commit(message: str) -> str:
    conventional = re.match(r"^(feat|fix|docs|style|refactor|test|build|ci|perf|chore|merge|revert)(\(.+\))?:", message)
    if conventional:
        return conventional.group(1)
    lowered = message.lower()
    if lowered.startswith("merge"):
        return "merge"
    if re.search(r"\bfix\b|修复", lowered):
        return "fix"
    if re.search(r"\badd\b|新增|添加", lowered):
        return "feat"
    if re.search(r"readme|doc|文档", lowered):
        return "docs"
    if re.search(r"\bupdate\b|\bremove\b|更新|删除|改进", lowered):
        return "chore"
    return "other"


def streak_stats(days: list[dict]) -> dict:
    longest = 0
    longest_start = ""
    longest_end = ""
    run = 0
    run_start = ""
    active_days = 0

    for day in days:
        count = int(day["contributionCount"])
        if count > 0:
            active_days += 1
            if run == 0:
                run_start = day["date"]
            run += 1
            if run > longest:
                longest = run
                longest_start = run_start
                longest_end = day["date"]
        else:
            run = 0
            run_start = ""

    current = 0
    for day in reversed(days):
        if int(day["contributionCount"]) > 0:
            current += 1
        else:
            break

    last_active = next((day for day in reversed(days) if int(day["contributionCount"]) > 0), None)
    return {
        "current": current,
        "longest": longest,
        "active_days": active_days,
        "longest_start": longest_start,
        "longest_end": longest_end,
        "last_active": last_active["date"] if last_active else "",
        "last_active_count": int(last_active["contributionCount"]) if last_active else 0,
    }


def render_overview(data: dict) -> str:
    body = f"""  <text x="24" y="57" fill="#57606a" font-family="Segoe UI, Arial, sans-serif" font-size="12">Last 12 months</text>
  <g font-family="Segoe UI, Arial, sans-serif">
    <text x="24" y="102" fill="#24292f" font-size="34" font-weight="700">{data['contributions']}</text>
    <text x="24" y="124" fill="#57606a" font-size="13">contributions</text>
    <text x="170" y="92" fill="#57606a" font-size="13">Public repos</text>
    <text x="346" y="92" text-anchor="end" fill="#24292f" font-size="16" font-weight="700">{data['public_repos']}</text>
    <line x1="170" y1="105" x2="346" y2="105" stroke="#d8dee4"/>
    <text x="170" y="128" fill="#57606a" font-size="13">Stars / Forks</text>
    <text x="346" y="128" text-anchor="end" fill="#24292f" font-size="16" font-weight="700">{data['stars']} / {data['forks']}</text>
    <line x1="170" y1="141" x2="346" y2="141" stroke="#d8dee4"/>
    <text x="170" y="160" fill="#57606a" font-size="13">Followers</text>
    <text x="346" y="160" text-anchor="end" fill="#24292f" font-size="16" font-weight="700">{data['followers']}</text>
  </g>"""
    return card("GitHub Overview", body, "Overview of public GitHub activity.", gradient=True)


def render_streak(data: dict) -> str:
    streak = data["streak"]
    start = format_date(streak["longest_start"])
    end = format_date(streak["longest_end"])
    body = f"""  <g font-family="Segoe UI, Arial, sans-serif">
    <text x="24" y="92" fill="#24292f" font-size="34" font-weight="700">{streak['current']}</text>
    <text x="62" y="92" fill="#57606a" font-size="14">day current</text>
    <text x="24" y="120" fill="#57606a" font-size="13">Longest streak</text>
    <text x="346" y="120" text-anchor="end" fill="#24292f" font-size="16" font-weight="700">{streak['longest']} days</text>
    <text x="24" y="146" fill="#57606a" font-size="13">Active days</text>
    <text x="346" y="146" text-anchor="end" fill="#24292f" font-size="16" font-weight="700">{streak['active_days']}</text>
  </g>
  <g transform="translate(220 50)">
    <rect x="0" y="0" width="18" height="18" rx="4" fill="#dbeafe"/>
    <rect x="24" y="0" width="18" height="18" rx="4" fill="#bfdbfe"/>
    <rect x="48" y="0" width="18" height="18" rx="4" fill="#93c5fd"/>
    <rect x="72" y="0" width="18" height="18" rx="4" fill="#60a5fa"/>
    <rect x="96" y="0" width="18" height="18" rx="4" fill="#3b82f6"/>
    <rect x="120" y="0" width="18" height="18" rx="4" fill="#0969da"/>
    <text x="69" y="44" text-anchor="middle" fill="#57606a" font-family="Segoe UI, Arial, sans-serif" font-size="12">{escape(start)} - {escape(end)}</text>
  </g>"""
    return card("Contribution Streak", body, "Contribution streak metrics.")


def render_activity(data: dict) -> str:
    activity = data["activity"]
    rows = [
        ("Commits", activity["Commits"], "#0969da"),
        ("Repositories", activity["Repositories"], "#2da44e"),
        ("Pull requests", activity["Pull requests"], "#8250df"),
        ("Reviews", activity["Reviews"], "#bf8700"),
        ("Issues", activity["Issues"], "#cf222e"),
    ]
    max_value = max(value for _, value, _ in rows) or 1
    parts = ['  <g font-family="Segoe UI, Arial, sans-serif" font-size="12">']
    y = 62
    for label, value, color in rows:
        parts.append(f'    <text x="24" y="{y + 10}" fill="#24292f">{escape(label)}</text>')
        parts.append(f"    {progress_bar(118, y, 220, value, max_value, color)}")
        parts.append(f'    <text x="354" y="{y + 10}" text-anchor="end" fill="#57606a">{value}</text>')
        y += 21
    parts.append("  </g>")
    return card("Contribution Activity", "\n".join(parts), "Contribution activity by type.")


def render_commit_types(data: dict) -> str:
    counts = data["commit_types"]
    total = sum(counts.values()) or 1
    top = counts.most_common(7)
    segments = [(name, pct(value, total), TYPE_COLORS.get(name, "#6e7781")) for name, value in top]
    legend = []
    positions = [(29, 89), (149, 89), (279, 89), (29, 119), (149, 119), (279, 119), (29, 149)]
    for (name, value), (x, y) in zip(top, positions):
        color = TYPE_COLORS.get(name, "#6e7781")
        legend.append(
            f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>'
            f'<text x="{x + 14}" y="{y + 5}" fill="#24292f">{escape(name)}</text>'
            f'<text x="{x + 82}" y="{y + 5}" fill="#57606a">{value}</text>'
        )
    body = f"""  <g transform="translate(24 55)">
    {stacked_bar(segments, x=0, y=0, width=342)}
  </g>
  <g font-family="Segoe UI, Arial, sans-serif" font-size="13">
    {' '.join(legend)}
  </g>"""
    return card("Commit Types", body, "Commit message type distribution.")


def render_languages(data: dict) -> str:
    languages: Counter[str] = data["languages"]
    total = sum(languages.values()) or 1
    top = languages.most_common(6)
    segments = [
        (name, pct(value, total), LANG_COLORS.get(name, "#6e7781"))
        for name, value in top
    ]
    positions = [(28, 88), (212, 88), (28, 114), (212, 114), (28, 140), (212, 140)]
    legend = []
    for (name, value), (x, y) in zip(top, positions):
        color = LANG_COLORS.get(name, "#6e7781")
        percent = pct(value, total)
        value_x = 132 if x < 200 else 316
        legend.append(
            f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>'
            f'<text x="{x + 14}" y="{y + 5}" fill="#24292f">{escape(name)}</text>'
            f'<text x="{value_x}" y="{y + 5}" fill="#57606a">{percent:.1f}%</text>'
        )
    body = f"""  <g transform="translate(24 55)">
    {stacked_bar(segments, x=0, y=0, width=342)}
  </g>
  <g font-family="Segoe UI, Arial, sans-serif" font-size="13">
    {' '.join(legend)}
  </g>"""
    return card("Language Distribution", body, "Repository language distribution.")


def render_projects(data: dict) -> str:
    projects: Counter[str] = data["projects"]
    top = projects.most_common(4)
    top_total = sum(value for _, value in top)
    other = max(0, sum(projects.values()) - top_total)
    rows = [(name, value, PROJECT_COLORS[index]) for index, (name, value) in enumerate(top)]
    if other:
        rows.append(("other projects", other, PROJECT_COLORS[-1]))
    max_value = max((value for _, value, _ in rows), default=1)
    parts = ['  <g font-family="Segoe UI, Arial, sans-serif" font-size="12">']
    y = 57
    for name, value, color in rows[:5]:
        label = shorten(name)
        parts.append(f'    <text x="24" y="{y + 10}" fill="#24292f">{escape(label)}</text>')
        parts.append(f"    {progress_bar(150, y, 190, value, max_value, color)}")
        parts.append(f'    <text x="356" y="{y + 10}" text-anchor="end" fill="#57606a">{value}</text>')
        y += 24
    parts.append("  </g>")
    return card("Project Contributions", "\n".join(parts), "Contribution distribution by repository.")


def format_date(value: str) -> str:
    if not value:
        return "n/a"
    parsed = dt.date.fromisoformat(value)
    return parsed.strftime("%b %-d") if os.name != "nt" else parsed.strftime("%b %#d")


def shorten(value: str) -> str:
    aliases = {
        "resources-for-cs-student": "resources",
        "Alexander-Bruce": "profile",
    }
    value = aliases.get(value, value)
    return value if len(value) <= 16 else value[:15] + "..."


def write_files(data: dict) -> None:
    ASSETS.mkdir(exist_ok=True)
    files = {
        "overview.svg": render_overview(data),
        "streak.svg": render_streak(data),
        "activity.svg": render_activity(data),
        "commit-types.svg": render_commit_types(data),
        "languages.svg": render_languages(data),
        "projects.svg": render_projects(data),
    }
    for name, content in files.items():
        (ASSETS / name).write_text(content, encoding="utf-8", newline="\n")

    readme = """<div align="center">

### Alexander-Bruce

<img width="390" src="./assets/overview.svg" alt="GitHub overview" />
<img width="390" src="./assets/streak.svg" alt="Contribution streak" />

<br />

<img width="390" src="./assets/activity.svg" alt="Contribution activity mix" />
<img width="390" src="./assets/commit-types.svg" alt="Commit type distribution" />

<br />

<img width="390" src="./assets/languages.svg" alt="Language distribution" />
<img width="390" src="./assets/projects.svg" alt="Project contribution distribution" />

</div>
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8", newline="\n")


def main() -> int:
    data = collect_data()
    write_files(data)
    print(
        f"Updated profile cards for {USERNAME}: "
        f"{data['contributions']} contributions, "
        f"{data['commit_total']} scanned commits."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise
