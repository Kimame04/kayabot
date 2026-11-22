#!/usr/bin/env python3
"""
CLI runner for On This Day (OTD) personal journal time capsule.

Usage:
    python -m scripts.run_otd
    python -m scripts.run_otd --date 09-15
    python -m scripts.run_otd --date yesterday
    python -m scripts.run_otd --random
    python -m scripts.run_otd --window 2 --html
    python -m scripts.run_otd --export-dir "path/to/export"
"""

from __future__ import annotations

import argparse
from pathlib import Path
from datetime import date

from src.parser import load_export, resolve_export_dir
from src.otd import (
    parse_query_date,
    query_on_this_day,
    get_random_active_day,
    generate_otd_html,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Surface journal memories and thoughts from this calendar day across past years."
    )
    parser.add_argument(
        "--date",
        "-d",
        type=str,
        default=None,
        help="Date to query: 'MM-DD', 'YYYY-MM-DD', 'Month Day', 'yesterday', or leave blank for today.",
    )
    parser.add_argument(
        "--window",
        "-w",
        type=int,
        default=0,
        help="Day window radius (±N days around the target date, default: 0).",
    )
    parser.add_argument(
        "--random",
        "-r",
        action="store_true",
        help="Pick a random past day from your journal that has memories.",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        default=True,
        help="Generate a standalone interactive HTML memory card (default: True).",
    )
    parser.add_argument(
        "--no-html",
        dest="html",
        action="store_false",
        help="Skip HTML card generation.",
    )
    parser.add_argument(
        "--export-dir",
        "-i",
        type=str,
        default=None,
        help="Path to the Telegram ChatExport directory (auto-discovered if omitted).",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="output/otd",
        help="Directory to save generated HTML memory cards.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass Parquet cache and force re-parsing of raw HTML files.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress verbose parser logs.",
    )

    args = parser.parse_args()

    export_path = resolve_export_dir(args.export_dir)
    output_path = Path(args.output_dir)

    # 1. Load data
    df = load_export(export_path, use_cache=not args.no_cache, verbose=not args.quiet)

    # 2. Determine target month and day
    if args.random:
        month, day = get_random_active_day(df, min_msgs=2)
        print(f"\n🎲 Selected random past active day: {month:02d}-{day:02d}")
    else:
        month, day = parse_query_date(args.date)

    # 3. Query OTD
    result = query_on_this_day(df, month=month, day=day, window_days=args.window)

    # 4. Terminal Output
    print("\n" + "=" * 70)
    print(f"🕰️  ON THIS DAY: {result.date_title.upper()}")
    print("=" * 70)
    print(f"📊 Memories Found: {result.total_matches} messages across {len(result.year_groups)} years")
    if result.all_tags:
        print(f"🏷️  Tracked Interests: {', '.join(f'[{t}]' for t in result.all_tags[:8])}")
    print("-" * 70)

    if not result.year_groups:
        print("\n🍃 No memories found for this calendar day.")
        print("💡 Tip: Try expanding the date window with '--window 2' or try '--random'!")
    else:
        for g in result.year_groups:
            print(f"\n{'━' * 70}")
            span_str = f" · {g.first_time} -> {g.last_time}" if g.first_time and g.last_time else ""
            print(f"📅 {g.label.upper()} · {g.total_messages} messages{span_str}")
            if g.tags_summary:
                tags_str = " ".join(f"[{t}]({c})" for t, c in g.tags_summary[:6])
                print(f"🏷️  Topics: {tags_str}")
            print(f"{'─' * 70}")

            for idx, e in enumerate(g.entries, 1):
                time_badge = f"[{e.time_str}]"
                media_badge = " 📷" if e.has_photo else ""

                lines = [line.strip() for line in e.text.split("\n") if line.strip()]
                first_line = lines[0] if lines else "(media attachment)"
                print(f"  {idx:2d}. {time_badge}{media_badge} {first_line}")
                for extra_line in lines[1:]:
                    print(f"      {extra_line}")

    # 5. Generate HTML Memory Card
    if args.html and result.total_matches > 0:
        html_file = output_path / f"on_this_day_{month:02d}_{day:02d}.html"
        latest_file = output_path / "on_this_day.html"
        generate_otd_html(result, html_file)
        generate_otd_html(result, latest_file)
        print("\n" + "=" * 70)
        print("✨ Interactive memory card generated:")
        print(f"   🌐 {latest_file.resolve()}")
        print("=" * 70)


if __name__ == "__main__":
    main()
