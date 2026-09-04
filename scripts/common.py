"""Shared helpers for the GitHub profile data and SVG renderers.

The scripts deliberately use only Python's standard library so they run both
locally and in a minimal GitHub Actions runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"
DEFAULT_CACHE_PATH = DATA_DIR / "github-data.json"
DEFAULT_CONTRIBUTIONS_SVG = ASSETS_DIR / "contributions.svg"
DEFAULT_STATS_SVG = ASSETS_DIR / "stats.svg"
SCHEMA_VERSION = 1

GITHUB_USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")

GITHUB_LEVELS = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

FALLBACK_LANGUAGE_COLORS = {
    "Python": "#3572A5",
    "TypeScript": "#3178C6",
    "JavaScript": "#F1E05A",
    "Jupyter Notebook": "#DA5B0B",
    "HTML": "#E34C26",
    "CSS": "#563D7C",
    "Shell": "#89E051",
    "Go": "#00ADD8",
    "Rust": "#DEA584",
    "Java": "#B07219",
}


def ensure_project_dirs() -> None:
    """Create output directories if needed."""

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def utc_today() -> date:
    """Return the current calendar date in UTC (not the runner's local zone)."""

    return datetime.now(timezone.utc).date()


def latest_complete_utc_day() -> date:
    """Return yesterday, the latest full UTC contribution day.

    GitHub updates today's square while the day is still in progress. Using the
    preceding date keeps the scheduled SVG deterministic within a UTC day.
    """

    return date.fromordinal(utc_today().toordinal() - 1)


def utc_timestamp() -> str:
    """Return a compact, unambiguous timestamp for cache metadata."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_as_of(value: Optional[str]) -> date:
    """Parse an optional ISO date, falling back to today's UTC date."""

    if not value:
        return utc_today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("--as-of must use YYYY-MM-DD") from exc


def normalize_username(value: Optional[str]) -> Optional[str]:
    """Return a safe GitHub login, or ``None`` for an empty value."""

    if not value:
        return None
    login = value.strip().lstrip("@")
    if not login:
        return None
    if not GITHUB_USERNAME_RE.fullmatch(login):
        raise ValueError("GitHub usernames may contain letters, numbers, and single hyphens only")
    return login


def resolve_username(explicit: Optional[str], cached: Optional[Mapping[str, Any]] = None) -> str:
    """Find the intended profile owner without baking a username into the repo."""

    candidates: List[Optional[str]] = [
        explicit,
        os.getenv("GITHUB_USERNAME"),
        os.getenv("GH_USERNAME"),
        os.getenv("GITHUB_REPOSITORY_OWNER"),
    ]
    if cached:
        profile = cached.get("profile")
        if isinstance(profile, Mapping):
            candidates.append(str(profile.get("login") or ""))

    for candidate in candidates:
        normalized = normalize_username(candidate)
        if normalized:
            return normalized
    return "your-github"


def iso_date_range(days: int, end_date: date) -> Tuple[date, date]:
    """Return an inclusive, exact-length UTC date range."""

    if days < 1:
        raise ValueError("--days must be at least 1")
    start_date = date.fromordinal(end_date.toordinal() - days + 1)
    return start_date, end_date


def canonical_color(value: Optional[str], language_name: str = "") -> str:
    """Use an API language colour when valid, otherwise choose a stable colour."""

    if isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return value.upper()
    if language_name in FALLBACK_LANGUAGE_COLORS:
        return FALLBACK_LANGUAGE_COLORS[language_name]
    palette = ("#39D353", "#58A6FF", "#F778BA", "#D2A8FF", "#F2CC60", "#79C0FF", "#FF7B72")
    digest = hashlib.sha256(language_name.encode("utf-8")).digest()
    return palette[digest[0] % len(palette)]


def contribution_level(count: int, positive_counts: Sequence[int]) -> int:
    """Map a count to a reproducible 0–4 colour level.

    GitHub supplies contribution levels for live data. This is used for the
    offline preview and for malformed/missing API values.
    """

    if count <= 0:
        return 0
    ordered = sorted(max(1, int(item)) for item in positive_counts if int(item) > 0)
    if not ordered:
        return 1
    length = len(ordered)
    # Quantile positions are deterministic even where many counts tie.
    q1 = ordered[min(length - 1, (length - 1) // 4)]
    q2 = ordered[min(length - 1, ((length - 1) * 2) // 4)]
    q3 = ordered[min(length - 1, ((length - 1) * 3) // 4)]
    if count <= q1:
        return 1
    if count <= q2:
        return 2
    if count <= q3:
        return 3
    return 4


def normalize_day_levels(days: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Sort daily records and guarantee valid count/date/level values."""

    normalized: List[Dict[str, Any]] = []
    for item in days:
        raw_date = str(item.get("date") or "")
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError:
            continue
        try:
            count = max(0, int(item.get("count", 0)))
        except (TypeError, ValueError):
            count = 0
        raw_level = item.get("level")
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            level = -1
        normalized.append({"date": parsed.isoformat(), "count": count, "level": level})

    normalized.sort(key=lambda item: item["date"])
    positives = [item["count"] for item in normalized if item["count"] > 0]
    for item in normalized:
        if item["level"] < 0 or item["level"] > 4 or (item["count"] == 0 and item["level"] != 0):
            item["level"] = contribution_level(item["count"], positives)
    return normalized


def fill_calendar_days(
    sparse_days: Iterable[Mapping[str, Any]], start_date: date, end_date: date
) -> List[Dict[str, Any]]:
    """Fill every date in a requested range, keeping API data inside it only."""

    by_date = {item["date"]: item for item in normalize_day_levels(sparse_days)}
    filled: List[Dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        key = current.isoformat()
        item = by_date.get(key, {"date": key, "count": 0, "level": 0})
        filled.append(
            {
                "date": key,
                "count": int(item["count"]),
                "level": max(0, min(4, int(item["level"]))),
                "weekday": current.weekday(),
            }
        )
        current = date.fromordinal(current.toordinal() + 1)
    return filled


def calendar_weeks(days: Sequence[Mapping[str, Any]], start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """Lay exact daily data out as Monday-first seven-day calendar columns."""

    by_date = {str(item["date"]): dict(item) for item in days}
    grid_start = date.fromordinal(start_date.toordinal() - start_date.weekday())
    grid_end = date.fromordinal(end_date.toordinal() + (6 - end_date.weekday()))
    weeks: List[Dict[str, Any]] = []
    week_start = grid_start
    while week_start <= grid_end:
        week_days: List[Optional[Dict[str, Any]]] = []
        for offset in range(7):
            current = date.fromordinal(week_start.toordinal() + offset)
            item = by_date.get(current.isoformat())
            week_days.append(dict(item) if item else None)
        weeks.append({"start_date": week_start.isoformat(), "days": week_days})
        week_start = date.fromordinal(week_start.toordinal() + 7)
    return weeks


def streaks(days: Sequence[Mapping[str, Any]]) -> Tuple[int, int]:
    """Calculate trailing and longest positive-contribution streaks."""

    ordered = sorted(days, key=lambda item: str(item.get("date") or ""))
    longest = 0
    running = 0
    for item in ordered:
        if int(item.get("count") or 0) > 0:
            running += 1
            longest = max(longest, running)
        else:
            running = 0

    trailing = 0
    for item in reversed(ordered):
        if int(item.get("count") or 0) <= 0:
            break
        trailing += 1
    return trailing, longest


def normalized_languages(language_bytes: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Convert byte totals into a stable, percentage-bearing language list."""

    raw: List[Tuple[str, int, str]] = []
    for name, details in language_bytes.items():
        try:
            size = max(0, int(details.get("bytes", 0)))
        except (AttributeError, TypeError, ValueError):
            size = 0
        if size <= 0:
            continue
        raw.append((str(name), size, canonical_color(details.get("color"), str(name))))

    raw.sort(key=lambda item: (-item[1], item[0].casefold(), item[0]))
    total = sum(item[1] for item in raw)
    if total == 0:
        return []
    return [
        {
            "name": name,
            "bytes": size,
            "color": color,
            "percent": round(size * 100 / total, 1),
        }
        for name, size, color in raw
    ]


def empty_calendar_days(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """Return an honest no-data calendar for offline or failed requests.

    A profile README must never imply activity that GitHub did not return. The
    renderer uses this all-zero state with a clear notice instead of inventing
    decorative contribution or language data.
    """

    return fill_calendar_days((), start_date, end_date)


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    """Read a JSON object safely; a corrupt cache is treated as a cache miss."""

    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def atomic_write_text(path: Path, content: str) -> None:
    """Write a text artifact atomically, including on Windows."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    os.replace(temporary, path)


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    """Write stable pretty JSON so cache diffs stay easy to review."""

    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def compact_date(value: Any) -> str:
    """Format ISO metadata without failing on hand-edited cache data."""

    text = str(value or "")
    return text[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", text) else "unknown date"


def format_number(value: Any) -> str:
    """Format arbitrary numeric cache values for human-readable SVG text."""

    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"
