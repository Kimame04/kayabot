"""
Unit tests for Discord Webhook Relay.
Verifies payload construction, truncation, timestamp normalization, and fail-safe HTTP dispatch.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from src.bot.config import BotConfig
from src.bot.discord_relay import (
    format_discord_payload,
    get_circadian_embed_color,
    send_discord_relay,
)


class TestDiscordRelay(unittest.TestCase):
    def test_format_payload_basic(self):
        row = {
            "id": 101,
            "timestamp": datetime(2026, 11, 1, 10, 0, 0),
            "text": "Reflecting on system architecture.",
            "word_count": 4,
            "tags": [],
        }
        payload = format_discord_payload(row, bot_name="TestKaya")

        self.assertEqual(payload["username"], "TestKaya")
        self.assertEqual(len(payload["embeds"]), 1)
        embed = payload["embeds"][0]
        self.assertNotIn("title", embed)
        self.assertEqual(embed["description"], "Reflecting on system architecture.")
        self.assertEqual(embed["author"]["name"], "🖋️ Journal")
        self.assertIn("4 words", embed["footer"]["text"])
        self.assertIn("Entry #101", embed["footer"]["text"])
        self.assertEqual(embed["color"], 0xF1C40F)  # 10:00 is Morning Gold
        self.assertNotIn("fields", embed)

    def test_circadian_colors(self):
        self.assertEqual(get_circadian_embed_color(datetime(2026, 11, 1, 8, 0)), 0xF1C40F)   # Morning
        self.assertEqual(get_circadian_embed_color(datetime(2026, 11, 1, 14, 0)), 0x3498DB)  # Afternoon
        self.assertEqual(get_circadian_embed_color(datetime(2026, 11, 1, 19, 0)), 0xE67E22)  # Evening
        self.assertEqual(get_circadian_embed_color(datetime(2026, 11, 1, 23, 0)), 0x3F51B5)  # Night Owl
        self.assertEqual(get_circadian_embed_color(datetime(2026, 11, 1, 2, 0)), 0x3F51B5)   # Night Owl
        self.assertEqual(get_circadian_embed_color(None), 0x5865F2)                           # Fallback

    def test_format_payload_author_custom(self):
        row = {"id": 108, "text": "Testing custom author", "timestamp": datetime(2026, 11, 1, 10, 0)}
        payload = format_discord_payload(
            row,
            author_name="Kyan's Reflections",
            author_icon_url="https://example.com/kyan.png",
        )
        author = payload["embeds"][0]["author"]
        self.assertEqual(author["name"], "🖋️ Kyan's Reflections")
        self.assertEqual(author["icon_url"], "https://example.com/kyan.png")

    def test_format_payload_clean_media_fallback(self):
        # Photo post without caption should omit description
        photo_row = {"id": 109, "text": "", "media_type": "photo", "timestamp": datetime(2026, 11, 1, 12, 0)}
        payload_photo = format_discord_payload(photo_row, attachment_filename="photo.jpg")
        self.assertNotIn("description", payload_photo["embeds"][0])

        # Video post without caption should show video icon
        video_row = {"id": 110, "text": "", "media_type": "video", "timestamp": datetime(2026, 11, 1, 12, 0)}
        payload_video = format_discord_payload(video_row)
        self.assertEqual(payload_video["embeds"][0]["description"], "📹 *Video reflection*")

    def test_format_payload_with_tags(self):
        row = {
            "id": 102,
            "timestamp": datetime(2026, 11, 1, 11, 30, 0),
            "text": "Deep thinking session today [dev] [notes]",
            "word_count": 6,
            "tags": ["dev", "notes"],
        }
        payload = format_discord_payload(row)
        embed = payload["embeds"][0]

        self.assertIn("fields", embed)
        fields = embed["fields"]
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]["name"], "🏷️ Tags")
        self.assertIn("`[dev]`", fields[0]["value"])
        self.assertIn("`[notes]`", fields[0]["value"])

    def test_format_payload_forwarded_message(self):
        row = {
            "id": 105,
            "timestamp": datetime(2026, 11, 1, 15, 0, 0),
            "text": "Insightful breakdown of deep learning developments.",
            "word_count": 6,
            "tags": ["ai"],
            "is_forwarded": True,
            "forward_source_name": "AI Digest",
            "forward_source_type": "channel",
            "forward_source_url": "https://t.me/aidigest/100",
            "forward_date": datetime(2026, 10, 31, 18, 30, 0),
        }
        payload = format_discord_payload(row, author_name="Kieran Journal")
        embed = payload["embeds"][0]

        # Verify Author header includes forward source and link
        author = embed["author"]
        self.assertEqual(author["name"], "🖋️ Kieran Journal ↪️ AI Digest")
        self.assertEqual(author["url"], "https://t.me/aidigest/100")

        # Verify fields include Forwarded field
        field_names = [f["name"] for f in embed.get("fields", [])]
        self.assertIn("↪️ Forwarded", field_names)
        fwd_field = next(f for f in embed["fields"] if f["name"] == "↪️ Forwarded")
        self.assertIn("[AI Digest](https://t.me/aidigest/100)", fwd_field["value"])
        self.assertIn("Oct 31, 2026", fwd_field["value"])

    def test_format_payload_truncation(self):
        long_text = "A" * 5000
        row = {
            "id": 103,
            "timestamp": datetime(2026, 11, 1, 12, 0, 0),
            "text": long_text,
            "word_count": 1,
            "tags": [],
        }
        payload = format_discord_payload(row, max_desc_length=100)
        embed = payload["embeds"][0]
        self.assertTrue(len(embed["description"]) <= 100)
        self.assertTrue(embed["description"].endswith("... (truncated)"))

    def test_format_payload_timestamp(self):
        dt = datetime(2026, 11, 1, 14, 20, 0, tzinfo=timezone.utc)
        row = {
            "id": 104,
            "timestamp": dt,
            "text": "Time test",
            "word_count": 2,
            "tags": [],
        }
        payload = format_discord_payload(row)
        embed = payload["embeds"][0]
        self.assertIn("timestamp", embed)
        self.assertEqual(embed["timestamp"], dt.isoformat())

    @patch("urllib.request.urlopen")
    def test_send_discord_relay_success_204(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 204
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        row = {
            "id": 105,
            "timestamp": datetime(2026, 11, 1, 15, 0, 0),
            "text": "Dispatched to Discord",
            "word_count": 3,
            "tags": [],
        }
        dummy_url = "https://discord.com/api/webhooks/12345/abcdef_token"
        result = send_discord_relay(dummy_url, row)

        self.assertTrue(result)
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, f"{dummy_url}?wait=true")
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.headers["Content-type"], "application/json")

    def test_send_discord_relay_invalid_url(self):
        row = {"id": 1, "text": "test"}
        # None or empty
        self.assertFalse(send_discord_relay("", row))
        self.assertFalse(send_discord_relay(None, row))
        # Malformed domain prefix
        self.assertFalse(send_discord_relay("https://evil.com/api/webhooks/123", row))

    @patch("urllib.request.urlopen")
    def test_send_discord_relay_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://discord.com/api/webhooks/123/token",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=io.BytesIO(b'{"message": "Unknown Webhook"}'),
        )
        row = {"id": 106, "text": "Fail test"}
        dummy_url = "https://discord.com/api/webhooks/123/token"
        result = send_discord_relay(dummy_url, row)
        self.assertFalse(result)

    @patch("urllib.request.urlopen")
    def test_send_discord_relay_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        row = {"id": 107, "text": "Network fail test"}
        dummy_url = "https://discord.com/api/webhooks/123/token"
        result = send_discord_relay(dummy_url, row)
        self.assertFalse(result)

    def test_bot_config_has_discord_relay(self):
        config_none = BotConfig(bot_token="token")
        self.assertFalse(config_none.has_discord_relay)

        config_empty = BotConfig(bot_token="token", discord_webhook_url="   ")
        self.assertFalse(config_empty.has_discord_relay)

        config_valid = BotConfig(bot_token="token", discord_webhook_url="https://discord.com/api/webhooks/1/2")
        self.assertTrue(config_valid.has_discord_relay)

    @patch("src.bot.discord_relay.get_pending_queue_path")
    @patch("src.bot.discord_relay.delete_discord_relay")
    @patch("src.bot.discord_relay.edit_discord_relay")
    @patch("src.bot.discord_relay.send_discord_relay")
    def test_queue_and_flush_pending_relays(self, mock_send, mock_edit, mock_delete, mock_queue_path):
        import tempfile
        from pathlib import Path
        from src.bot.discord_relay import flush_pending_relays, queue_pending_relay

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_queue = Path(tmpdir) / "pending.json"
            mock_queue_path.return_value = fake_queue

            # 1. Queue CREATE action
            row1 = {"id": 201, "text": "Offline entry", "timestamp": datetime(2026, 11, 1, 12, 0, 0)}
            queue_pending_relay(row1, action="CREATE")

            # 2. Queue UPDATE action
            row2 = {"id": 202, "text": "Edited entry", "timestamp": datetime(2026, 11, 1, 13, 0, 0)}
            queue_pending_relay(row2, action="UPDATE", discord_message_id="msg_edit_123")

            # 3. Queue DELETE action
            row3 = {"id": 203, "text": "Deleted entry", "timestamp": datetime(2026, 11, 1, 14, 0, 0)}
            queue_pending_relay(row3, action="DELETE", discord_message_id="msg_del_456")

            self.assertTrue(fake_queue.exists())

            mock_send.return_value = True
            mock_edit.return_value = True
            mock_delete.return_value = True

            flushed = flush_pending_relays("https://discord.com/api/webhooks/1/2")
            self.assertEqual(flushed, 3)
            self.assertFalse(fake_queue.exists())
            mock_send.assert_called_once()
            mock_edit.assert_called_once()
            mock_delete.assert_called_once()

    def test_encode_multipart_form(self):
        from src.bot.discord_relay import encode_multipart_form
        payload = {"username": "Kaya", "embeds": [{"title": "Test"}]}
        file_bytes = b"fake_jpeg_content"
        body, content_type = encode_multipart_form(payload, file_bytes, "photo.jpg")

        self.assertIn("multipart/form-data; boundary=", content_type)
        self.assertIn(b"payload_json", body)
        self.assertIn(b"fake_jpeg_content", body)
        self.assertIn(b'filename="photo.jpg"', body)
        self.assertIn(b"image/jpeg", body)

    def test_format_payload_with_media(self):
        row = {
            "id": 301,
            "timestamp": datetime(2026, 11, 1, 14, 0, 0),
            "text": "Photo caption",
            "media_type": "photo",
        }
        payload = format_discord_payload(
            row,
            attachment_filename="reflection.jpg",
            media_warning="⚠️ Video too large",
        )
        embed = payload["embeds"][0]
        self.assertEqual(embed["image"]["url"], "attachment://reflection.jpg")
        self.assertTrue(any(f["name"] == "📹 Media Notice" for f in embed.get("fields", [])))

    @patch("urllib.request.urlopen")
    def test_send_discord_relay_multipart_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 204
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        row = {"id": 302, "text": "Photo post", "media_type": "photo"}
        dummy_url = "https://discord.com/api/webhooks/123/token"
        result = send_discord_relay(
            dummy_url,
            row,
            file_bytes=b"dummy_bytes",
            filename="photo.jpg",
        )
        self.assertTrue(result)
        req = mock_urlopen.call_args[0][0]
        self.assertIn("multipart/form-data", req.headers["Content-type"])

    @patch("urllib.request.urlopen")
    def test_send_discord_relay_413_fallback(self, mock_urlopen):
        # First call fails with 413, second call (text fallback) succeeds with 204
        err_413 = urllib.error.HTTPError(
            url="https://discord.com/api/webhooks/123/token",
            code=413,
            msg="Payload Too Large",
            hdrs={},
            fp=io.BytesIO(b'{"message": "Request entity too large"}'),
        )
        mock_resp_success = MagicMock()
        mock_resp_success.__enter__.return_value.getcode.return_value = 204

        mock_urlopen.side_effect = [err_413, mock_resp_success]

        row = {"id": 303, "text": "Huge video post", "media_type": "video"}
        dummy_url = "https://discord.com/api/webhooks/123/token"
        result = send_discord_relay(
            dummy_url,
            row,
            file_bytes=b"15mb_of_data",
            filename="large.mp4",
        )
        self.assertTrue(result)
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("urllib.request.urlopen")
    def test_send_discord_relay_returns_message_id(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = b'{"id": "987654321012345678", "channel_id": "111"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        row = {"id": 401, "text": "Testing wait=true ID extraction", "word_count": 4}
        dummy_url = "https://discord.com/api/webhooks/123/token"
        result = send_discord_relay(dummy_url, row)

        self.assertEqual(result, "987654321012345678")
        req = mock_urlopen.call_args[0][0]
        self.assertIn("wait=true", req.full_url)

    @patch("urllib.request.urlopen")
    def test_edit_discord_relay_success(self, mock_urlopen):
        from src.bot.discord_relay import edit_discord_relay

        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        row = {"id": 402, "text": "Edited text reflection", "word_count": 3}
        dummy_url = "https://discord.com/api/webhooks/123/token?wait=true"
        success = edit_discord_relay(dummy_url, "987654321012345678", row)

        self.assertTrue(success)
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_method(), "PATCH")
        self.assertEqual(req.full_url, "https://discord.com/api/webhooks/123/token/messages/987654321012345678")

        # Verify edited indicator in footer
        payload = json.loads(req.data.decode("utf-8"))
        self.assertIn("(edited)", payload["embeds"][0]["footer"]["text"])

    @patch("urllib.request.urlopen")
    def test_delete_discord_relay_success(self, mock_urlopen):
        from src.bot.discord_relay import delete_discord_relay

        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 204
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        dummy_url = "https://discord.com/api/webhooks/123/token"
        success = delete_discord_relay(dummy_url, "987654321012345678")

        self.assertTrue(success)
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_method(), "DELETE")
        self.assertEqual(req.full_url, "https://discord.com/api/webhooks/123/token/messages/987654321012345678")


if __name__ == "__main__":
    unittest.main()
