#!/usr/bin/env python3
"""
CLI runner for Circadian & Habit Heatmap analysis.

Usage:
    python -m scripts.run_circadian
    python -m scripts.run_circadian --export-dir "path/to/any/ChatExport_folder" --output-dir "output/circadian"
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.parser import load_export, resolve_export_dir
from src.circadian import generate_circadian_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze and visualize personal circadian rhythms and journaling habits from Telegram exports."
    )
    parser.add_argument(
        "--export-dir",
        "-i",
        type=str,
        default=None,
        help="Path to the Telegram ChatExport directory (auto-discovered if omitted)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="output/circadian",
        help="Directory where generated charts and HTML report will be saved (default: 'output/circadian')",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass Parquet cache and force re-parsing of raw HTML files",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress verbose logs",
    )

    args = parser.parse_args()

    export_path = resolve_export_dir(args.export_dir)
    output_path = Path(args.output_dir)

    print("=" * 65)
    print("🌙 TELEGRAM JOURNAL - CIRCADIAN & HABIT HEATMAP")
    print("=" * 65)
    print(f"📁 Target Export:  {export_path.resolve()}")
    print(f"📊 Output Dir:     {output_path.resolve()}")
    print(f"⚡ Cache Enabled:  {not args.no_cache}")
    print("-" * 65)

    # 1. Load data via universal parser
    df = load_export(export_path, use_cache=not args.no_cache, verbose=not args.quiet)

    # 2. Generate circadian analysis and reports
    print("\n[Analysis] Generating circadian charts and interactive report...")
    metrics = generate_circadian_report(df, output_path)

    # 3. Print summary findings
    print("\n" + "=" * 65)
    print("📌 KEY CIRCADIAN INSIGHTS")
    print("=" * 65)
    print(f"• Total Logged Entries:   {metrics['total_messages']:,}")
    print(f"• Peak Journaling Hour:   {metrics['peak_hour']:02d}:00 ({metrics['peak_hour_count']:,} messages)")
    print(f"• Peak Day of Week:       {metrics['peak_day']} ({metrics['peak_day_count']:,} messages)")
    print(f"• Night Owl Index:        {metrics['night_owl_pct']}% of entries sent between 10 PM and 4 AM ({metrics['night_owl_count']:,} msgs)")
    print(f"• Morning Reflection:     {metrics['morning_pct']}% of entries sent between 5 AM and 9 AM ({metrics['morning_count']:,} msgs)")
    print(f"• Busiest Single Day:     {metrics['busiest_date']} ({metrics['busiest_date_count']} messages)")
    print("-" * 65)
    print("🎨 GENERATED ASSETS:")
    print(f"  1. [Weekly Heatmap]         {output_path / 'circadian_weekly_heatmap.png'}")
    print(f"  2. [Hourly Distribution]    {output_path / 'hourly_circadian_distribution.png'}")
    print(f"  3. [Longitudinal Shift]     {output_path / 'longitudinal_circadian_shift.png'}")
    print(f"  4. [Interactive Dashboard]  {output_path / 'circadian_report.html'}")
    print("=" * 65)
    print("✨ Analysis complete! Open circadian_report.html in any browser for interactive hover tooltips.")


if __name__ == "__main__":
    main()
