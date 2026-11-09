"""
Unit tests for Live Channel Ingestion and Delta Sync.
Verifies post parsing, Parquet delta storage, edit updates, and unified dataset merging.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

import pandas as pd

from src.bot.client import TelegramClient
from src.bot.config import BotConfig
from src.bot.handlers import BotDispatcher
from src.bot.live_sync import (
    _save_delta_df,
    ingest_channel_post,
    load_unified_journal,
    parse_channel_post,
)


class TestLiveSync(unittest.TestCase):
    def test_parse_channel_post(self):
        sample_post = {
            "message_id": 501,
            "date": 1729684800,  # 2024-10-23 12:00:00 UTC
            "chat": {
                "id": -1001987654321,
                "title": "Kieran Journal",
                "type": "channel"
            },
            "text": "Finished testing the live subsea autonomous sync! [robotics] [ros2]",
            "photo": [{"file_id": "photo_123"}]
        }

        row = parse_channel_post(sample_post)
        self.assertEqual(row["id"], 501)
        self.assertIn("robotics", row["tags"])
        self.assertIn("ros2", row["tags"])
        self.assertEqual(row["first_tag"], "robotics")
        self.assertEqual(row["word_count"], 9)
        self.assertTrue(row["has_photo"])
        self.assertFalse(row["has_media"])
        self.assertEqual(row["year"], 2024)
        self.assertEqual(row["month"], 10)
        self.assertEqual(row["day"], 23)
        self.assertFalse(row["is_forwarded"])
        self.assertIsNone(row["forward_source_name"])

    def test_parse_forwarded_post_bot_api_7(self):
        # 1. Channel origin with username and message_id
        post_channel = {
            "message_id": 502,
            "date": 1729684800,
            "chat": {"id": -1001987654321, "type": "channel"},
            "text": "Great article on autonomous systems [robotics]",
            "forward_origin": {
                "type": "channel",
                "chat": {"id": -100999, "title": "Tech Dispatch", "username": "techdispatch"},
                "message_id": 42,
                "date": 1729680000,
            },
        }
        row = parse_channel_post(post_channel)
        self.assertTrue(row["is_forwarded"])
        self.assertEqual(row["forward_source_type"], "channel")
        self.assertEqual(row["forward_source_name"], "Tech Dispatch")
        self.assertEqual(row["forward_source_url"], "https://t.me/techdispatch/42")
        self.assertIsNotNone(row["forward_date"])

        # 2. User origin
        post_user = {
            "message_id": 503,
            "date": 1729684800,
            "chat": {"id": -1001987654321, "type": "channel"},
            "text": "Check this note out",
            "forward_origin": {
                "type": "user",
                "sender_user": {"first_name": "Alice", "last_name": "Smith", "username": "alicesmith"},
                "date": 1729681000,
            },
        }
        row_user = parse_channel_post(post_user)
        self.assertTrue(row_user["is_forwarded"])
        self.assertEqual(row_user["forward_source_type"], "user")
        self.assertEqual(row_user["forward_source_name"], "Alice Smith")
        self.assertEqual(row_user["forward_source_url"], "https://t.me/alicesmith")

        # 3. Hidden user origin
        post_hidden = {
            "message_id": 504,
            "date": 1729684800,
            "chat": {"id": -1001987654321, "type": "channel"},
            "text": "Anonymous snippet",
            "forward_origin": {
                "type": "hidden_user",
                "sender_user_name": "Secret Contributor",
                "date": 1729682000,
            },
        }
        row_hidden = parse_channel_post(post_hidden)
        self.assertTrue(row_hidden["is_forwarded"])
        self.assertEqual(row_hidden["forward_source_type"], "hidden_user")
        self.assertEqual(row_hidden["forward_source_name"], "Secret Contributor")
        self.assertIsNone(row_hidden["forward_source_url"])

    def test_parse_forwarded_post_legacy(self):
        post_legacy = {
            "message_id": 505,
            "date": 1729684800,
            "chat": {"id": -1001987654321, "type": "channel"},
            "text": "Legacy forwarded message",
            "forward_date": 1729670000,
            "forward_from_chat": {
                "id": -100888,
                "title": "Old News Channel",
                "username": "oldnews",
                "type": "channel",
            },
            "forward_from_message_id": 99,
        }
        row = parse_channel_post(post_legacy)
        self.assertTrue(row["is_forwarded"])
        self.assertEqual(row["forward_source_name"], "Old News Channel")
        self.assertEqual(row["forward_source_url"], "https://t.me/oldnews/99")
        self.assertIsNotNone(row["forward_date"])

    def test_ingest_and_edit_channel_post(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            delta_file = Path(tmp_dir) / "test_live_messages.parquet"

            post1 = {
                "message_id": 1001,
                "date": 1729684800,
                "chat": {"id": -1001234567890, "type": "channel"},
                "text": "Initial reflection before lunch. [work]"
            }

            # 1. First ingestion
            row1, is_new1 = ingest_channel_post(post1, delta_path=delta_file)
            self.assertTrue(is_new1)
            self.assertTrue(delta_file.exists())

            df1 = pd.read_parquet(delta_file)
            self.assertEqual(len(df1), 1)
            self.assertEqual(df1.iloc[0]["id"], 1001)
            self.assertIn("Initial reflection", df1.iloc[0]["text"])

            # 2. Edit of the same post
            post1_edited = {
                "message_id": 1001,
                "date": 1729684900,
                "chat": {"id": -1001234567890, "type": "channel"},
                "text": "Edited reflection after lunch! [work] [food]"
            }
            row1_edit, is_new2 = ingest_channel_post(post1_edited, delta_path=delta_file)
            self.assertFalse(is_new2, "Existing ID edit should not be marked as new")

            df2 = pd.read_parquet(delta_file)
            self.assertEqual(len(df2), 1, "Should upsert in place without duplicating row")
            self.assertIn("Edited reflection after lunch", df2.iloc[0]["text"])
            self.assertIn("food", df2.iloc[0]["tags"])

            # 3. New separate post
            post2 = {
                "message_id": 1002,
                "date": 1729685000,
                "chat": {"id": -1001234567890, "type": "channel"},
                "text": "Evening reflection. [reading]"
            }
            row2, is_new3 = ingest_channel_post(post2, delta_path=delta_file)
            self.assertTrue(is_new3)

            df3 = pd.read_parquet(delta_file)
            self.assertEqual(len(df3), 2)

    def test_load_unified_journal_deduplication(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            delta_file = tmp_path / "live.parquet"

            # Create mock live delta with an updated entry #100 and a new entry #200
            live_rows = [
                {
                    "id": 100,
                    "timestamp": pd.to_datetime("2024-10-23 14:00:00"),
                    "text": "Overwritten version of post 100",
                    "word_count": 5,
                    "char_count": 31,
                    "tags": ["updated"],
                    "first_tag": "updated",
                    "reactions": {},
                    "total_reactions": 0,
                    "reply_to_id": None,
                    "has_photo": False,
                    "has_media": False,
                    "date": datetime(2024, 10, 23).date(),
                    "year": 2024,
                    "month": 10,
                    "year_month": "2024-10",
                    "day": 23,
                    "day_of_week": 2,
                    "day_name": "Wednesday",
                    "hour": 14,
                    "minute": 0,
                },
                {
                    "id": 200,
                    "timestamp": pd.to_datetime("2024-10-23 15:00:00"),
                    "text": "Completely new live entry 200",
                    "word_count": 5,
                    "char_count": 28,
                    "tags": ["new"],
                    "first_tag": "new",
                    "reactions": {},
                    "total_reactions": 0,
                    "reply_to_id": None,
                    "has_photo": False,
                    "has_media": False,
                    "date": datetime(2024, 10, 23).date(),
                    "year": 2024,
                    "month": 10,
                    "year_month": "2024-10",
                    "day": 23,
                    "day_of_week": 2,
                    "day_name": "Wednesday",
                    "hour": 15,
                    "minute": 0,
                }
            ]
            _save_delta_df(pd.DataFrame(live_rows), delta_file)

            # Use synthetic sample as base export
            sample_dir = Path(__file__).resolve().parent.parent / "ChatExport_sample"
            if not sample_dir.exists():
                self.skipTest("ChatExport_sample not found.")

            unified_df = load_unified_journal(sample_dir, delta_path=delta_file)
            self.assertFalse(unified_df.empty)
            self.assertIn(200, unified_df["id"].values)
            matching_100 = unified_df[unified_df["id"] == 100]
            if not matching_100.empty:
                self.assertEqual(matching_100.iloc[0]["text"], "Overwritten version of post 100")

    def test_bot_dispatcher_channel_post_filtering(self):
        client = MagicMock()
        config = BotConfig(bot_token="test_tok", chat_id="123", channel_id="-100123")
        initial_df = pd.DataFrame([{
            "id": 1,
            "timestamp": pd.to_datetime("2024-01-01 10:00:00"),
            "text": "First post",
            "word_count": 2,
            "char_count": 10,
            "tags": [],
            "first_tag": None,
            "reactions": {},
            "total_reactions": 0,
            "reply_to_id": None,
            "has_photo": False,
            "has_media": False,
            "date": datetime(2024, 1, 1).date(),
            "year": 2024,
            "month": 1,
            "year_month": "2024-01",
            "day": 1,
            "day_of_week": 0,
            "day_name": "Monday",
            "hour": 10,
            "minute": 0,
        }])

        with tempfile.TemporaryDirectory() as tmp_dir:
            delta_path = Path(tmp_dir) / "dispatcher_delta.parquet"
            dispatcher = BotDispatcher(client, config, initial_df, delta_path=delta_path)

            # 1. Post from unauthorized channel
            rogue_post = {
                "message_id": 99,
                "date": 1729684800,
                "chat": {"id": -100999999, "type": "channel"},
                "text": "Ignored spam post"
            }
            res_rogue = dispatcher.handle_channel_post(rogue_post)
            self.assertIsNone(res_rogue)
            self.assertEqual(len(dispatcher.df), 1)

            # 2. Post from designated channel
            valid_post = {
                "message_id": 2,
                "date": 1729685800,
                "chat": {"id": -100123, "type": "channel"},
                "text": "Legit journal thought [mai]"
            }
            res_valid = dispatcher.handle_channel_post(valid_post)
            self.assertIsNotNone(res_valid)
            self.assertEqual(len(dispatcher.df), 2)
            self.assertIn("mai", dispatcher.df.iloc[-1]["tags"])

    def test_unauthorized_user_dm_blocked(self):
        client = MagicMock()
        config = BotConfig(bot_token="test_tok", chat_id="12345")  # Kieran's ID is 12345
        dispatcher = BotDispatcher(client, config, pd.DataFrame())

        # Stranger attempts /otd command
        stranger_msg = {
            "chat": {"id": 99999},
            "from": {"id": 99999, "first_name": "Stranger"},
            "text": "/otd"
        }
        dispatcher.dispatch_message(stranger_msg)

        # Verify client sent Access Denied message
        client.send_message.assert_called_once()
        args = client.send_message.call_args[0]
        self.assertEqual(args[0], 99999)
        self.assertIn("Access Denied", args[1])

    def test_parse_channel_post_suppression_tag(self):
        # 1. Post with [nowh] (default suppression tag)
        post_suppressed = {
            "message_id": 601,
            "date": 1729684800,
            "text": "[nowh] A confidential thought about the roadmap.",
        }
        row = parse_channel_post(post_suppressed, suppress_tags=["nowh"], strip_suppress_tags=True)
        self.assertTrue(row["skip_discord"])
        self.assertEqual(row["text"], "A confidential thought about the roadmap.")
        self.assertEqual(row["tags"], [])
        self.assertIsNone(row["first_tag"])
        self.assertEqual(row["word_count"], 6)

        # 2. Post with [nowh] and other topic tags
        post_mixed = {
            "message_id": 602,
            "date": 1729684800,
            "text": "[reading] Finished chapter 5 [nowh] and feeling inspired",
        }
        row_mixed = parse_channel_post(post_mixed, suppress_tags=["nowh"], strip_suppress_tags=True)
        self.assertTrue(row_mixed["skip_discord"])
        self.assertEqual(row_mixed["text"], "[reading] Finished chapter 5 and feeling inspired")
        self.assertEqual(row_mixed["tags"], ["reading"])
        self.assertEqual(row_mixed["first_tag"], "reading")

        # 3. Case-insensitive [NOWH]
        post_upper = {
            "message_id": 603,
            "date": 1729684800,
            "text": "[NOWH] All caps suppression tag",
        }
        row_upper = parse_channel_post(post_upper, suppress_tags=["nowh"], strip_suppress_tags=True)
        self.assertTrue(row_upper["skip_discord"])
        self.assertEqual(row_upper["text"], "All caps suppression tag")

        # 4. Strip disabled (strip_suppress_tags=False)
        row_no_strip = parse_channel_post(post_suppressed, suppress_tags=["nowh"], strip_suppress_tags=False)
        self.assertTrue(row_no_strip["skip_discord"])
        self.assertEqual(row_no_strip["text"], "[nowh] A confidential thought about the roadmap.")
        self.assertEqual(row_no_strip["tags"], ["nowh"])

        # 5. Normal post without suppress tag -> skip_discord is False
        post_normal = {
            "message_id": 604,
            "date": 1729684800,
            "text": "Regular journal entry [fitness]",
        }
        row_normal = parse_channel_post(post_normal, suppress_tags=["nowh"])
        self.assertFalse(row_normal["skip_discord"])
        self.assertEqual(row_normal["text"], "Regular journal entry [fitness]")
        self.assertEqual(row_normal["tags"], ["fitness"])

    def test_dispatcher_channel_post_with_suppress_tag(self):
        client = MagicMock()
        config = BotConfig(
            bot_token="test_tok",
            channel_id="-100123",
            discord_webhook_url="https://discord.com/api/webhooks/123/abc",
            discord_suppress_tags=["nowh"],
        )
        initial_df = pd.DataFrame()

        with tempfile.TemporaryDirectory() as tmp_dir:
            delta_path = Path(tmp_dir) / "suppress_delta.parquet"
            dispatcher = BotDispatcher(client, config, initial_df, delta_path=delta_path)

            from unittest.mock import patch
            with patch("src.bot.discord_relay.send_discord_relay") as mock_relay:
                # 1. Post with [nowh] -> Should sync locally but NOT relay to Discord
                post_suppressed = {
                    "message_id": 10,
                    "date": 1729686000,
                    "chat": {"id": -100123, "type": "channel"},
                    "text": "[nowh] Private journal reflection"
                }
                res = dispatcher.handle_channel_post(post_suppressed)
                self.assertIsNotNone(res)
                self.assertTrue(res["skip_discord"])
                self.assertEqual(len(dispatcher.df), 1)
                self.assertEqual(dispatcher.df.iloc[0]["text"], "Private journal reflection")
                mock_relay.assert_not_called()

                # 2. Normal post -> Should sync locally AND relay to Discord
                post_normal = {
                    "message_id": 11,
                    "date": 1729687000,
                    "chat": {"id": -100123, "type": "channel"},
                    "text": "Public journal reflection [reading]"
                }
                res_normal = dispatcher.handle_channel_post(post_normal)
                self.assertIsNotNone(res_normal)
                self.assertFalse(res_normal["skip_discord"])
                self.assertEqual(len(dispatcher.df), 2)
                mock_relay.assert_called_once()


if __name__ == "__main__":
    unittest.main()
