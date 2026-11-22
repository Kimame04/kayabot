"""
Unit tests for KayaBot Cold Storage Compaction & Backup Engine.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.bot.compaction import (
    consolidate_cache,
    create_snapshot_backup,
    resolve_export_dir,
)
from src.bot.live_sync import _save_delta_df, load_unified_journal


class TestCompactionEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="test_compaction_"))
        self.export_dir = self.tmp_dir / "ChatExport_test"
        self.cache_dir = self.export_dir / ".cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Create dummy messages.html so load_export recognizes it
        html_file = self.export_dir / "messages.html"
        html_content = """<!DOCTYPE html><html><body>
        <div class="message default clearfix" id="message1">
            <div class="date details" title="15 November 2026 12:00:00">12:00</div>
            <div class="text">Base message 1</div>
        </div>
        </body></html>"""
        html_file.write_text(html_content, encoding="utf-8")

        # Create base cold storage DataFrame
        self.base_df = pd.DataFrame(
            [
                {
                    "id": 1,
                    "timestamp": pd.to_datetime("2026-11-15 12:00:00"),
                    "text": "Base message 1",
                    "char_count": 14,
                    "word_count": 3,
                    "tags": [],
                    "first_tag": None,
                    "reactions": '{"👍": 1}',
                    "total_reactions": 1,
                    "reply_to_id": None,
                    "has_photo": False,
                    "has_media": False,
                    "date": datetime(2026, 11, 15).date(),
                    "year": 2026,
                    "month": 11,
                    "year_month": "2026-11",
                    "day": 15,
                    "day_of_week": 6,
                    "day_name": "Sunday",
                    "hour": 12,
                    "minute": 0,
                }
            ]
        )
        self.cold_file = self.cache_dir / "parsed_messages.parquet"
        self.base_df.to_parquet(self.cold_file, index=False)

        # Create dummy live delta DataFrame
        self.live_file = self.tmp_dir / "live_messages.parquet"
        self.live_df = pd.DataFrame(
            [
                {
                    "id": 2,
                    "timestamp": pd.to_datetime("2026-11-16 10:00:00"),
                    "text": "[bumblebee] Live message 2",
                    "char_count": 26,
                    "word_count": 4,
                    "tags": ["bumblebee"],
                    "first_tag": "bumblebee",
                    "reactions": {"🔥": 1},
                    "total_reactions": 1,
                    "reply_to_id": None,
                    "has_photo": True,
                    "has_media": True,
                    "date": datetime(2026, 11, 16).date(),
                    "year": 2026,
                    "month": 11,
                    "year_month": "2026-11",
                    "day": 16,
                    "day_of_week": 0,
                    "day_name": "Monday",
                    "hour": 10,
                    "minute": 0,
                    "media_file_name": "photo.jpg",
                }
            ]
        )
        _save_delta_df(self.live_df, self.live_file)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_snapshot_backup(self) -> None:
        """Verify standalone snapshot creates a readable parquet file."""
        backup_dir = self.tmp_dir / "snapshots"
        snapshot = create_snapshot_backup(
            export_dir=self.export_dir,
            delta_path=self.live_file,
            backup_dir=backup_dir,
        )
        self.assertTrue(snapshot.exists())
        self.assertTrue(snapshot.name.endswith(".parquet"))

        df = pd.read_parquet(snapshot)
        self.assertEqual(len(df), 2)
        self.assertIn("bumblebee", df["tags"].iloc[1])

    def test_consolidate_cache(self) -> None:
        """Verify consolidation merges live cache into cold storage with backups."""
        backup_dir = self.tmp_dir / "backups"
        res = consolidate_cache(
            export_dir=self.export_dir,
            delta_path=self.live_file,
            backup_dir=backup_dir,
            prune_live=False,
            create_snapshot=True,
            verbose=False,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_messages"], 2)
        self.assertEqual(res["base_messages_before"], 1)
        self.assertEqual(res["live_messages_merged"], 1)

        # Check that cold storage now contains 2 messages
        reloaded_cold = pd.read_parquet(self.cold_file)
        self.assertEqual(len(reloaded_cold), 2)
        self.assertEqual(list(reloaded_cold["id"]), [1, 2])

        # Check backup files exist
        self.assertTrue(Path(res["cold_backup_path"]).exists())
        self.assertTrue(Path(res["live_backup_path"]).exists())
        self.assertTrue(Path(res["snapshot_path"]).exists())

        # Check live file was NOT pruned when prune_live=False
        live_after = pd.read_parquet(self.live_file)
        self.assertEqual(len(live_after), 1)

    def test_consolidate_cache_with_prune(self) -> None:
        """Verify consolidation resets the live buffer when prune_live=True."""
        backup_dir = self.tmp_dir / "backups"
        res = consolidate_cache(
            export_dir=self.export_dir,
            delta_path=self.live_file,
            backup_dir=backup_dir,
            prune_live=True,
            create_snapshot=False,
            verbose=False,
        )

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["pruned_live"])

        # Cold storage has both messages
        reloaded_cold = pd.read_parquet(self.cold_file)
        self.assertEqual(len(reloaded_cold), 2)

        # Live buffer should now be empty
        reloaded_live = pd.read_parquet(self.live_file)
        self.assertEqual(len(reloaded_live), 0)

    def test_no_sample_pollution(self) -> None:
        """Verify resolve_export_dir never silently falls back to sample in production."""
        empty_root = self.tmp_dir / "empty_workspace"
        empty_root.mkdir()
        (empty_root / "ChatExport_sample").mkdir()

        # In empty workspace without allow_sample, must NOT resolve to sample
        from unittest.mock import patch
        with patch("src.bot.compaction.get_repo_root", return_value=empty_root):
            self.assertIsNone(resolve_export_dir(allow_sample=False))
            self.assertEqual(resolve_export_dir(allow_sample=True), empty_root / "ChatExport_sample")

        # In empty workspace with live delta only, load_unified_journal serves live messages only
        with patch("src.parser.get_repo_root", return_value=empty_root), patch("src.bot.live_sync.resolve_export_dir", return_value=None):
            unified = load_unified_journal(export_dir=None, delta_path=self.live_file, allow_sample=False)
            self.assertEqual(len(unified), 1)
            self.assertEqual(unified["id"].iloc[0], 2)


if __name__ == "__main__":
    unittest.main()
