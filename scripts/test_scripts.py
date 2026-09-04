"""Unit tests for GitHub profile SVG generation scripts."""

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from PIL import Image

from common import (
    calendar_weeks,
    canonical_color,
    contribution_level,
    fill_calendar_days,
    iso_date_range,
    normalized_languages,
    normalize_username,
    parse_as_of,
    resolve_username,
    streaks,
)
from fetch_github_data import build_fallback_payload, cache_matches
import render_contributions
import render_stats
import make_portrait


class TestCommonHelpers(unittest.TestCase):
    def test_normalize_username(self):
        self.assertEqual(normalize_username("arindam0025"), "arindam0025")
        self.assertEqual(normalize_username("@arindam0025"), "arindam0025")
        self.assertIsNone(normalize_username(""))
        self.assertIsNone(normalize_username(None))
        with self.assertRaises(ValueError):
            normalize_username("invalid username!")

    def test_resolve_username(self):
        self.assertEqual(resolve_username("explicit-user"), "explicit-user")
        self.assertEqual(resolve_username(None, {"profile": {"login": "cached-user"}}), "cached-user")
        self.assertEqual(resolve_username(None, None), "your-github")

    def test_iso_date_range(self):
        end = date(2026, 9, 4)
        start, end_out = iso_date_range(7, end)
        self.assertEqual(start, date(2026, 8, 29))
        self.assertEqual(end_out, end)
        with self.assertRaises(ValueError):
            iso_date_range(0, end)

    def test_parse_as_of(self):
        self.assertEqual(parse_as_of("2026-01-01"), date(2026, 1, 1))
        with self.assertRaises(ValueError):
            parse_as_of("invalid-date")

    def test_streaks(self):
        days = [
            {"date": "2026-01-01", "count": 1},
            {"date": "2026-01-02", "count": 3},
            {"date": "2026-01-03", "count": 0},
            {"date": "2026-01-04", "count": 2},
            {"date": "2026-01-05", "count": 4},
        ]
        trailing, longest = streaks(days)
        self.assertEqual(trailing, 2)
        self.assertEqual(longest, 2)

    def test_normalized_languages(self):
        lang_bytes = {
            "Python": {"bytes": 1000, "color": "#3572A5"},
            "TypeScript": {"bytes": 500, "color": "#3178C6"},
        }
        res = normalized_languages(lang_bytes)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["name"], "Python")
        self.assertEqual(res[0]["percent"], 66.7)
        self.assertEqual(res[1]["name"], "TypeScript")
        self.assertEqual(res[1]["percent"], 33.3)


class TestFetchData(unittest.TestCase):
    def test_fallback_payload(self):
        start = date(2026, 1, 1)
        end = date(2026, 1, 10)
        payload = build_fallback_payload("testuser", start, end, "test reason")
        self.assertEqual(payload["profile"]["login"], "testuser")
        self.assertEqual(payload["source"], "fallback")
        self.assertTrue(cache_matches(payload, "testuser", start, end))
        self.assertFalse(cache_matches(payload, "otheruser", start, end))


class TestRenderers(unittest.TestCase):
    def test_render_contributions(self):
        start = date(2026, 1, 1)
        end = date(2026, 1, 10)
        payload = build_fallback_payload("arindam0025", start, end, "testing")
        svg = render_contributions.render(payload)
        self.assertIn("GitHub contribution activity for arindam0025", svg)
        self.assertIn("<svg", svg)

    def test_render_stats_fallback_and_live(self):
        start = date(2026, 1, 1)
        end = date(2026, 1, 10)
        fallback_payload = build_fallback_payload("arindam0025", start, end, "testing")
        svg_fallback = render_stats.render(fallback_payload)
        self.assertIn("live activity is ready to refresh", svg_fallback)

        live_payload = {
            "source": "live",
            "profile": {"login": "arindam0025"},
            "calendar": {"total_contributions": 150},
            "stats": {
                "active_days": 45,
                "current_streak": 5,
                "longest_streak": 12,
                "public_repositories": 8,
                "total_stars": 25,
                "languages": [{"name": "Python", "bytes": 1000, "color": "#3572A5", "percent": 100.0}],
            },
        }
        svg_live = render_stats.render(live_payload)
        self.assertIn("TOTAL COMMITS", svg_live)
        self.assertIn("Python", svg_live)

    def test_make_wordmark(self):
        import make_wordmark
        svg = make_wordmark.render(static=False)
        self.assertIn("Arindam Nag", svg)
        self.assertIn("arindam0025@github", svg)
        self.assertIn("<svg", svg)


class TestMakePortrait(unittest.TestCase):
    def test_make_portrait(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = Path(tmpdir) / "test_avatar.png"
            img = Image.new("RGBA", (100, 100), color=(200, 180, 50, 255))
            img.save(img_path)

            rows = make_portrait.image_rows(img, columns=20)
            self.assertTrue(len(rows) > 0)
            self.assertEqual(len(rows[0]), 20)

            svg = make_portrait.build_svg(rows, "test_avatar.png", animated=True)
            self.assertIn("Gold ASCII owl portrait", svg)
            self.assertIn("<svg", svg)


if __name__ == "__main__":
    unittest.main()
