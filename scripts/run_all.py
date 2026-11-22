#!/usr/bin/env python3
"""
Master Orchestrator CLI for Telegram Journal Analytics.

Runs all analytical pipelines (Circadian, Tag Lifecycles, Channel-Wrapped,
and On-This-Day Time Capsule) in a single unified execution and compiles
a comprehensive, interactive, standalone HTML master dashboard.

Usage:
    python -m scripts.run_all
    python -m scripts.run_all --export-dir "path/to/ChatExport" --open
    python -m scripts.run_all --all-reports
"""

from __future__ import annotations

import argparse
from pathlib import Path
import webbrowser

from src.parser import load_export, resolve_export_dir
from src.dashboard import generate_dashboard


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Master Orchestrator: Generate a unified all-in-one HTML dossier from personal Telegram channel exports."
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
        default="output",
        help="Directory to save the generated dashboard and reports (default: 'output')",
    )
    parser.add_argument(
        "--dashboard-name",
        type=str,
        default="dashboard.html",
        help="Filename for the unified master dashboard (default: 'dashboard.html')",
    )
    parser.add_argument(
        "--year",
        "-y",
        type=int,
        default=None,
        help="Specific year for retrospective metrics (default: all-time or latest active year)",
    )
    parser.add_argument(
        "--all-time",
        action="store_true",
        help="Force all-time retrospective scope regardless of year",
    )
    parser.add_argument(
        "--date",
        "-d",
        type=str,
        default=None,
        help="Target date for On-This-Day (default: today, with auto-fallback to active past date if empty)",
    )
    parser.add_argument(
        "--window",
        "-w",
        type=int,
        default=0,
        help="Window radius in days around target date for On-This-Day (default: 0)",
    )
    parser.add_argument(
        "--all-reports",
        action="store_true",
        help="Also generate individual standalone reports (circadian, lifecycles, wrapped, otd) alongside master dashboard",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Automatically open the generated dashboard in your default web browser",
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
    output_dir = Path(args.output_dir)
    dashboard_path = output_dir / args.dashboard_name

    target_year = None if args.all_time else args.year

    print("=" * 68)
    print("🌌 TELEGRAM JOURNAL ANALYTICS — MASTER DOSSIER ORCHESTRATOR")
    print("=" * 68)
    print(f"📁 Target Export:    {export_path.resolve()}")
    print(f"📊 Dashboard Output: {dashboard_path.resolve()}")
    print(f"⚡ Fast Cache:       {not args.no_cache}")
    if target_year:
        print(f"📅 Wrapped Scope:    Year {target_year}")
    else:
        print(f"📅 Wrapped Scope:    All-Time History")
    print("-" * 68)

    # 1. Load data once via high-speed parser & cache
    df = load_export(export_path, use_cache=not args.no_cache, verbose=not args.quiet)

    # 2. Generate unified dashboard
    print("\n[Dashboard] Running analytical models & generating unified dashboard...")
    data, out_file = generate_dashboard(
        df,
        output_path=dashboard_path,
        year=target_year,
        otd_date=args.date,
        window_days=args.window,
    )

    # 3. Optional: generate standalone individual reports
    if args.all_reports:
        print("\n[Orchestrator] Generating individual feature reports (--all-reports)...")
        from src.circadian import generate_circadian_report
        from src.lifecycle import generate_lifecycle_report
        from src.wrapped import generate_wrapped_html
        from src.otd import generate_otd_html

        circadian_dir = output_dir / "circadian"
        generate_circadian_report(df, circadian_dir)
        print(f"  • Circadian Report:   {circadian_dir / 'circadian_report.html'}")

        lifecycle_dir = output_dir / "lifecycles"
        generate_lifecycle_report(df, lifecycle_dir)
        print(f"  • Lifecycle Report:   {lifecycle_dir / 'tag_lifecycle_report.html'}")

        wrapped_file = output_dir / "wrapped" / f"wrapped_{data.wrapped_data.period_label.lower().replace(' ', '_')}.html"
        generate_wrapped_html(data.wrapped_data, wrapped_file)
        print(f"  • Wrapped Deck:       {wrapped_file}")

        otd_file = output_dir / "otd" / "on_this_day.html"
        generate_otd_html(data.otd_result, otd_file)
        print(f"  • On This Day Card:   {otd_file}")

    # 4. Print summary briefing
    p = data.wrapped_data.persona
    print("\n" + "=" * 68)
    print("📋 MASTER DOSSIER SUMMARY BRIEFING")
    print("=" * 68)
    print(f"• Total Messages:        {data.total_messages:,} entries ({data.total_words:,} words)")
    print(f"• Reading Metaphor:      ~{data.book_pages:.1f} book pages (~{data.reading_time_mins} min read)")
    print(f"• Active Consistency:    {data.active_days} active days ({data.active_days_pct}%)")
    print(f"• Daily Streak Record:   {data.longest_streak_days} consecutive days")
    print(f"• Peak Activity Hour:    {data.circadian_metrics['peak_hour']:02d}:00 ({data.circadian_metrics['peak_hour_count']:,} msgs)")
    print(f"• Night Owl Share:       {data.circadian_metrics['night_owl_pct']}% (10 PM – 4 AM)")
    print(f"• Circadian Persona:     {p.emoji} {p.name}")
    print(f"• Top Tracked Interest:  [{data.lifecycle_summary['top_tag']}] ({data.lifecycle_summary['top_tag_count']:,} mentions)")
    print(f"• On This Day Flashback: {data.otd_result.date_title} ({data.otd_result.total_matches} memories)")
    print("-" * 68)
    print(f"✨ Master Dashboard generated successfully!")
    print(f"🌐 Local File URI: file://{out_file}")
    print("=" * 68)

    # 5. Open in browser if requested
    if args.open:
        print(f"🚀 Launching dashboard in browser...")
        webbrowser.open(out_file.as_uri())


if __name__ == "__main__":
    main()
