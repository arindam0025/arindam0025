"""Fetch profile data from GitHub GraphQL, with an offline-safe no-data state.

Usage examples:
    GITHUB_TOKEN=... python scripts/fetch_github_data.py --username octocat
    python scripts/fetch_github_data.py --username octocat --offline --as-of 2026-01-01

Only the standard library is used. The cache never includes a token.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from common import (
    DEFAULT_CACHE_PATH,
    GITHUB_LEVELS,
    SCHEMA_VERSION,
    calendar_weeks,
    empty_calendar_days,
    fill_calendar_days,
    iso_date_range,
    latest_complete_utc_day,
    normalized_languages,
    parse_as_of,
    read_json,
    resolve_username,
    streaks,
    utc_timestamp,
    write_json,
)


GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

PROFILE_QUERY = """
query Profile($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    login
    name
    bio
    url
    avatarUrl
    createdAt
    followers { totalCount }
    following { totalCount }
    repositories(first: 1, privacy: PUBLIC, ownerAffiliations: OWNER) { totalCount }
    contributionCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            weekday
            contributionCount
            contributionLevel
          }
        }
      }
    }
  }
}
"""

PUBLIC_REPOSITORIES_QUERY = """
query PublicRepositories($login: String!, $after: String) {
  user(login: $login) {
    repositories(
      first: 100,
      after: $after,
      privacy: PUBLIC,
      ownerAffiliations: OWNER,
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        stargazerCount
        languages(first: 100, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
  }
}
"""


class GitHubAPIError(RuntimeError):
    """An API failure that should gracefully fall back rather than stop a build."""


def graphql(token: str, query: str, variables: Mapping[str, Any]) -> Dict[str, Any]:
    """Make one authenticated GitHub GraphQL request without leaking credentials."""

    payload = json.dumps({"query": query, "variables": dict(variables)}).encode("utf-8")
    request = Request(
        GITHUB_GRAPHQL_URL,
        data=payload,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-profile-svg-data-script",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise GitHubAPIError(f"GitHub API returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise GitHubAPIError("GitHub API could not be reached.") from exc
    except OSError as exc:
        raise GitHubAPIError("GitHub API request failed.") from exc

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise GitHubAPIError("GitHub API returned invalid JSON.") from exc
    if not isinstance(decoded, dict):
        raise GitHubAPIError("GitHub API returned an unexpected response.")

    errors = decoded.get("errors")
    if errors:
        messages = []
        if isinstance(errors, list):
            for error in errors[:2]:
                if isinstance(error, Mapping) and error.get("message"):
                    messages.append(str(error["message"]))
        detail = " ".join(messages) or "GitHub GraphQL reported an error."
        raise GitHubAPIError(detail)

    data = decoded.get("data")
    if not isinstance(data, dict):
        raise GitHubAPIError("GitHub GraphQL response contained no data.")
    return data


def graphql_datetime(value: date) -> str:
    """GitHub needs DateTime bounds; a midnight UTC boundary is deterministic."""

    return f"{value.isoformat()}T00:00:00Z"


def fetch_public_repositories(login: str, token: str) -> Tuple[int, Dict[str, Dict[str, Any]]]:
    """Aggregate every owned public repository's language bytes and stars.

    The GraphQL query deliberately constrains the selection to public,
    owner-affiliated repositories. Language ties are ordered later by name.
    """

    after: Optional[str] = None
    seen_cursors = set()
    total_stars = 0
    language_bytes: Dict[str, Dict[str, Any]] = {}

    while True:
        response = graphql(token, PUBLIC_REPOSITORIES_QUERY, {"login": login, "after": after})
        user = response.get("user")
        if not isinstance(user, Mapping):
            raise GitHubAPIError("GitHub user was not found.")
        repositories = user.get("repositories")
        if not isinstance(repositories, Mapping):
            raise GitHubAPIError("GitHub repository response was incomplete.")

        nodes = repositories.get("nodes")
        if not isinstance(nodes, list):
            nodes = []
        for repository in nodes:
            if not isinstance(repository, Mapping):
                continue
            try:
                total_stars += max(0, int(repository.get("stargazerCount") or 0))
            except (TypeError, ValueError):
                pass

            languages = repository.get("languages")
            edges = languages.get("edges") if isinstance(languages, Mapping) else []
            if not isinstance(edges, list):
                continue
            for edge in edges:
                if not isinstance(edge, Mapping):
                    continue
                node = edge.get("node")
                if not isinstance(node, Mapping) or not node.get("name"):
                    continue
                name = str(node["name"])
                try:
                    size = max(0, int(edge.get("size") or 0))
                except (TypeError, ValueError):
                    size = 0
                if size <= 0:
                    continue
                entry = language_bytes.setdefault(name, {"bytes": 0, "color": node.get("color")})
                entry["bytes"] = int(entry["bytes"]) + size
                # Prefer the first API colour, which is deterministic after the
                # query's update-time ordering, then canonicalise in common.py.
                if not entry.get("color") and node.get("color"):
                    entry["color"] = node.get("color")

        page_info = repositories.get("pageInfo")
        has_next = bool(page_info.get("hasNextPage")) if isinstance(page_info, Mapping) else False
        next_cursor = page_info.get("endCursor") if isinstance(page_info, Mapping) else None
        if not has_next:
            break
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
            raise GitHubAPIError("GitHub repository pagination did not advance.")
        seen_cursors.add(next_cursor)
        after = next_cursor

    return total_stars, language_bytes


def build_live_payload(login: str, token: str, start_date: date, end_date: date) -> Dict[str, Any]:
    """Fetch live profile, calendar, and public-language data."""

    end_exclusive = date.fromordinal(end_date.toordinal() + 1)
    profile_response = graphql(
        token,
        PROFILE_QUERY,
        {
            "login": login,
            "from": graphql_datetime(start_date),
            "to": graphql_datetime(end_exclusive),
        },
    )
    user = profile_response.get("user")
    if not isinstance(user, Mapping):
        raise GitHubAPIError("GitHub user was not found or is unavailable to this token.")

    collection = user.get("contributionCollection")
    calendar = collection.get("contributionCalendar") if isinstance(collection, Mapping) else None
    if not isinstance(calendar, Mapping):
        raise GitHubAPIError("GitHub contribution calendar response was incomplete.")

    sparse_days = []
    weeks = calendar.get("weeks")
    if isinstance(weeks, list):
        for week in weeks:
            contribution_days = week.get("contributionDays") if isinstance(week, Mapping) else []
            if not isinstance(contribution_days, list):
                continue
            for day in contribution_days:
                if not isinstance(day, Mapping):
                    continue
                level_name = str(day.get("contributionLevel") or "")
                sparse_days.append(
                    {
                        "date": day.get("date"),
                        "count": day.get("contributionCount", 0),
                        "level": GITHUB_LEVELS.get(level_name, -1),
                    }
                )

    daily = fill_calendar_days(sparse_days, start_date, end_date)
    current_streak, longest_streak = streaks(daily)
    total_stars, language_bytes = fetch_public_repositories(str(user.get("login") or login), token)
    repositories = user.get("repositories")
    try:
        public_repositories = max(0, int(repositories.get("totalCount") or 0)) if isinstance(repositories, Mapping) else 0
    except (TypeError, ValueError):
        public_repositories = 0

    def count_from(field: str) -> int:
        value = user.get(field)
        try:
            return max(0, int(value.get("totalCount") or 0)) if isinstance(value, Mapping) else 0
        except (TypeError, ValueError):
            return 0

    total_contributions = sum(item["count"] for item in daily)
    resolved_login = str(user.get("login") or login)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "live",
        "generated_at": utc_timestamp(),
        "notice": "Live GitHub GraphQL data.",
        "profile": {
            "login": resolved_login,
            "name": str(user.get("name") or resolved_login),
            "bio": str(user.get("bio") or ""),
            "url": str(user.get("url") or f"https://github.com/{resolved_login}"),
            "avatar_url": str(user.get("avatarUrl") or ""),
            "created_at": str(user.get("createdAt") or ""),
        },
        "calendar": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": daily,
            "weeks": calendar_weeks(daily, start_date, end_date),
            "total_contributions": total_contributions,
        },
        "stats": {
            "public_repositories": public_repositories,
            "followers": count_from("followers"),
            "following": count_from("following"),
            "total_stars": total_stars,
            "active_days": sum(1 for item in daily if item["count"] > 0),
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "languages": normalized_languages(language_bytes),
        },
    }


def build_fallback_payload(login: str, start_date: date, end_date: date, reason: str) -> Dict[str, Any]:
    """Build an explicit no-data payload when live data is unavailable.

    No contribution, repository, language, or social statistic is fabricated.
    """

    daily = empty_calendar_days(start_date, end_date)
    current_streak, longest_streak = streaks(daily)
    total_contributions = sum(item["count"] for item in daily)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "fallback",
        "generated_at": utc_timestamp(),
        "notice": f"No authenticated GitHub data yet — {reason}",
        "profile": {
            "login": login,
            "name": login,
            "bio": "",
            "url": f"https://github.com/{login}",
            "avatar_url": "",
            "created_at": "",
        },
        "calendar": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": daily,
            "weeks": calendar_weeks(daily, start_date, end_date),
            "total_contributions": total_contributions,
        },
        "stats": {
            "public_repositories": 0,
            "followers": 0,
            "following": 0,
            "total_stars": 0,
            "active_days": sum(1 for item in daily if item["count"] > 0),
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "languages": [],
        },
    }


def cache_matches(cache: Optional[Mapping[str, Any]], login: str, start_date: date, end_date: date) -> bool:
    """Ensure stale/malformed cache data is never shown for the wrong profile/range."""

    if not isinstance(cache, Mapping) or cache.get("schema_version") != SCHEMA_VERSION:
        return False
    profile = cache.get("profile")
    calendar = cache.get("calendar")
    if not isinstance(profile, Mapping) or not isinstance(calendar, Mapping):
        return False
    if str(profile.get("login") or "").casefold() != login.casefold():
        return False
    if calendar.get("start_date") != start_date.isoformat() or calendar.get("end_date") != end_date.isoformat():
        return False
    days = calendar.get("days")
    return isinstance(days, list) and len(days) == (end_date.toordinal() - start_date.toordinal() + 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch GitHub profile data for local SVG renderers.")
    parser.add_argument("--username", help="GitHub login. Defaults to GITHUB_USERNAME or GITHUB_REPOSITORY_OWNER.")
    parser.add_argument("--days", type=int, default=365, help="Inclusive contribution window (default: 365).")
    parser.add_argument("--as-of", help="UTC end date in YYYY-MM-DD form; useful for reproducible previews.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH, help="JSON cache output path.")
    parser.add_argument("--offline", action="store_true", help="Skip GitHub and write an explicit no-data state.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        end_date = parse_as_of(args.as_of) if args.as_of else latest_complete_utc_day()
        start_date, end_date = iso_date_range(args.days, end_date)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    cache = read_json(args.cache)
    try:
        login = resolve_username(args.username, cache)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    token = os.getenv("GITHUB_TOKEN", "").strip()
    data: Dict[str, Any]
    wrote_cache = False
    if args.offline:
        data = build_fallback_payload(login, start_date, end_date, "offline mode was requested")
        wrote_cache = True
        outcome = "generated explicit no-data state"
    elif token:
        try:
            data = build_live_payload(login, token, start_date, end_date)
            wrote_cache = True
            outcome = "fetched live GitHub data"
        except GitHubAPIError as exc:
            if cache_matches(cache, login, start_date, end_date):
                data = copy.deepcopy(dict(cache))
                outcome = f"kept compatible cache after API error ({exc})"
            else:
                data = build_fallback_payload(login, start_date, end_date, "GitHub data could not be fetched")
                wrote_cache = True
                outcome = f"generated no-data state after API error ({exc})"
    elif cache_matches(cache, login, start_date, end_date):
        data = copy.deepcopy(dict(cache))
        outcome = "kept compatible cache (GITHUB_TOKEN is not set)"
    else:
        data = build_fallback_payload(login, start_date, end_date, "GITHUB_TOKEN is not set")
        wrote_cache = True
        outcome = "generated no-data state (GITHUB_TOKEN is not set)"

    if wrote_cache:
        write_json(args.cache, data)
    print(f"{outcome}: {args.cache}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
