"""
Pure-Python Telegram Bot API Client.
Zero third-party dependencies; uses standard library urllib.request.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union
import urllib.error
import urllib.parse
import urllib.request


class TelegramAPIError(Exception):
    """Raised when Telegram Bot API returns an error response."""
    def __init__(self, description: str, error_code: Optional[int] = None):
        super().__init__(f"[{error_code}] {description}" if error_code else description)
        self.description = description
        self.error_code = error_code


class TelegramClient:
    """Minimalist, zero-dependency Telegram Bot API client."""

    BASE_URL = "https://api.telegram.org/bot"

    def __init__(self, token: str, timeout: int = 15):
        if not token:
            raise ValueError("Telegram Bot token must not be empty.")
        self.token = token.strip()
        self.timeout = timeout
        self.api_url = f"{self.BASE_URL}{self.token}"

    def _request(self, method: str, payload: Optional[Dict[str, Any]] = None, timeout: Optional[int] = None) -> Any:
        """Execute a POST or GET request to the Telegram Bot API."""
        url = f"{self.api_url}/{method}"
        headers = {"User-Agent": "TelegramJournalBot/1.0"}

        data_bytes = None
        if payload is not None:
            # Clean None values from payload
            cleaned = {k: v for k, v in payload.items() if v is not None}
            data_bytes = json.dumps(cleaned).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data_bytes, headers=headers)
        call_timeout = timeout if timeout is not None else self.timeout

        try:
            with urllib.request.urlopen(req, timeout=call_timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if not result.get("ok"):
                    raise TelegramAPIError(
                        result.get("description", "Unknown error"),
                        result.get("error_code")
                    )
                return result.get("result")
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                desc = err_body.get("description", e.reason)
                code = err_body.get("error_code", e.code)
            except Exception:
                desc = str(e.reason)
                code = e.code
            raise TelegramAPIError(desc, code) from e
        except urllib.error.URLError as e:
            raise TelegramAPIError(f"Network error connecting to Telegram: {e.reason}") from e

    def get_me(self) -> Dict[str, Any]:
        """Verify token and get basic information about the bot."""
        return self._request("getMe")

    def get_updates(
        self,
        offset: Optional[int] = None,
        limit: int = 100,
        timeout: int = 0,
        allowed_updates: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch incoming updates using long polling."""
        payload: Dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates

        # For long polling, request timeout must be larger than poll timeout
        req_timeout = (timeout + 10) if timeout > 0 else self.timeout
        return self._request("getUpdates", payload=payload, timeout=req_timeout)

    def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        parse_mode: Optional[str] = "HTML",
        disable_web_page_preview: bool = True,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a text message to a chat or channel."""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        return self._request("sendMessage", payload=payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> bool:
        """Acknowledge an inline keyboard callback query."""
        payload: Dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = text
        return bool(self._request("answerCallbackQuery", payload=payload))

    def get_file(self, file_id: str) -> Dict[str, Any]:
        """Fetch basic file metadata including file_path from Telegram."""
        return self._request("getFile", payload={"file_id": file_id})

    def download_file(self, file_path: str, max_bytes: int = 10 * 1024 * 1024) -> Optional[bytes]:
        """
        Download raw file bytes from Telegram cloud storage.
        Safely enforces max_bytes to avoid reading monolithic streams into memory.
        """
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        req = urllib.request.Request(url, headers={"User-Agent": "TelegramJournalAnalytics/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content_len = resp.headers.get("Content-Length")
                if content_len and int(content_len) > max_bytes:
                    return None
                data = resp.read(max_bytes + 1)
                if len(data) > max_bytes:
                    return None
                return data
        except Exception:
            return None
