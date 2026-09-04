"""Render a compact public GitHub-activity summary as a standalone SVG."""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Mapping

from common import DEFAULT_CACHE_PATH, DEFAULT_STATS_SVG, atomic_write_text, format_number, read_json


WIDTH = 1000
HEIGHT = 276


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the profile public-activity stats SVG.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH, help="GitHub JSON cache input.")
    parser.add_argument("--output", type=Path, default=DEFAULT_STATS_SVG, help="SVG output path.")
    return parser.parse_args()


def integer(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def metric_card(x: int, label: str, value: str) -> str:
    """Render one metric card with simple, stable SVG geometry."""

    return f'''
  <rect class="card" x="{x}" y="55" width="218" height="78" rx="8"/>
  <text class="label" x="{x + 16}" y="81">{escape(label)}</text>
  <text class="value" x="{x + 16}" y="114">{escape(value)}</text>'''


def render(payload: Mapping[str, Any]) -> str:
    profile = payload.get("profile")
    profile = profile if isinstance(profile, Mapping) else {}
    calendar = payload.get("calendar")
    calendar = calendar if isinstance(calendar, Mapping) else {}
    stats = payload.get("stats")
    stats = stats if isinstance(stats, Mapping) else {}
    source = str(payload.get("source") or "fallback")
    login = escape(str(profile.get("login") or "your-github"))
    notice = escape(str(payload.get("notice") or "No authenticated GitHub data has been rendered yet."))

    if source != "live":
        content = f'''
  <rect class="empty" x="24" y="58" width="952" height="166" rx="10"/>
  <text class="empty-title" x="52" y="105">live activity is ready to refresh</text>
  <text class="empty-copy" x="52" y="139">Run the Refresh profile activity workflow or provide GITHUB_TOKEN locally.</text>
  <text class="empty-copy" x="52" y="167">{notice}</text>
  <text class="empty-copy" x="52" y="199">No placeholder counts or invented language data are displayed.</text>'''
    else:
        total_contributions = integer(calendar.get("total_contributions"))
        active_days = integer(stats.get("active_days"))
        current_streak = integer(stats.get("current_streak"))
        longest_streak = integer(stats.get("longest_streak"))
        public_repositories = integer(stats.get("public_repositories"))
        total_stars = integer(stats.get("total_stars"))
        cards = "".join(
            (
                metric_card(24, "CONTRIBUTIONS / YEAR", format_number(total_contributions)),
                metric_card(270, "ACTIVE DAYS", format_number(active_days)),
                metric_card(516, "CURRENT STREAK", f"{current_streak} days"),
                metric_card(762, "LONGEST STREAK", f"{longest_streak} days"),
            )
        )
        languages = stats.get("languages")
        language_rows: List[str] = []
        if isinstance(languages, list) and languages:
            for index, item in enumerate(languages[:5]):
                if not isinstance(item, Mapping):
                    continue
                name = escape(str(item.get("name") or "Unknown"))
                color = str(item.get("color") or "#8B949E")
                try:
                    percent = float(item.get("percent") or 0)
                except (TypeError, ValueError):
                    percent = 0.0
                percent = max(0.0, min(100.0, percent))
                x = 24 + index * 190
                bar_width = int(132 * percent / 100)
                language_rows.append(
                    f'<text class="language" x="{x}" y="180">{name}</text>'
                    f'<text class="percent" x="{x + 146}" y="180">{percent:.1f}%</text>'
                    f'<rect class="bar-bg" x="{x}" y="190" width="168" height="8" rx="4"/>'
                    f'<rect x="{x}" y="190" width="{bar_width}" height="8" rx="4" fill="{escape(color)}"/>'
                )
        if not language_rows:
            language_rows.append('<text class="empty-copy" x="24" y="189">No public language aggregation was returned by GitHub.</text>')
        content = f'''
  {cards}
  <text class="section" x="24" y="157">PUBLIC LANGUAGE MIX</text>
  {''.join(language_rows)}
  <text class="footer" x="24" y="243">PUBLIC REPOSITORIES  {format_number(public_repositories)}</text>
  <text class="footer" x="284" y="243">TOTAL STARS  {format_number(total_stars)}</text>
  <text class="footer" x="762" y="243">scope: owned public repositories</text>'''

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">Public GitHub activity summary for {login}</title>
  <desc id="desc">Repository and contribution statistics generated from public GitHub data. {notice}</desc>
  <style>
    .panel {{ fill: #0D1117; stroke: #30363D; }}
    .rule {{ stroke: #30363D; stroke-width: 1; }}
    .title {{ fill: #E6EDF3; font: 700 16px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .label, .section {{ fill: #8B949E; font: 700 11px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; letter-spacing: .4px; }}
    .value {{ fill: #E6EDF3; font: 700 25px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .card {{ fill: #161B22; stroke: #30363D; }}
    .language {{ fill: #C9D1D9; font: 12px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .percent, .footer, .empty-copy {{ fill: #8B949E; font: 11px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .bar-bg, .empty {{ fill: #161B22; stroke: #30363D; }}
    .empty-title {{ fill: #E6EDF3; font: 700 18px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
  </style>
  <rect class="panel" x="1" y="1" width="{WIDTH - 2}" height="{HEIGHT - 2}" rx="12"/>
  <path class="rule" d="M24 33H976"/>
  <circle cx="34" cy="19" r="4" fill="#F85149"/><circle cx="48" cy="19" r="4" fill="#D29922"/><circle cx="62" cy="19" r="4" fill="#3FB950"/>
  <text class="title" x="82" y="24">public-signal / repository-summary</text>
  <text class="footer" x="852" y="24">user: {login}</text>
  {content}
</svg>
'''


def main() -> int:
    args = parse_args()
    payload = read_json(args.cache) or {}
    atomic_write_text(args.output, render(payload))
    print(f"rendered public activity summary: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
