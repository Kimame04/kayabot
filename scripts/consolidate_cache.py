#!/usr/bin/env python3
"""
Consolidate Live Cache into Cold Storage Archive & Backup CLI.

Merges live messages (`live_messages.parquet`) into cold storage
(`parsed_messages.parquet`), creates timestamped backup snapshots,
and optionally prunes the live buffer.

Usage:
    # Full consolidation into cold storage with backup:
    python -m scripts.consolidate_cache

    # Consolidate and prune live buffer:
    python -m scripts.consolidate_cache --prune-live

    # Only create a standalone timestamped backup snapshot:
    python -m scripts.consolidate_cache --snapshot-only

    # Target specific export directory:
    python -m scripts.consolidate_cache --export-dir "path/to/ChatExport_channel"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.compaction import consolidate_cache, create_snapshot_backup, resolve_export_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consolidate KayaBot live delta cache into cold storage and generate backup snapshots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--export-dir",
        type=str,
        default=None,
        help="Path to Telegram chat export directory (auto-detected if omitted).",
    )
    parser.add_argument(
        "--delta-path",
        type=str,
        default=None,
        help="Custom path to live_messages.parquet file.",
    )
    parser.add_argument(
        "--prune-live",
        action="store_true",
        help="Prune/reset the live delta buffer after successful consolidation.",
    )
    parser.add_argument(
        "--snapshot-only",
        action="store_true",
        help="Only create a standalone backup snapshot without modifying parsed_messages.parquet.",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Custom output directory for snapshots.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational stdout output.",
    )

    args = parser.parse_args()

    export_path = Path(args.export_dir) if args.export_dir else None
    delta_path = Path(args.delta_path) if args.delta_path else None
    out_dir = Path(args.out_dir) if args.out_dir else None
    verbose = not args.quiet

    try:
        resolved_export = resolve_export_dir(export_path)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.snapshot_only:
        if verbose:
            print(f"📦 Creating standalone backup snapshot from: {resolved_export.name}...")
        snapshot = create_snapshot_backup(
            export_dir=resolved_export,
            delta_path=delta_path,
            backup_dir=out_dir,
        )
        if verbose:
            print(f"✅ Backup snapshot created: {snapshot}")
        return

    if verbose:
        print("============================================================")
        print("  ❄️ KayaBot Cold Storage Compaction & Backup Engine")
        print("============================================================")
        print(f"  📁 Target Export:  {resolved_export.name}")
        if args.prune_live:
            print("  ✂️ Mode:           Consolidate + Prune Live Delta Buffer")
        else:
            print("  📥 Mode:           Consolidate (Keep Live Buffer)")
        print("============================================================")

    res = consolidate_cache(
        export_dir=resolved_export,
        delta_path=delta_path,
        backup_dir=out_dir,
        prune_live=args.prune_live,
        create_snapshot=True,
        verbose=verbose,
    )

    if verbose:
        print("\n============================================================")
        print("  🎉 Compaction Completed Successfully!")
        print("============================================================")
        print(f"  📊 Total Messages in Cold Storage: {res['total_messages']:,}")
        print(f"  📈 Live Messages Merged:           {res['live_messages_merged']:,}")
        print(f"  💾 Active Cold Storage File:       {res['cold_cache_path']}")
        if res.get("cold_backup_path"):
            print(f"  🛡️ Pre-compaction Cold Backup:    {res['cold_backup_path']}")
        if res.get("live_backup_path"):
            print(f"  🛡️ Pre-compaction Live Backup:    {res['live_backup_path']}")
        if res.get("snapshot_path"):
            print(f"  📦 Standalone Snapshot:            {res['snapshot_path']}")
        print(f"  🧹 Live Delta Buffer Pruned:       {res['pruned_live']}")
        print("============================================================\n")


if __name__ == "__main__":
    main()
