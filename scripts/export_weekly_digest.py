#!/usr/bin/env python3
"""
CLI runner to extract, filter, and format weekly Telegram journal digests.

Usage:
    python -m scripts.export_weekly_digest
    python -m scripts.export_weekly_digest --week 2026-48
    python -m scripts.export_weekly_digest --date 2026-11-20
    python -m scripts.export_weekly_digest --format json --out-dir output/digest
    python -m scripts.export_weekly_digest --export-dir ChatExport_sample
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
import sys
from typing import Optional, Tuple

from src.bot.live_sync import load_unified_journal
from src.digest import (
    build_weekly_digest,
    export_digest,
    format_week_label,
    get_previous_week_bounds,
    get_sunday_start_bounds,
    parse_week_label,
    week_bounds_from_label,
)


def _resolve_default_export_dir() -> Path:
    """Find the best default export folder across private and synthetic environments."""
    for candidate in [Path("ChatExport_kieran's channel"), Path("ChatExport_sample")]:
        if candidate.exists() and (candidate / "messages.html").exists():
            return candidate
    return Path("ChatExport_sample")


def _resolve_target_window(
    week_arg: Optional[str],
    date_arg: Optional[str],
    df_max_date: Optional[date] = None,
) -> Tuple[date, date, str]:
    """
    Resolves the start date (Sunday), end date (Saturday), and week label
    based on CLI options or defaults.
    """
    if week_arg:
        sun, sat, label = week_bounds_from_label(week_arg)
        return sun, sat, label

    if date_arg:
        date_str = date_arg.strip().lower()
        if date_str in ("today", "now"):
            target_date = date.today()
        elif date_str == "yesterday":
            target_date = date.today() - datetime.timedelta(days=1)
        else:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        sun, sat = get_sunday_start_bounds(target_date)
        label = format_week_label(sun)
        return sun, sat, label

    # Default fallback: If today is Sunday or Monday, get the week that just ended.
    # If working on a static archive, use the max date present in the dataset.
    today = date.today()
    if df_max_date and df_max_date.year < today.year - 1:
        # Static historical dataset (e.g. sample benchmark)
        sun, sat = get_sunday_start_bounds(df_max_date)
    else:
        sun, sat = get_previous_week_bounds(today)

    label = format_week_label(sun)
    return sun, sat, label


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract and export a Sunday-to-Saturday weekly journal digest from Telegram history."
    )
    parser.add_argument(
        "--week",
        "-w",
        type=str,
        default=None,
        help="Target week label in 'YYYY-WW' format (e.g., '2026-48').",
    )
    parser.add_argument(
        "--date",
        "-d",
        type=str,
        default=None,
        help="Target date ('YYYY-MM-DD', 'today', 'yesterday'). Resolves containing Sunday-to-Saturday week.",
    )
    parser.add_argument(
        "--format",
        "-f",
        type=str,
        choices=["all", "json", "md"],
        default="all",
        help="Export format: 'all' (default), 'json', or 'md'.",
    )
    parser.add_argument(
        "--out-dir",
        "-o",
        type=str,
        default="output/digest",
        help="Output directory to save exported artifacts (default: 'output/digest').",
    )
    parser.add_argument(
        "--export-dir",
        "-i",
        type=str,
        default=None,
        help="Path to Telegram export folder. Auto-detects if omitted.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass Parquet cache and force re-parsing HTML exports.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress terminal output summary.",
    )

    args = parser.parse_args()

    # 1. Resolve export directory
    export_dir = Path(args.export_dir) if args.export_dir else _resolve_default_export_dir()
    if not export_dir.exists():
        print(f"❌ Error: Export directory not found: {export_dir}", file=sys.stderr)
        sys.exit(1)

    # 2. Ingest export (historical + live delta)
    try:
        df = load_unified_journal(export_dir, verbose=not args.quiet)
    except Exception as e:
        print(f"❌ Error loading export data: {e}", file=sys.stderr)
        sys.exit(1)

    if df.empty:
        print("❌ Error: No messages found in export.", file=sys.stderr)
        sys.exit(1)

    # 3. Resolve target window
    df_max_date = df["date"].max() if "date" in df.columns else None
    try:
        start_date, end_date, week_label = _resolve_target_window(
            week_arg=args.week,
            date_arg=args.date,
            df_max_date=df_max_date,
        )
    except Exception as e:
        print(f"❌ Error resolving week bounds: {e}", file=sys.stderr)
        sys.exit(1)

    # 4. Build weekly digest
    try:
        digest = build_weekly_digest(
            df=df,
            start_date=start_date,
            end_date=end_date,
            label=week_label,
        )
    except Exception as e:
        print(f"❌ Error building weekly digest: {e}", file=sys.stderr)
        sys.exit(1)

    # 5. Export to disk
    formats = ["json", "md"] if args.format == "all" else [args.format]
    out_dir_path = Path(args.out_dir)
    written_files = export_digest(digest, out_dir=out_dir_path, formats=formats)

    # 6. Terminal Summary (unless --quiet)
    if not args.quiet:
        print("\n" + "=" * 60)
        print(f"  🧩 Weekly Journal Digest: {digest.label}")
        print("=" * 60)
        print(f"  📅 Period:       {digest.start_date} (Sun) → {digest.end_date} (Sat)")
        print(f"  📝 Reflections:  {digest.total_messages:,} entries across {digest.active_days}/7 days")
        print(f"  ✍️ Total Words:  {digest.total_words:,}")
        print(f"  📷 Photos:       {digest.total_photos}")
        if digest.all_tags:
            top_tags = ", ".join(f"[{t}] ({c})" for t, c in digest.all_tags[:6])
            print(f"  🏷️ Top Topics:   {top_tags}")

        print("\n  📆 Daily Activity:")
        for day in digest.days:
            bullet = "🟢" if day.total_messages > 0 else "⚪"
            media_indicator = f" ({day.total_words} words, 📷 {sum(1 for e in day.entries if e.has_photo)})" if day.total_messages > 0 else ""
            print(f"    {bullet} {day.day_name:<9} ({day.date_str}): {day.total_messages} entries{media_indicator}")

        if digest.tagged_groups:
            print(f"\n  🔀 Routed Tags ({len(digest.tagged_groups)}):")
            for tag, entries in digest.tagged_groups.items():
                print(f"    • [{tag}]: {len(entries)} reflection(s)")

        print("\n  💾 Exported Artifacts:")
        for fmt, path in written_files.items():
            print(f"    - {fmt.upper()}: {path}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
