"""Render a terminal header / wordmark SVG for Arindam Nag.

Generates assets/wordmark.svg containing terminal chrome, ASCII typography / prompt,
and role information with an optional one-time CSS reveal animation.
"""

from __future__ import annotations

import argparse
import sys
from html import escape
from pathlib import Path

from common import ASSETS_DIR, atomic_write_text

DEFAULT_WORDMARK_SVG = ASSETS_DIR / "wordmark.svg"
WIDTH = 1000
HEIGHT = 160


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the terminal wordmark SVG.")
    parser.add_argument("--output", type=Path, default=DEFAULT_WORDMARK_SVG, help="SVG output path.")
    parser.add_argument("--static", action="store_true", help="Omit CSS animations.")
    return parser.parse_args()


def render(static: bool = False) -> str:
    title = "arindam0025@github ~ $ whoami"
    name = "Arindam Nag"
    tagline = "Quantitative Finance  ·  Algorithmic Trading  ·  Risk Systems"
    stack = "Python  ·  C++  ·  TypeScript  ·  R  ·  SQL  ·  MetaTrader 5  ·  XGBoost"

    animation_css = ""
    if not static:
        animation_css = """
    @media (prefers-reduced-motion: no-preference) {
      .cmd-text { animation: type-text 0.6s steps(28, end) 0.1s both; }
      .name-text { animation: fade-in 0.5s ease-out 0.6s both; }
      .tagline-text { animation: fade-in 0.5s ease-out 0.9s both; }
      .cursor { display: inline-block; animation: blink 1s step-end infinite; }
    }
    @keyframes type-text { 0% { opacity: 0; } 100% { opacity: 1; } }
    @keyframes fade-in { 0% { opacity: 0; transform: translateY(4px); } 100% { opacity: 1; transform: translateY(0); } }
    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
"""

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">Arindam Nag — Developer Console Header</title>
  <desc id="desc">Terminal console header showing identity, role, and core stack for Arindam Nag.</desc>
  <style>
    .panel {{ fill: #0D1117; stroke: #30363D; }}
    .rule {{ stroke: #30363D; stroke-width: 1; }}
    .prompt-user {{ fill: #39D353; font: 700 13px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .prompt-path {{ fill: #58A6FF; font: 700 13px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .cmd-text {{ fill: #E6EDF3; font: 700 13px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .name-text {{ fill: #D9BD6C; font: 700 24px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; letter-spacing: 1px; }}
    .tagline-text {{ fill: #C9D1D9; font: 600 13px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .stack-text {{ fill: #8B949E; font: 12px ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
    .cursor {{ fill: #D9BD6C; }}
{animation_css}  </style>
  <rect class="panel" x="1" y="1" width="{WIDTH - 2}" height="{HEIGHT - 2}" rx="12"/>
  <circle cx="34" cy="19" r="4" fill="#F85149"/><circle cx="48" cy="19" r="4" fill="#D29922"/><circle cx="62" cy="19" r="4" fill="#3FB950"/>
  <path class="rule" d="M24 33H976"/>
  
  <!-- Terminal Prompt -->
  <text class="prompt-user" x="28" y="58">arindam0025@github</text>
  <text class="prompt-path" x="180" y="58">~ $</text>
  <text class="cmd-text" x="215" y="58">whoami</text>
  <rect class="cursor" x="272" y="46" width="8" height="15" rx="1"/>

  <!-- Identity & Role -->
  <text class="name-text" x="28" y="96">{escape(name)}</text>
  <text class="tagline-text" x="28" y="122">{escape(tagline)}</text>
  <text class="stack-text" x="28" y="142">{escape(stack)}</text>
</svg>
'''


def main() -> int:
    args = parse_args()
    svg = render(static=args.static)
    atomic_write_text(args.output, svg)
    print(f"rendered terminal wordmark: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
