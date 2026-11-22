#!/usr/bin/env python3
"""
CLI runner for Channel-Wrapped retrospective analytics.

Usage:
    python -m scripts.run_wrapped
    python -m scripts.run_wrapped --year 2024
    python -m scripts.run_wrapped --all-time
    python -m scripts.run_wrapped --export-dir "ChatExport_sample"
    python -m scripts.run_wrapped --no-html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from src.parser import load_export, resolve_export_dir
from src.wrapped import (
    compute_wrapped,
    render_wrapped_terminal,
    generate_wrapped_html,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an annual or all-time Spotify Wrapped-style retrospective for your Telegram journal."
    )
    parser.add_argument(
        "--year",
        "-y",
        type=int,
        default=None,
        help="Specific year to summarize (e.g. 2024). Defaults to the most recent active year in the dataset.",
    )
    parser.add_argument(
        "--all-time",
        "-a",
        action="store_true",
        help="Generate an All-Time retrospective across all recorded years.",
    )
    parser.add_argument(
        "--export-dir",
        "-i",
        type=str,
        default=None,
        help="Path to Telegram ChatExport directory (auto-detects if omitted).",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="output/wrapped",
        help="Directory to save the interactive HTML story deck (default: 'output/wrapped').",
    )
    parser.add_argument(
        "--no-html",
        dest="html",
        action="store_false",
        help="Skip generating HTML report and display terminal summary only.",
    )
    parser.set_defaults(html=True)
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass Parquet cache and force re-parsing of raw HTML files.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress parser diagnostic logs.",
    )

    args = parser.parse_args()

    # 1. Resolve export directory
    export_path = resolve_export_dir(args.export_dir)

    output_dir = Path(args.output_dir)

    # 2. Ingest journal data
    df = load_export(export_path, use_cache=not args.no_cache, verbose=not args.quiet)
    if df.empty:
        print(f"❌ Error: No messages found in '{export_path}'. Please check export folder.")
        sys.exit(1)

    # 3. Determine target year or all-time
    available_years = sorted(df["year"].dropna().unique().astype(int).tolist())
    target_year: Optional[int] = None

    if args.all_time:
        target_year = None
    elif args.year is not None:
        if args.year not in available_years:
            print(f"⚠️  Warning: Year {args.year} not found in dataset. Available years: {available_years}")
        target_year = args.year
    else:
        # Default to latest active year
        target_year = available_years[-1] if available_years else None

    # 4. Compute Wrapped metrics
    wrapped_data = compute_wrapped(df, year=target_year)

    # 5. Output terminal cards
    terminal_summary = render_wrapped_terminal(wrapped_data)
    print(terminal_summary)

    # 6. Generate interactive HTML story deck
    if args.html:
        output_dir.mkdir(parents=True, exist_ok=True)
        file_suffix = str(target_year) if target_year is not None else "all_time"
        html_file = output_dir / f"wrapped_{file_suffix}.html"
        generate_wrapped_html(wrapped_data, html_file)
        print(f"✨ Interactive Story Deck generated: {html_file.resolve()}")
        print(f"💡 Open in your browser: file://{html_file.resolve()}")


if __name__ == "__main__":
    main()
