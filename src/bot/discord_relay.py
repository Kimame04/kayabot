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
    author_name: str = "Journal",
    author_icon_url: Optional[str] = None,
    max_desc_length: int = 4000,
    attachment_filename: Optional[str] = None,
    media_warning: Optional[str] = None,
    is_edited: bool = False,
) -> Dict[str, Any]:
    """
    Construct a JSON-serializable Discord webhook payload featuring a rich embed.
    Safely handles string truncation, ISO-8601 timestamps, tags, circadian colors,
    and edge-to-edge media rendering without redundant title headers.
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

    # Forwarded source field
    if row.get("is_forwarded"):
        source_name = row.get("forward_source_name") or "Unknown Source"
        source_url = row.get("forward_source_url")
        source_display = f"[{source_name}]({source_url})" if source_url else f"**{source_name}**"

        fwd_date = row.get("forward_date")
        if isinstance(fwd_date, datetime):
            fwd_date_str = fwd_date.strftime("%b %d, %Y %H:%M")
            fwd_val = f"From {source_display} • {fwd_date_str}"
        else:
            fwd_val = f"From {source_display}"

        fields.append({
            "name": "↪️ Forwarded",
            "value": fwd_val,
            "inline": False,
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
    if is_edited or row.get("is_edited"):
        footer_text += " • (edited)"

    # Compute circadian time-of-day border color
    color = get_circadian_embed_color(raw_ts)

    # Author header block
    author_header = f"🖋️ {author_name}"
    if row.get("is_forwarded") and row.get("forward_source_name"):
        author_header = f"🖋️ {author_name} ↪️ {row['forward_source_name']}"
    author_dict: Dict[str, Any] = {"name": author_header}
    if author_icon_url:
        author_dict["icon_url"] = author_icon_url
    if row.get("is_forwarded") and row.get("forward_source_url"):
        author_dict["url"] = row["forward_source_url"]

    embed: Dict[str, Any] = {
        "author": author_dict,
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
    author_name: str = "Journal",
    author_icon_url: Optional[str] = None,
    timeout: int = 15,
) -> Optional[str]:
    """
    Dispatches a reflection entry to Discord via Webhook.
    Supports multipart form uploads with file attachments, automatic 413 fallback,
    customizable author branding, and non-blocking fail-safe execution.
    Returns the Discord message ID string on success (truthy), or None on failure.
    """
    if not webhook_url or not str(webhook_url).strip():
        return None

    url = str(webhook_url).strip()
    if not (url.startswith("https://discord.com/api/webhooks/") or url.startswith("https://discordapp.com/api/webhooks/")):
        logger.warning(f"[DiscordRelay] Invalid Discord webhook URL prefix: {url[:30]}...")
        return None

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

        # Append wait=true so Discord returns created Message object JSON with its ID
        target_url = url
        if "?" in target_url:
            if "wait=true" not in target_url:
                target_url += "&wait=true"
        else:
            target_url += "?wait=true"

        req = urllib.request.Request(
            target_url,
            data=data,
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.getcode()
            if status in (200, 201):
                try:
                    resp_bytes = response.read()
                    if resp_bytes:
                        resp_json = json.loads(resp_bytes.decode("utf-8"))
                        msg_id = resp_json.get("id")
                        if msg_id:
                            return str(msg_id)
                except Exception:
                    pass
                return "true"
            elif status == 204:
                return "true"
            logger.warning(f"[DiscordRelay] Webhook returned unexpected HTTP status: {status}")
            return None

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
        return None
    except urllib.error.URLError as e:
        logger.warning(f"[DiscordRelay] Network/URL Error: {e.reason}")
        return None
    except Exception as e:
        logger.warning(f"[DiscordRelay] Unexpected error relaying to Discord: {e}")
        return None


def edit_discord_relay(
    webhook_url: Optional[str],
    discord_message_id: str,
    row: Dict[str, Any],
    bot_name: str = "Kaya",
    author_name: str = "Journal",
    author_icon_url: Optional[str] = None,
    timeout: int = 15,
) -> bool:
    """
    Edits an existing Discord webhook reflection message using HTTP PATCH.
    Updates the embed content, tags, circadian border color, and footer with an '(edited)' indicator.
    Returns True if successfully edited, False otherwise.
    """
    if not webhook_url or not str(webhook_url).strip() or not discord_message_id:
        return False

    url = str(webhook_url).strip()
    if not (url.startswith("https://discord.com/api/webhooks/") or url.startswith("https://discordapp.com/api/webhooks/")):
        logger.warning(f"[DiscordRelay] Invalid Discord webhook URL prefix: {url[:30]}...")
        return False

    base_url = url.split("?")[0].rstrip("/")
    patch_url = f"{base_url}/messages/{discord_message_id}"

    payload = format_discord_payload(
        row,
        bot_name=bot_name,
        author_name=author_name,
        author_icon_url=author_icon_url,
        is_edited=True,
    )

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "TelegramJournalRelay/1.0",
    }

    try:
        req = urllib.request.Request(
            patch_url,
            data=data,
            headers=headers,
            method="PATCH",
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.getcode()
            if status in (200, 204):
                return True
            logger.warning(f"[DiscordRelay] Webhook PATCH returned unexpected HTTP status: {status}")
            return False

    except urllib.error.HTTPError as e:
        logger.warning(f"[DiscordRelay] HTTP Error {e.code} editing message {discord_message_id}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        logger.warning(f"[DiscordRelay] Network/URL Error editing message: {e.reason}")
        return False
    except Exception as e:
        logger.warning(f"[DiscordRelay] Unexpected error editing Discord message: {e}")
        return False


def delete_discord_relay(
    webhook_url: Optional[str],
    discord_message_id: str,
    timeout: int = 15,
) -> bool:
    """
    Deletes an existing Discord webhook reflection message using HTTP DELETE.
    Returns True if successfully deleted (HTTP 204), False otherwise.
    """
    if not webhook_url or not str(webhook_url).strip() or not discord_message_id:
        return False

    url = str(webhook_url).strip()
    if not (url.startswith("https://discord.com/api/webhooks/") or url.startswith("https://discordapp.com/api/webhooks/")):
        logger.warning(f"[DiscordRelay] Invalid Discord webhook URL prefix: {url[:30]}...")
        return False

    base_url = url.split("?")[0].rstrip("/")
    del_url = f"{base_url}/messages/{discord_message_id}"

    headers = {
        "User-Agent": "TelegramJournalRelay/1.0",
    }

    try:
        req = urllib.request.Request(
            del_url,
            headers=headers,
            method="DELETE",
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.getcode()
            if status in (200, 204):
                return True
            logger.warning(f"[DiscordRelay] Webhook DELETE returned unexpected HTTP status: {status}")
            return False

    except urllib.error.HTTPError as e:
        logger.warning(f"[DiscordRelay] HTTP Error {e.code} deleting message {discord_message_id}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        logger.warning(f"[DiscordRelay] Network/URL Error deleting message: {e.reason}")
        return False
    except Exception as e:
        logger.warning(f"[DiscordRelay] Unexpected error deleting Discord message: {e}")
        return False


def get_pending_queue_path() -> Path:
    """Return path to local pending Discord relay queue in .cache directory."""
    from src.bot.config import get_repo_root
    cache_dir = get_repo_root() / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "pending_discord_relays.json"


def queue_pending_relay(
    row: Dict[str, Any],
    media_warning: Optional[str] = None,
    action: str = "CREATE",
    discord_message_id: Optional[str] = None,
) -> None:
    """Queue a failed or offline reflection (create, update, delete) to be retried when connectivity is restored."""
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
    if isinstance(serializable.get("forward_date"), datetime):
        serializable["forward_date"] = serializable["forward_date"].isoformat()
    if isinstance(serializable.get("edit_date"), datetime):
        serializable["edit_date"] = serializable["edit_date"].isoformat()

    entry = {
        "action": action,
        "entry_id": serializable.get("id"),
        "discord_message_id": discord_message_id or serializable.get("discord_message_id"),
        "media_warning": media_warning,
        "row": serializable,
    }

    # Deduplicate by entry_id
    entries = [e for e in entries if (e.get("entry_id") or e.get("id")) != serializable.get("id")]
    entries.append(entry)

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
    except Exception as e:
        logger.warning(f"[DiscordRelay] Failed to write to pending relay queue: {e}")


def flush_pending_relays(
    webhook_url: Optional[str],
    bot_name: str = "Kaya",
    author_name: str = "Journal",
    author_icon_url: Optional[str] = None,
    timeout: int = 5,
) -> int:
    """
    Attempt to flush any previously queued failed reflections to Discord.
    Supports CREATE, UPDATE, and DELETE actions.
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
        action = entry.get("action", "CREATE")
        item = dict(entry.get("row") or entry)
        if isinstance(item.get("timestamp"), str):
            try:
                item["timestamp"] = datetime.fromisoformat(item["timestamp"])
            except Exception:
                pass
        if isinstance(item.get("forward_date"), str):
            try:
                item["forward_date"] = datetime.fromisoformat(item["forward_date"])
            except Exception:
                pass
        if isinstance(item.get("edit_date"), str):
            try:
                item["edit_date"] = datetime.fromisoformat(item["edit_date"])
            except Exception:
                pass

        success = False
        target_msg_id = entry.get("discord_message_id") or item.get("discord_message_id")

        if action == "UPDATE" and target_msg_id:
            success = edit_discord_relay(
                webhook_url,
                target_msg_id,
                item,
                bot_name=bot_name,
                author_name=author_name,
                author_icon_url=author_icon_url,
                timeout=timeout,
            )
        elif action == "DELETE" and target_msg_id:
            success = delete_discord_relay(
                webhook_url,
                target_msg_id,
                timeout=timeout,
            )
        else:
            success = bool(send_discord_relay(
                webhook_url,
                item,
                bot_name=bot_name,
                author_name=author_name,
                author_icon_url=author_icon_url,
                timeout=timeout,
            ))

        if success:
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
