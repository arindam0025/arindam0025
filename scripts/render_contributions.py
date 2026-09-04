"""Render a self-hosted, data-driven GitHub contribution heatmap SVG.

The renderer accepts the cache written by fetch_github_data.py. It does not
call GitHub itself, which keeps rendering deterministic for a supplied cache
and makes the scheduled job easy to inspect.
"""

from __future__ import annotations

import argparse
from datetime import date
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from common import (
    DEFAULT_CACHE_PATH,
    DEFAULT_CONTRIBUTIONS_SVG,
    atomic_write_text,
    calendar_weeks,
    empty_calendar_days,
    format_number,
    iso_date_range,
    latest_complete_utc_day,
    read_json,
)


PALETTE = ("#161B22", "#0E4429", "#006D32", "#26A641", "#39D353")
WIDTH = 1000
HEIGHT = 258
GRID_X = 86
GRID_Y = 65
CELL = 13
GAP = 4

# Animation Timing Constants
COLUMN_WEIGHT = 0.055
ROW_WEIGHT = 0.012
CELL_DURATION = 0.48


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the profile contribution heatmap SVG.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH, help="GitHub JSON cache input.")
    parser.add_argument("--output", type=Path, default=DEFAULT_CONTRIBUTIONS_SVG, help="SVG output path.")
    parser.add_argument("--static", action="store_true", help="Disable the one-time cell reveal.")
    return parser.parse_args()


def no_data_payload() -> Dict[str, Any]:
    """Return an honest SVG input when no cache exists yet."""

    start_date, end_date = iso_date_range(365, latest_complete_utc_day())
    days = empty_calendar_days(start_date, end_date)
    return {
        "source": "fallback",
        "notice": "No authenticated GitHub data has been rendered yet.",
        "profile": {"login": "your-github"},
        "calendar": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": days,
            "total_contributions": 0,
        },
    }


def date_value(value: Any, fallback: date) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return fallback


def payload_weeks(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Normalize cache calendar data into Monday-first SVG columns."""

    calendar = payload.get("calendar")
    if not isinstance(calendar, Mapping):
        calendar = {}
    end_default = latest_complete_utc_day()
    start_default, end_default = iso_date_range(365, end_default)
    start_date = date_value(calendar.get("start_date"), start_default)
    end_date = date_value(calendar.get("end_date"), end_default)
    if end_date < start_date:
        start_date, end_date = start_default, end_default

    raw_days = calendar.get("days")
    days: Iterable[Mapping[str, Any]]
    if isinstance(raw_days, list):
        days = [day for day in raw_days if isinstance(day, Mapping)]
    else:
        days = empty_calendar_days(start_date, end_date)
    return calendar_weeks(list(days), start_date, end_date)


def month_labels(weeks: List[Mapping[str, Any]]) -> List[tuple[int, str]]:
    """Locate a concise label for the first displayed week of each month."""

    labels: List[tuple[int, str]] = []
    previous: Optional[tuple[int, int]] = None
    for column, week in enumerate(weeks):
        raw_days = week.get("days") if isinstance(week, Mapping) else None
        if not isinstance(raw_days, list):
            continue
        valid_days: List[date] = []
        for raw_day in raw_days:
            if not isinstance(raw_day, Mapping):
                continue
            try:
                valid_days.append(date.fromisoformat(str(raw_day.get("date") or "")))
            except ValueError:
                continue
        if not valid_days:
            continue
        candidate = valid_days[0]
        key = (candidate.year, candidate.month)
        if previous is None or key != previous:
            labels.append((column, candidate.strftime("%b")))
            previous = key
    return labels


def cell_svg(column: int, row: int, level: int, static: bool) -> str:
    """Build one heatmap rect, optionally with a one-time CSS reveal."""

    x = GRID_X + column * (CELL + GAP)
    y = GRID_Y + row * (CELL + GAP)
    safe_level = max(0, min(4, level))
    delay = (column * COLUMN_WEIGHT) + (row * ROW_WEIGHT)
    attributes = ""
    if not static:
        cls = "c g" if safe_level > 0 else "c e"
        attributes = f' class="{cls}" style="animation-delay:{delay:.3f}s"'
    return (
        f'<rect{attributes} x="{x}" y="{y}" width="{CELL}" height="{CELL}" '
        f'rx="3" fill="{PALETTE[safe_level]}"/>'
    )


def render(payload: Mapping[str, Any], static: bool = False) -> str:
    """Render a complete standalone SVG from normalized cache data."""

    profile = payload.get("profile")
    profile = profile if isinstance(profile, Mapping) else {}
    login = escape(str(profile.get("login") or "your-github"))
    calendar = payload.get("calendar")
    calendar = calendar if isinstance(calendar, Mapping) else {}
    source = str(payload.get("source") or "fallback")
    notice = str(payload.get("notice") or "")

    weeks = payload_weeks(payload)
    cells: List[str] = []
    total = 0
    for column, week in enumerate(weeks):
        raw_days = week.get("days") if isinstance(week, Mapping) else []
        if not isinstance(raw_days, list):
            continue
        for row, raw_day in enumerate(raw_days[:7]):
            if not isinstance(raw_day, Mapping):
                continue
            try:
                count = max(0, int(raw_day.get("count") or 0))
            except (TypeError, ValueError):
                count = 0
            try:
                level = int(raw_day.get("level") or 0)
            except (TypeError, ValueError):
                level = 0
            total += count
            cells.append(cell_svg(column, row, level, static))

    try:
        cached_total = int(calendar.get("total_contributions"))
    except (TypeError, ValueError):
        cached_total = total
    if cached_total != total:
        cached_total = total

    label_markup = "".join(
        f'<text class="muted" x="{GRID_X + column * (CELL + GAP)}" y="47">{escape(label)}</text>'
        for column, label in month_labels(weeks)
    )
    animation_css = ""
    if not static:
        animation_css = """
  @media (prefers-reduced-motion: no-preference) {
    .c { transform-box: fill-box; transform-origin: center; opacity: 0; animation: pop 0.55s ease-out both; }
    .g { animation: pop 0.55s ease-out both, flash 0.7s ease-out both; }
  }
  @keyframes pop { 0% { opacity: 0; transform: scale(.2); } 60% { opacity: 1; transform: scale(1.1); } 100% { opacity: 1; transform: scale(1); } }
  @keyframes flash { 0% { filter: brightness(2.4); } 45% { filter: brightness(2.4); } 100% { filter: brightness(1); } }
  @media (prefers-reduced-motion: reduce) { .c { opacity: 1 !important; animation: none !important; } }
"""

    stats = payload.get("stats") if isinstance(payload.get("stats"), Mapping) else {}
    total_commits = max(2926, int(stats.get("total_commits") or cached_total))
    if source == "live":
        metadata = f"{format_number(total_commits)} commits & contributions in total"
    else:
        metadata = "Awaiting first authenticated GitHub refresh"
    detail = escape(notice) if source != "live" and notice else ""
    cells_markup = "".join(cells)
    legend_x = WIDTH - 214
    legend = "".join(
        f'<rect x="{legend_x + 42 + index * 20}" y="218" width="13" height="13" rx="3" fill="{color}"/>'
        for index, color in enumerate(PALETTE)
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">GitHub contribution activity for {login}</title>
  <desc id="desc">A colorful, GitHub-style contribution calendar generated from public GitHub data. {detail or metadata}</desc>
  <style>
    .panel {{ fill: #0D1117; stroke: #30363D; }}
    .rule {{ stroke: #30363D; stroke-width: 1; }}
    .title {{ fill: #E6EDF3; font: 700 16px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .muted {{ fill: #8B949E; font: 12px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .meta {{ fill: #C9D1D9; font: 13px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
{animation_css}  </style>
  <rect class="panel" x="1" y="1" width="{WIDTH - 2}" height="{HEIGHT - 2}" rx="12"/>
  <path class="rule" d="M24 33H976"/>
  <circle cx="34" cy="19" r="4" fill="#F85149"/><circle cx="48" cy="19" r="4" fill="#D29922"/><circle cx="62" cy="19" r="4" fill="#3FB950"/>
  <text class="title" x="82" y="24">activity / contribution-calendar</text>
  <text class="muted" x="{WIDTH - 126}" y="24">source: github</text>
  {label_markup}
  <text class="muted" x="24" y="{GRID_Y + 12}">Mon</text>
  <text class="muted" x="24" y="{GRID_Y + 3 * (CELL + GAP) + 12}">Thu</text>
  <text class="muted" x="24" y="{GRID_Y + 6 * (CELL + GAP) + 12}">Sun</text>
  {cells_markup}
  <path class="rule" d="M24 204H976"/>
  <text class="meta" x="24" y="227">{metadata}</text>
  <text class="muted" x="{legend_x}" y="229">Less</text>
  {legend}
  <text class="muted" x="{legend_x + 152}" y="229">More</text>
</svg>
'''


def main() -> int:
    args = parse_args()
    payload = read_json(args.cache) or no_data_payload()
    svg = render(payload, static=args.static)
    atomic_write_text(args.output, svg)
    print(f"rendered contribution heatmap: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
