"""
Unit tests for Telegram Bot API Client.
Verifies payload structures, serialization, and error handling with 100% mocked network calls.
"""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from src.bot.client import TelegramAPIError, TelegramClient


class TestTelegramClient(unittest.TestCase):
    def test_empty_token_raises_error(self):
        with self.assertRaises(ValueError):
            TelegramClient("")

    @patch("urllib.request.urlopen")
    def test_get_me_success(self, mock_urlopen):
        mock_response = io.BytesIO(json.dumps({
            "ok": True,
            "result": {
                "id": 123456,
                "is_bot": True,
                "first_name": "TestBot",
                "username": "test_bot"
            }
        }).encode("utf-8"))
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = TelegramClient("dummy_token")
        result = client.get_me()

        self.assertEqual(result["username"], "test_bot")
        self.assertEqual(result["id"], 123456)
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.telegram.org/botdummy_token/getMe")

    @patch("urllib.request.urlopen")
    def test_send_message_payload(self, mock_urlopen):
        mock_response = io.BytesIO(json.dumps({
            "ok": True,
            "result": {"message_id": 999}
        }).encode("utf-8"))
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = TelegramClient("dummy_token")
        markup = {"inline_keyboard": [[{"text": "Test", "callback_data": "test"}]]}
        res = client.send_message(
            chat_id=12345,
            text="Hello <b>World</b>",
            parse_mode="HTML",
            reply_markup=markup
        )

        self.assertEqual(res["message_id"], 999)
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.telegram.org/botdummy_token/sendMessage")
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], 12345)
        self.assertEqual(payload["text"], "Hello <b>World</b>")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertEqual(payload["reply_markup"], markup)

    @patch("urllib.request.urlopen")
    def test_api_returns_ok_false(self, mock_urlopen):
        mock_response = io.BytesIO(json.dumps({
            "ok": False,
            "error_code": 403,
            "description": "Forbidden: bot was blocked by the user"
        }).encode("utf-8"))
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = TelegramClient("dummy_token")
        with self.assertRaises(TelegramAPIError) as ctx:
            client.send_message(chat_id=12345, text="Hello")

        self.assertIn("bot was blocked by the user", str(ctx.exception))
        self.assertEqual(ctx.exception.error_code, 403)

    @patch("urllib.request.urlopen")
    def test_http_error_handling(self, mock_urlopen):
        err_body = io.BytesIO(json.dumps({
            "ok": False,
            "error_code": 400,
            "description": "Bad Request: chat not found"
        }).encode("utf-8"))
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://example.com",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=err_body
        )

        client = TelegramClient("dummy_token")
        with self.assertRaises(TelegramAPIError) as ctx:
            client.send_message(chat_id=99999, text="Hello")

        self.assertIn("chat not found", str(ctx.exception))
        self.assertEqual(ctx.exception.error_code, 400)

    @patch("urllib.request.urlopen")
    def test_get_file(self, mock_urlopen):
        mock_response = io.BytesIO(json.dumps({
            "ok": True,
            "result": {
                "file_id": "file_123",
                "file_path": "photos/file_123.jpg",
                "file_size": 45000,
            }
        }).encode("utf-8"))
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = TelegramClient("dummy_token")
        res = client.get_file("file_123")
        self.assertEqual(res["file_path"], "photos/file_123.jpg")
        self.assertEqual(res["file_size"], 45000)

    @patch("urllib.request.urlopen")
    def test_download_file(self, mock_urlopen):
        fake_bytes = b"\xff\xd8\xff\xe0test_jpeg_bytes"
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_bytes
        mock_resp.headers = {"Content-Length": str(len(fake_bytes))}
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        client = TelegramClient("dummy_token")
        data = client.download_file("photos/file_123.jpg", max_bytes=1024)
        self.assertEqual(data, fake_bytes)


if __name__ == "__main__":
    unittest.main()
