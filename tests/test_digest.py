"""
Unit tests for the Weekly Digest domain models, boundary logic, and formatters.
"""

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from src.parser import load_export
from src.digest import (
    DigestEntry,
    DayGroup,
    WeeklyDigest,
    build_weekly_digest,
    export_digest,
    format_digest_json,
    format_digest_markdown,
    format_week_label,
    get_previous_week_bounds,
    get_sunday_start_bounds,
    parse_week_label,
    week_bounds_from_label,
)
from tests.helpers import get_test_export_dir


class TestDigestBounds(unittest.TestCase):
    """Test date math and week boundary resolution."""

    def test_parse_week_label_valid(self):
        year, week = parse_week_label("2026-48")
        self.assertEqual((year, week), (2026, 48))

        year, week = parse_week_label("2024-W05")
        self.assertEqual((year, week), (2024, 5))

        year, week = parse_week_label("2025_12")
        self.assertEqual((year, week), (2025, 12))

    def test_parse_week_label_invalid(self):
        with self.assertRaises(ValueError):
            parse_week_label("invalid-format")
        with self.assertRaises(ValueError):
            parse_week_label("2026")
        with self.assertRaises(ValueError):
            parse_week_label("2026-48-extra")

    def test_get_sunday_start_bounds(self):
        # 2026-11-22 is Sunday
        sun_input = date(2026, 11, 22)
        sun, sat = get_sunday_start_bounds(sun_input)
        self.assertEqual(sun, date(2026, 11, 22))
        self.assertEqual(sat, date(2026, 11, 28))

        # 2026-11-25 is Wednesday (should resolve to Sunday 2026-11-22)
        wed_input = date(2026, 11, 25)
        sun, sat = get_sunday_start_bounds(wed_input)
        self.assertEqual(sun, date(2026, 11, 22))
        self.assertEqual(sat, date(2026, 11, 28))

        # 2026-11-28 is Saturday (should resolve to Sunday 2026-11-22)
        sat_input = date(2026, 11, 28)
        sun, sat = get_sunday_start_bounds(sat_input)
        self.assertEqual(sun, date(2026, 11, 22))
        self.assertEqual(sat, date(2026, 11, 28))

    def test_get_previous_week_bounds(self):
        ref_sun = date(2026, 11, 22)
        prev_sun, prev_sat = get_previous_week_bounds(ref_sun)
        self.assertEqual(prev_sun, date(2026, 11, 15))
        self.assertEqual(prev_sat, date(2026, 11, 21))

    def test_week_bounds_from_label(self):
        sun, sat, label = week_bounds_from_label("2026-47")
        self.assertEqual(label, "2026-47")
        self.assertEqual(sun, date(2026, 11, 15))  # Sunday
        self.assertEqual(sat, date(2026, 11, 21))  # Saturday
        self.assertEqual(sun.weekday(), 6)
        self.assertEqual(sat.weekday(), 5)
        self.assertEqual((sat - sun).days, 6)

    def test_format_week_label(self):
        sun = date(2026, 11, 15)
        label = format_week_label(sun)
        self.assertEqual(label, "2026-47")


class TestDigestBuilder(unittest.TestCase):
    """Test building digests from message DataFrames."""

    @classmethod
    def setUpClass(cls):
        cls.export_dir = get_test_export_dir()
        cls.df = load_export(cls.export_dir, use_cache=True, verbose=False)

    def test_build_digest_with_sample_data(self):
        # Target a week known to contain synthetic entries (Sep 15, 2026)
        sun, sat = get_sunday_start_bounds(date(2026, 9, 15))
        digest = build_weekly_digest(self.df, start_date=sun, end_date=sat)

        self.assertIsInstance(digest, WeeklyDigest)
        self.assertEqual(len(digest.days), 7)

        # Verify daily sequence starts on Sunday and ends on Saturday
        self.assertEqual(digest.days[0].day_name, "Sunday")
        self.assertEqual(digest.days[1].day_name, "Monday")
        self.assertEqual(digest.days[2].day_name, "Tuesday")
        self.assertEqual(digest.days[3].day_name, "Wednesday")
        self.assertEqual(digest.days[4].day_name, "Thursday")
        self.assertEqual(digest.days[5].day_name, "Friday")
        self.assertEqual(digest.days[6].day_name, "Saturday")

        # Verify Tuesday has messages
        tue = digest.days[2]
        self.assertGreater(tue.total_messages, 0)
        self.assertGreater(tue.total_words, 0)

        # Verify summary stats
        self.assertGreaterEqual(digest.total_messages, tue.total_messages)
        self.assertGreaterEqual(digest.active_days, 1)

        # Test dictionary serialization
        d_dict = digest.to_dict()
        self.assertIn("summary", d_dict)
        self.assertIn("days", d_dict)
        self.assertIn("tagged_groups", d_dict)
        self.assertEqual(len(d_dict["days"]), 7)

    def test_build_digest_empty_week(self):
        # Query a week far in the past with no entries
        sun = date(2010, 1, 3)
        sat = date(2010, 1, 9)
        digest = build_weekly_digest(self.df, start_date=sun, end_date=sat, label="2010-01")

        self.assertEqual(digest.total_messages, 0)
        self.assertEqual(digest.total_words, 0)
        self.assertEqual(digest.active_days, 0)
        self.assertEqual(len(digest.days), 7)
        self.assertEqual(len(digest.tagged_groups), 0)

    def test_build_digest_invalid_args(self):
        # Empty DataFrame
        with self.assertRaises(ValueError):
            build_weekly_digest(pd.DataFrame(), start_date=date(2026, 1, 4), end_date=date(2026, 1, 10))

        # start_date > end_date
        with self.assertRaises(ValueError):
            build_weekly_digest(self.df, start_date=date(2026, 1, 10), end_date=date(2026, 1, 4))


class TestDigestFormatters(unittest.TestCase):
    """Test formatting outputs into JSON and Markdown."""

    def setUp(self):
        # Construct synthetic digest
        entries = [
            DigestEntry(
                id=1,
                timestamp=datetime(2026, 11, 23, 14, 30),
                date_str="2026-11-23",
                time_str="14:30",
                day_name="Monday",
                day_of_week=0,
                text="[robotics] autonomous docking worked!\nSecond line test.",
                word_count=6,
                char_count=45,
                tags=["robotics"],
                has_photo=True,
                has_media=True,
                media_path="docking.jpg",
            )
        ]
        mon_group = DayGroup(
            date_str="2026-11-23",
            day_name="Monday",
            entries=entries,
            total_messages=1,
            total_words=6,
            has_media=True,
            tags=["robotics"],
        )
        empty_days = [
            DayGroup(
                date_str=f"2026-11-{d:02d}",
                day_name=name,
                entries=[],
                total_messages=0,
                total_words=0,
                has_media=False,
                tags=[],
            )
            for d, name in [
                (22, "Sunday"),
                (24, "Tuesday"),
                (25, "Wednesday"),
                (26, "Thursday"),
                (27, "Friday"),
                (28, "Saturday"),
            ]
        ]
        all_days = [empty_days[0], mon_group] + empty_days[1:]

        self.digest = WeeklyDigest(
            label="2026-48",
            year=2026,
            week_num=48,
            start_date="2026-11-22",
            end_date="2026-11-28",
            days=all_days,
            tagged_groups={"robotics": entries},
            total_messages=1,
            total_words=6,
            active_days=1,
            total_photos=1,
            all_tags=[("robotics", 1)],
        )

    def test_json_formatter(self):
        json_output = format_digest_json(self.digest)
        parsed = json.loads(json_output)

        self.assertEqual(parsed["label"], "2026-48")
        self.assertEqual(parsed["summary"]["total_messages"], 1)
        self.assertEqual(parsed["summary"]["total_photos"], 1)
        self.assertIn("robotics", parsed["tagged_groups"])
        self.assertEqual(len(parsed["days"]), 7)

    def test_markdown_formatter(self):
        md_output = format_digest_markdown(self.digest)

        # Check title & summary sections
        self.assertIn("# 🧩 2026-48", md_output)
        self.assertIn("## A quick summary of events that happened the last week", md_output)
        self.assertIn("- **Monday** (2026-11-23)", md_output)
        self.assertIn("autonomous docking worked!", md_output)
        self.assertIn("📷 *[docking.jpg]*", md_output)

        # Check standard retrospective template sections
        self.assertIn("## Biggest win", md_output)
        self.assertIn("## Biggest challenge", md_output)
        self.assertIn("## Looking back on this week’s goals", md_output)
        self.assertIn("## Outcomes for next week", md_output)
        self.assertIn("1. Health", md_output)
        self.assertIn("5. Leisure", md_output)

    def test_export_digest_disk(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = export_digest(self.digest, out_dir=tmp_dir, formats=["json", "md"])
            self.assertIn("json", res)
            self.assertIn("md", res)
            self.assertTrue(res["json"].exists())
            self.assertTrue(res["md"].exists())

            # Verify contents
            saved_json = json.loads(res["json"].read_text(encoding="utf-8"))
            self.assertEqual(saved_json["label"], "2026-48")

            saved_md = res["md"].read_text(encoding="utf-8")
            self.assertTrue(saved_md.startswith("# 🧩 2026-48"))


if __name__ == "__main__":
    unittest.main()
