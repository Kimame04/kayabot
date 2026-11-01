"""
Discord Webhook Relay Module.
Forwards live journal reflections from Telegram channel ingestion to Discord
using standard library urllib and rich embeds, with zero third-party dependencies.
Supports inline photo attachments, short videos, circadian color palettes,
and customizable author branding.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request
import uuid

logger = logging.getLogger("discord_relay")


def get_circadian_embed_color(dt: Optional[datetime]) -> int:
    """
    Return a Discord hex color integer matching the circadian time-of-day:
    - 🌅 Morning (05:00 – 11:59): Sunrise Gold (0xF1C40F)
    - ☀️ Afternoon (12:00 – 17:59): Sky Blue (0x3498DB)
    - 🌆 Evening / Dusk (18:00 – 21:59): Sunset Coral (0xE67E22)
    - 🌙 Night Owl (22:00 – 04:59): Midnight Indigo (0x3F51B5)
    """
    if not isinstance(dt, datetime):
        return 0x5865F2  # Discord Blurple default

    hour = dt.hour
    if 5 <= hour < 12:
        return 0xF1C40F  # Morning Gold
    elif 12 <= hour < 18:
        return 0x3498DB  # Afternoon Sky Blue
    elif 18 <= hour < 22:
        return 0xE67E22  # Evening Sunset Coral
    else:
        return 0x3F51B5  # Night Owl Midnight Indigo


def encode_multipart_form(
    payload_json: Dict[str, Any],
    file_bytes: bytes,
    filename: str,
    mime_type: Optional[str] = None,
) -> Tuple[bytes, str]:
    """
    Encode a multipart/form-data payload containing payload_json and binary file attachment.
    Returns (body_bytes, content_type_header).
    """
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    content_type_header = f"multipart/form-data; boundary={boundary}"

    if not mime_type:
        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type:
            mime_type = "application/octet-stream"

    body = io.BytesIO()
    # Part 1: payload_json
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(b'Content-Disposition: form-data; name="payload_json"\r\n')
    body.write(b"Content-Type: application/json\r\n\r\n")
    body.write(json.dumps(payload_json).encode("utf-8"))
    body.write(b"\r\n")

    # Part 2: file attachment
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'.encode("utf-8"))
    body.write(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
    body.write(file_bytes)
    body.write(b"\r\n")

    # Closing boundary
    body.write(f"--{boundary}--\r\n".encode("utf-8"))

    return body.getvalue(), content_type_header


def format_discord_payload(
    row: Dict[str, Any],
    bot_name: str = "Kaya",
    author_name: str = "Kyan's Journal",
    author_icon_url: Optional[str] = None,
    max_desc_length: int = 4000,
    attachment_filename: Optional[str] = None,
    media_warning: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Construct a JSON-serializable Discord webhook payload featuring a rich embed.
    Safely handles string truncation, ISO-8601 timestamps, tags, circadian colors,
    and edge-to-edge media rendering.
    """
    raw_text = str(row.get("text") or "").strip()
    has_photo = bool(attachment_filename or row.get("has_photo") or row.get("media_type") == "photo")
    has_video = bool(row.get("media_type") == "video")

    embed_description: Optional[str] = None
    if raw_text:
        if len(raw_text) > max_desc_length:
            embed_description = raw_text[: max_desc_length - 20] + "\n\n... (truncated)"
        else:
            embed_description = raw_text
    else:
        # Clean media fallback: omit description on photos for edge-to-edge rendering
        if has_photo:
            embed_description = None
        elif has_video:
            embed_description = "📹 *Video reflection*"
        else:
            embed_description = "*(Blank reflection)*"

    # Format timestamp for Discord (ISO-8601)
    raw_ts = row.get("timestamp")
    ts_str = None
    if isinstance(raw_ts, datetime):
        if raw_ts.tzinfo is None:
            ts_str = raw_ts.astimezone().isoformat()
        else:
            ts_str = raw_ts.isoformat()

    # Build fields for metadata
    fields: List[Dict[str, Any]] = []

    tags = row.get("tags")
    if tags and hasattr(tags, "__iter__") and not isinstance(tags, (str, bytes)):
        tag_list = [f"`[{t}]`" for t in tags if str(t).strip()]
        if tag_list:
            fields.append({
                "name": "🏷️ Tags",
                "value": " ".join(tag_list),
                "inline": True,
            })

    # Media warning or notice (e.g. over 10MB)
    warning_text = media_warning or row.get("media_warning")
    if warning_text:
        fields.append({
            "name": "📹 Media Notice",
            "value": str(warning_text),
            "inline": False,
        })

    # Word count & Entry ID footer
    word_count = row.get("word_count", len(raw_text.split()))
    entry_id = row.get("id", "")
    footer_text = f"💬 {word_count} words"
    if entry_id:
        footer_text += f" • Entry #{entry_id}"

    # Compute circadian time-of-day border color
    color = get_circadian_embed_color(raw_ts)

    # Author header block
    author_dict: Dict[str, Any] = {"name": f"🖋️ {author_name}"}
    if author_icon_url:
        author_dict["icon_url"] = author_icon_url

    embed: Dict[str, Any] = {
        "author": author_dict,
        "title": "📓 Journal Reflection",
        "color": color,
        "footer": {
            "text": footer_text,
        },
    }

    if embed_description:
        embed["description"] = embed_description

    if ts_str:
        embed["timestamp"] = ts_str

    if fields:
        embed["fields"] = fields

    # If photo attachment provided, link it in the embed so it displays natively
    if attachment_filename and row.get("media_type") in ("photo", None):
        embed["image"] = {"url": f"attachment://{attachment_filename}"}

    return {
        "username": bot_name,
        "embeds": [embed],
    }


def send_discord_relay(
    webhook_url: Optional[str],
    row: Dict[str, Any],
    file_bytes: Optional[bytes] = None,
    filename: Optional[str] = None,
    media_warning: Optional[str] = None,
    bot_name: str = "Kaya",
    author_name: str = "Kyan's Journal",
    author_icon_url: Optional[str] = None,
    timeout: int = 15,
) -> bool:
    """
    Dispatches a reflection entry to Discord via Webhook.
    Supports multipart form uploads with file attachments, automatic 413 fallback,
    customizable author branding, and non-blocking fail-safe execution.
    Returns True if successfully sent, False otherwise.
    """
    if not webhook_url or not str(webhook_url).strip():
        return False

    url = str(webhook_url).strip()
    if not (url.startswith("https://discord.com/api/webhooks/") or url.startswith("https://discordapp.com/api/webhooks/")):
        logger.warning(f"[DiscordRelay] Invalid Discord webhook URL prefix: {url[:30]}...")
        return False

    try:
        if file_bytes and filename:
            payload = format_discord_payload(
                row,
                bot_name=bot_name,
                author_name=author_name,
                author_icon_url=author_icon_url,
                attachment_filename=filename,
                media_warning=media_warning,
            )
            data, content_type = encode_multipart_form(payload, file_bytes, filename)
            headers = {
                "Content-Type": content_type,
                "User-Agent": "TelegramJournalRelay/1.0",
            }
        else:
            payload = format_discord_payload(
                row,
                bot_name=bot_name,
                author_name=author_name,
                author_icon_url=author_icon_url,
                media_warning=media_warning,
            )
            data = json.dumps(payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "TelegramJournalRelay/1.0",
            }

        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.getcode()
            if status in (200, 204):
                return True
            logger.warning(f"[DiscordRelay] Webhook returned unexpected HTTP status: {status}")
            return False

    except urllib.error.HTTPError as e:
        if e.code == 413 and file_bytes:
            logger.warning("[DiscordRelay] Payload too large (HTTP 413). Retrying without file attachment...")
            # Automatically retry without file bytes, adding a clean warning note
            return send_discord_relay(
                webhook_url,
                row,
                file_bytes=None,
                filename=None,
                media_warning="⚠️ Media exceeds Discord upload limit (view in Telegram channel)",
                bot_name=bot_name,
                author_name=author_name,
                author_icon_url=author_icon_url,
                timeout=timeout,
            )
        logger.warning(f"[DiscordRelay] HTTP Error {e.code}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        logger.warning(f"[DiscordRelay] Network/URL Error: {e.reason}")
        return False
    except Exception as e:
        logger.warning(f"[DiscordRelay] Unexpected error relaying to Discord: {e}")
        return False


def get_pending_queue_path() -> Path:
    """Return path to local pending Discord relay queue in .cache directory."""
    from src.bot.config import get_repo_root
    cache_dir = get_repo_root() / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "pending_discord_relays.json"


def queue_pending_relay(row: Dict[str, Any], media_warning: Optional[str] = None) -> None:
    """Queue a failed or offline reflection to be retried when connectivity is restored."""
    path = get_pending_queue_path()
    entries: List[Dict[str, Any]] = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []

    serializable = dict(row)
    if isinstance(serializable.get("timestamp"), datetime):
        serializable["timestamp"] = serializable["timestamp"].isoformat()

    if media_warning:
        serializable["media_warning"] = media_warning

    # Deduplicate by ID
    entries = [e for e in entries if e.get("id") != serializable.get("id")]
    entries.append(serializable)

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
    except Exception as e:
        logger.warning(f"[DiscordRelay] Failed to write to pending relay queue: {e}")


def flush_pending_relays(
    webhook_url: Optional[str],
    bot_name: str = "Kaya",
    author_name: str = "Kyan's Journal",
    author_icon_url: Optional[str] = None,
    timeout: int = 5,
) -> int:
    """
    Attempt to flush any previously queued failed reflections to Discord.
    Returns the number of successfully relayed entries.
    """
    if not webhook_url:
        return 0

    path = get_pending_queue_path()
    if not path.exists():
        return 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        return 0

    if not entries:
        return 0

    remaining: List[Dict[str, Any]] = []
    flushed_count = 0

    for entry in entries:
        item = dict(entry)
        if isinstance(item.get("timestamp"), str):
            try:
                item["timestamp"] = datetime.fromisoformat(item["timestamp"])
            except Exception:
                pass

        if send_discord_relay(
            webhook_url,
            item,
            bot_name=bot_name,
            author_name=author_name,
            author_icon_url=author_icon_url,
            timeout=timeout,
        ):
            flushed_count += 1
        else:
            remaining.append(entry)

    if remaining:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(remaining, f, indent=2)
        except Exception:
            pass
    else:
        try:
            path.unlink()
        except Exception:
            pass

    return flushed_count
