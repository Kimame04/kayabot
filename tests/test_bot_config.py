"""
Unit tests for Telegram Bot configuration and .env parsing.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from src.bot.config import BotConfig, load_config, parse_env_file, save_chat_id_to_env


class TestBotConfig(unittest.TestCase):
    def test_parse_env_file(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".env") as f:
            f.write("# Comment line\n")
            f.write("TELEGRAM_BOT_TOKEN=\"12345:ABCDE\"\n")
            f.write("TELEGRAM_CHAT_ID='987654321'\n")
            f.write("EMPTY_VAL=\n")
            f.flush()
            temp_path = Path(f.name)

        try:
            parsed = parse_env_file(temp_path)
            self.assertEqual(parsed.get("TELEGRAM_BOT_TOKEN"), "12345:ABCDE")
            self.assertEqual(parsed.get("TELEGRAM_CHAT_ID"), "987654321")
            self.assertEqual(parsed.get("EMPTY_VAL"), "")
        finally:
            temp_path.unlink()

    def test_save_chat_id_to_env(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".env") as f:
            f.write('TELEGRAM_BOT_TOKEN="test_token"\n')
            f.flush()
            temp_path = Path(f.name)

        try:
            save_chat_id_to_env(445566, env_file=temp_path)
            cfg = load_config(env_file=temp_path)
            self.assertEqual(cfg.chat_id, "445566")
            self.assertEqual(cfg.bot_token, "test_token")
            self.assertTrue(cfg.can_send)
        finally:
            temp_path.unlink()

    def test_suppress_tags_config(self):
        # 1. Default suppression tag
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".env") as f:
            f.write('TELEGRAM_BOT_TOKEN="token_123"\n')
            f.flush()
            temp_path = Path(f.name)

        try:
            cfg = load_config(env_file=temp_path)
            self.assertEqual(cfg.discord_suppress_tags, ["nowh"])
            self.assertTrue(cfg.discord_strip_suppress_tags)
            self.assertTrue(cfg.is_suppressed(["nowh"]))
            self.assertTrue(cfg.is_suppressed(["NOWH"]))
            self.assertFalse(cfg.is_suppressed(["reading"]))
            self.assertFalse(cfg.is_suppressed([]))
        finally:
            temp_path.unlink()

        # 2. Custom multiple suppression tags & strip disabled
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".env") as f:
            f.write('TELEGRAM_BOT_TOKEN="token_123"\n')
            f.write('DISCORD_SUPPRESS_TAGS="nowh, [private], #secret"\n')
            f.write('DISCORD_STRIP_SUPPRESS_TAGS="false"\n')
            f.flush()
            temp_path = Path(f.name)

        try:
            cfg2 = load_config(env_file=temp_path)
            self.assertEqual(cfg2.discord_suppress_tags, ["nowh", "private", "secret"])
            self.assertFalse(cfg2.discord_strip_suppress_tags)
            self.assertTrue(cfg2.is_suppressed(["private"]))
            self.assertTrue(cfg2.is_suppressed(["SECRET"]))
            self.assertFalse(cfg2.is_suppressed(["random"]))
        finally:
            temp_path.unlink()


if __name__ == "__main__":
    unittest.main()
