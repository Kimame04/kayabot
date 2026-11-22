#!/usr/bin/env python3
"""
CLI runner for Tag & Hobby Lifecycles analysis.

Usage:
    python -m scripts.run_tag_lifecycles
    python -m scripts.run_tag_lifecycles --export-dir "path/to/any/ChatExport_folder" --output-dir "output/lifecycles"
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.parser import load_export, resolve_export_dir
from src.lifecycle import generate_lifecycle_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze and visualize tag and hobby lifecycles from personal Telegram channel journal exports."
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
        default="output/lifecycles",
        help="Directory to save generated charts and HTML report (default: 'output/lifecycles')",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=16,
        help="Number of top tags to feature in the streamgraph (default: 16)",
    )
    parser.add_argument(
        "--min-msgs",
        type=int,
        default=5,
        help="Minimum message count required to track a tag (default: 5)",
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
    print("🎨 TELEGRAM JOURNAL - TAG & HOBBY LIFECYCLES")
    print("=" * 65)
    print(f"📁 Target Export:  {export_path.resolve()}")
    print(f"📊 Output Dir:     {output_path.resolve()}")
    print(f"🎯 Top N Tags:     {args.top_n}")
    print(f"🔍 Min Mentions:   {args.min_msgs}")
    print("-" * 65)

    # 1. Load data via universal parser
    df = load_export(export_path, use_cache=not args.no_cache, verbose=not args.quiet)

    # 2. Run lifecycle pipeline
    print("\n[Analysis] Computing tag lifecycles, streams, and Gantt charts...")
    summary = generate_lifecycle_report(
        df,
        output_dir_path=output_path,
        top_n=args.top_n,
        min_count=args.min_msgs,
    )

    # 3. Print summary insights
    print("\n" + "=" * 65)
    print("📌 KEY LIFECYCLE INSIGHTS")
    print("=" * 65)
    print(f"• Total Tracked Tags (>= {args.min_msgs} msgs): {summary['total_tags_analyzed']}")
    print(f"• #1 Most Mentioned Tag:       [{summary['top_tag']}] ({summary['top_tag_count']} messages)")
    print(f"\n🌟 Evergreen Passions (>1 year, steady):")
    for t in summary["evergreens"][:8]:
        print(f"   - [{t}]")
    print(f"\n⚡ Seasonal Hyperfixations (1–4 months burst):")
    for t in summary["bursts"][:8]:
        print(f"   - [{t}]")
    print(f"\n🌱 Emerging Eras (Started 2025/2026 & Active):")
    for t in summary["emerging"][:8]:
        print(f"   - [{t}]")
    print("-" * 65)
    print("🎨 GENERATED ASSETS:")
    print(f"  1. [Hobby Streamgraph]      {output_path / 'tag_streamgraph.png'}")
    print(f"  2. [Lifespan Gantt Chart]   {output_path / 'tag_lifespans_gantt.png'}")
    print(f"  3. [Monthly Turnover Matrix]{output_path / 'tag_monthly_heatmap.png'}")
    print(f"  4. [Interactive Explorer]   {output_path / 'tag_lifecycle_report.html'}")
    print("=" * 65)
    print("✨ Analysis complete! Open tag_lifecycle_report.html to interact with your hobby streams.")


if __name__ == "__main__":
    main()
