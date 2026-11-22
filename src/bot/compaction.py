"""
Compaction & Cold Storage Consolidation Engine for KayaBot.

Consolidates hot live delta cache (`live_messages.parquet`) into the
historical cold storage archive (`parsed_messages.parquet`), manages
timestamped backup snapshots, and supports safe live delta pruning.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from src.bot.live_sync import (
    _load_delta_df,
    _save_delta_df,
    get_deleted_ids,
    get_live_delta_path,
    get_repo_root,
    load_unified_journal,
)
from src.parser import _sanitize_reactions, load_export, resolve_export_dir


def get_default_backup_dir(export_dir: Optional[Path] = None) -> Path:
    """Return default backup directory for cold storage snapshots."""
    resolved = resolve_export_dir(export_dir) if export_dir else None
    target_dir = resolved if resolved else get_repo_root()
    backup_dir = target_dir / ".cache" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_snapshot_backup(
    export_dir: Optional[Path] = None,
    delta_path: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    tag_prefix: str = "journal_snapshot",
    allow_sample: bool = False,
) -> Path:
    """
    Create a standalone timestamped snapshot of the unified journal dataset.
    Does not modify active cache files.
    """
    resolved_export = resolve_export_dir(export_dir, allow_sample=allow_sample)
    unified = load_unified_journal(resolved_export, delta_path=delta_path, verbose=False, allow_sample=allow_sample)

    dest_dir = backup_dir or (get_repo_root() / "output" / "backups")
    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = dest_dir / f"{tag_prefix}_{timestamp_str}.parquet"

    # Save snapshot
    save_unified = unified.copy()
    if "reactions" in save_unified.columns:
        save_unified["reactions"] = save_unified["reactions"].apply(
            lambda r: json.dumps(r) if isinstance(r, dict) else (r if isinstance(r, str) else "{}")
        )
    save_unified.to_parquet(snapshot_path, index=False)
    return snapshot_path


def consolidate_cache(
    export_dir: Optional[Path] = None,
    delta_path: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    prune_live: bool = False,
    create_snapshot: bool = True,
    verbose: bool = True,
    allow_sample: bool = False,
) -> Dict[str, Any]:
    """
    Consolidate live cache into cold storage (`parsed_messages.parquet`).

    Workflow:
    1. Load unified dataset (historical cold storage + hot live delta).
    2. Create safety backups of existing `parsed_messages.parquet` and `live_messages.parquet`.
    3. Atomically overwrite `parsed_messages.parquet` with the consolidated dataset.
    4. Bump mtime of `parsed_messages.parquet` so parser loads it as authoritative cache.
    5. Optionally prune the consolidated entries from `live_messages.parquet`.
    6. Optionally create an immutable standalone snapshot in `output/backups/`.
    """
    resolved_export = resolve_export_dir(export_dir, allow_sample=allow_sample)
    if resolved_export:
        target_cache_dir = resolved_export / ".cache"
    else:
        target_cache_dir = get_repo_root() / ".cache" / "archive"
    target_cache_dir.mkdir(parents=True, exist_ok=True)
    cold_cache_file = target_cache_dir / "parsed_messages.parquet"

    live_path = delta_path or get_live_delta_path(resolved_export)
    dest_backup_dir = backup_dir or get_default_backup_dir(resolved_export)
    dest_backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. Inspect existing cold storage
    base_count = 0
    cold_backup_path: Optional[Path] = None
    if cold_cache_file.exists():
        try:
            base_df = pd.read_parquet(cold_cache_file)
            base_count = len(base_df)
            cold_backup_path = dest_backup_dir / f"parsed_messages_pre_consolidate_{timestamp_str}.parquet"
            shutil.copy2(cold_cache_file, cold_backup_path)
            if verbose:
                print(f"[Compaction] Backed up active cold cache to {cold_backup_path.name}")
        except Exception as e:
            if verbose:
                print(f"[Compaction] Notice: Failed to copy cold cache backup ({e})")

    # 2. Inspect and backup live delta
    live_count = 0
    live_backup_path: Optional[Path] = None
    if live_path.exists():
        try:
            live_df = _load_delta_df(live_path)
            live_count = len(live_df)
            if live_count > 0:
                live_backup_path = dest_backup_dir / f"live_messages_pre_consolidate_{timestamp_str}.parquet"
                shutil.copy2(live_path, live_backup_path)
                if verbose:
                    print(f"[Compaction] Backed up active live cache ({live_count} entries) to {live_backup_path.name}")
        except Exception as e:
            if verbose:
                print(f"[Compaction] Notice: Failed to copy live delta backup ({e})")

    # 3. Load unified journal
    unified = load_unified_journal(resolved_export, delta_path=live_path, verbose=False)
    total_count = len(unified)

    # Sanitize reactions and total reactions
    if "reactions" in unified.columns:
        unified["reactions"] = unified["reactions"].apply(_sanitize_reactions)
        unified["total_reactions"] = unified["reactions"].apply(lambda r: sum(r.values()) if isinstance(r, dict) else 0)

    # 4. Atomic write to cold storage
    tmp_cold_file = target_cache_dir / f"parsed_messages_tmp_{timestamp_str}.parquet"
    save_unified = unified.copy()
    if "reactions" in save_unified.columns:
        save_unified["reactions"] = save_unified["reactions"].apply(
            lambda r: json.dumps(r) if isinstance(r, dict) else (r if isinstance(r, str) else "{}")
        )
    save_unified.to_parquet(tmp_cold_file, index=False)
    os.replace(tmp_cold_file, cold_cache_file)

    # Ensure mtime is current so parser won't invalidate against HTML files
    now_ts = datetime.datetime.now().timestamp()
    os.utime(cold_cache_file, (now_ts, now_ts))

    if verbose:
        print(f"[Compaction] Successfully consolidated {total_count:,} messages into cold storage: {cold_cache_file}")

    # 5. Optional pruning of live delta
    pruned = False
    if prune_live and live_path.exists() and live_count > 0:
        # Keep any live entries whose IDs are NOT in unified (rare) or reset to empty schema
        empty_delta = live_df.iloc[0:0].copy()
        _save_delta_df(empty_delta, live_path)
        pruned = True
        if verbose:
            print(f"[Compaction] Pruned {live_count} consolidated entries from {live_path.name}. Live buffer reset.")

    # 6. Standalone snapshot
    snapshot_path: Optional[Path] = None
    if create_snapshot:
        snapshot_dir = get_repo_root() / "output" / "backups"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"journal_cold_snapshot_{timestamp_str}.parquet"
        shutil.copy2(cold_cache_file, snapshot_path)
        if verbose:
            print(f"[Compaction] Standalone cold snapshot created at: {snapshot_path}")

    return {
        "status": "success",
        "total_messages": total_count,
        "base_messages_before": base_count,
        "live_messages_merged": max(0, total_count - base_count),
        "cold_cache_path": str(cold_cache_file),
        "cold_backup_path": str(cold_backup_path) if cold_backup_path else None,
        "live_backup_path": str(live_backup_path) if live_backup_path else None,
        "snapshot_path": str(snapshot_path) if snapshot_path else None,
        "pruned_live": pruned,
    }
