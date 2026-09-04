#!/usr/bin/env python3
"""Render a local profile image as a self-contained gold-on-dark ASCII SVG."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape

try:
    from PIL import Image, ImageOps
except ImportError as error:  # pragma: no cover - depends on local setup
    raise SystemExit("Install requirements-static.txt to regenerate the portrait SVG.") from error


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPOSITORY_ROOT / "source" / "profile-photo.png"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "assets" / "portrait.svg"

# A short palette keeps fine line art legible at the narrow widths used in a
# README. Spaces remain the dark background; every other character is gold.
PALETTE = " .,:;+=*#%@"
DEFAULT_COLUMNS = 66
FONT_SIZE = 13.2
CELL_WIDTH = 8.0


def parse_args() -> argparse.Namespace:
    """Parse regeneration options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="source avatar image (default: source/profile-photo.png)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="generated SVG path (default: assets/portrait.svg)",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="omit the one-time reveal animation for a fully still SVG",
    )
    parser.add_argument(
        "--columns",
        type=int,
        default=DEFAULT_COLUMNS,
        help=f"ASCII columns to render (default: {DEFAULT_COLUMNS})",
    )
    return parser.parse_args()


def warm_ink_signal(red: int, green: int, blue: int, alpha: int) -> float:
    """Return a line-art signal that favours warm/gold ink over grey noise.

    The profile owl is gold on black. Combining luma with yellow warmth keeps
    its anti-aliased strokes while preventing faint neutral background pixels
    from turning into distracting ASCII speckles. Alpha is composited on black.
    """
    opacity = alpha / 255.0
    red *= opacity
    green *= opacity
    blue *= opacity
    luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    warmth = max(0.0, red - blue) + 0.60 * max(0.0, green - blue)
    return min(255.0, 0.35 * luma + 1.40 * warmth)


def cell_signal(pixels: Sequence[tuple[int, int, int, int]]) -> float:
    """Sample a cell without losing a thin outline that crosses it."""
    values = [warm_ink_signal(*pixel) for pixel in pixels]
    if not values:
        return 0.0
    # A maximum preserves a one-pixel curve. A little mean prevents isolated
    # hot pixels from dominating a character cell.
    return 0.72 * max(values) + 0.28 * (sum(values) / len(values))


def character_for(signal: float) -> str:
    """Translate a warm-ink strength to one printable ASCII character."""
    threshold = 36.0
    if signal < threshold:
        return " "
    normalised = (signal - threshold) / (255.0 - threshold)
    index = max(1, min(len(PALETTE) - 1, round(normalised * (len(PALETTE) - 1))))
    return PALETTE[index]


def image_rows(image: Image.Image, columns: int) -> list[str]:
    """Rasterise ``image`` into rows whose rendered cell aspect stays square."""
    width, height = image.size
    rows = max(1, round(columns * (height / width) * (CELL_WIDTH / FONT_SIZE)))
    rgba = image.convert("RGBA")
    output: list[str] = []

    for row in range(rows):
        top = math.floor(row * height / rows)
        bottom = max(top + 1, math.floor((row + 1) * height / rows))
        characters: list[str] = []
        for column in range(columns):
            left = math.floor(column * width / columns)
            right = max(left + 1, math.floor((column + 1) * width / columns))
            crop = rgba.crop((left, top, right, bottom))
            pixel_access = crop.load()
            region = [
                pixel_access[x, y]
                for y in range(crop.height)
                for x in range(crop.width)
            ]
            characters.append(character_for(cell_signal(region)))
        output.append("".join(characters))
    return output


def animated_row(row_index: int, y: float, text: str, animated: bool, grid_width: float) -> str:
    """Build one row with an optional, one-time CSS fade-in.

    The text remains visible when an SVG host disables animation support. This
    is safer than using an inline opacity of zero as the static fallback.
    """
    delay = 0.18 + row_index * 0.065
    class_name = "row"
    reveal = ""
    if animated:
        class_name += " render-row"
        reveal = f' style="animation-delay:{delay:.3f}s"'
    return (
        f'    <text class="{class_name}" xml:space="preserve" x="28" y="{y:.1f}" '
        f'textLength="{grid_width:.1f}" lengthAdjust="spacingAndGlyphs"{reveal}>'
        f"{escape(text)}</text>"
    )


def build_svg(rows: Sequence[str], source_name: str, animated: bool) -> str:
    """Create standalone SVG markup, including a terminal-style frame."""
    columns = len(rows[0])
    row_count = len(rows)
    grid_width = columns * CELL_WIDTH
    grid_height = row_count * FONT_SIZE
    width = int(math.ceil(grid_width + 56))
    height = int(math.ceil(grid_height + 92))
    footer_y = 56 + grid_height + 24
    animation_rows = [
        animated_row(index, 56 + (index + 1) * FONT_SIZE, row, animated, grid_width)
        for index, row in enumerate(rows)
    ]
    cursor = ""
    if animated:
        final_delay = 0.18 + row_count * 0.065
        cursor = (
            f'    <rect class="cursor render-cursor" x="28" y="{footer_y - 10:.1f}" width="7" height="12" '
            f'style="animation-delay:{final_delay:.3f}s"/>'
        )
    animation_note = "Rows reveal once in terminal order." if animated else "Static, no-motion rendering."
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby="title desc">',
            "  <title id=\"title\">Gold ASCII owl portrait</title>",
            f"  <desc id=\"desc\">A gold-on-dark ASCII rendering of {escape(source_name)}. {animation_note}</desc>",
            "  <style>",
            "    .background { fill: #090906; }",
            "    .frame { fill: #100e09; stroke: #665630; stroke-width: 1.25; }",
            "    .terminal-label, .footer { fill: #a89257; font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace; font-size: 10px; letter-spacing: .55px; }",
            "    .dim { fill: #77663c; font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace; font-size: 9px; }",
            "    .row { fill: #c9ad63; font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace; font-size: 13.2px; font-weight: 700; }",
            "    .cursor { fill: #d9bd6c; display: none; }",
            "    @media (prefers-reduced-motion: no-preference) {",
            "      .render-row { animation: row-print .18s ease-out both; }",
            "      .render-cursor { display: block; animation: cursor-finish .72s ease-out both; }",
            "    }",
            "    @keyframes row-print { 0% { opacity: 0; transform: translateX(-3px); } 100% { opacity: 1; transform: translateX(0); } }",
            "    @keyframes cursor-finish { 0%, 15% { opacity: 0; } 30%, 55% { opacity: 1; } 100% { opacity: 0; } }",
            "    @media (prefers-reduced-motion: reduce) { .row { opacity: 1 !important; } .cursor { display: none; } }",
            "  </style>",
            f'  <rect class="background" width="{width}" height="{height}" rx="12"/>',
            f'  <rect class="frame" x="10" y="10" width="{width - 20}" height="{height - 20}" rx="8"/>',
            '  <circle cx="27" cy="29" r="4" fill="#d9bd6c"/>',
            '  <circle cx="41" cy="29" r="4" fill="#a89257"/>',
            '  <circle cx="55" cy="29" r="4" fill="#665630"/>',
            '  <text class="terminal-label" x="75" y="33">OWL.PORTRAIT  /  ASCII SIGNAL</text>',
            f'  <text class="dim" x="{width - 102}" y="33">{columns:02d} × {row_count:02d}</text>',
            '  <path d="M20 43.5H' + str(width - 20) + '" stroke="#4f4329" stroke-width="1"/>',
            *animation_rows,
            f'  <text class="footer" x="28" y="{footer_y:.1f}">&gt; render.complete</text>',
            cursor,
            "</svg>",
            "",
        ]
    )


def main() -> int:
    args = parse_args()
    if args.columns < 12:
        raise SystemExit("--columns must be at least 12 for a readable portrait.")

    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input image does not exist: {input_path}")

    with Image.open(input_path) as raw_image:
        image = ImageOps.exif_transpose(raw_image).convert("RGBA")
    rows = image_rows(image, args.columns)
    svg = build_svg(rows, input_path.name, animated=not args.static)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8", newline="\n")
    mode = "static" if args.static else "one-time CSS reveal"
    print(f"Wrote {mode} SVG portrait: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
