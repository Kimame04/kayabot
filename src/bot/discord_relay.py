"""
Discord Webhook Relay Module.
Forwards live journal reflections from Telegram channel ingestion to Discord
using standard library urllib and rich embeds, with zero third-party dependencies.
Supports inline photo attachments, short videos, circadian color palettes,
and customizable author branding.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import io
import json
import logging
import math
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

    # If photo attachment provided (or existing on edit), link it in the embed so it displays natively
    is_image_type = row.get("media_type") in ("photo", None)
    is_image_ext = bool(attachment_filename and attachment_filename.lower().endswith(
        (".jpg", ".jpeg", ".png", ".webp", ".gif")
    ))
    if attachment_filename and (is_image_type or is_image_ext):
        embed["image"] = {"url": f"attachment://{attachment_filename}"}
    elif row.get("has_photo") or row.get("media_type") == "photo":
        photo_filename = row.get("media_file_name") or "reflection.jpg"
        embed["image"] = {"url": f"attachment://{photo_filename}"}

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
    file_bytes: Optional[bytes] = None,
    filename: Optional[str] = None,
    media_warning: Optional[str] = None,
    bot_name: str = "Kaya",
    author_name: str = "Journal",
    author_icon_url: Optional[str] = None,
    timeout: int = 15,
) -> bool:
    """
    Edits an existing Discord webhook reflection message using HTTP PATCH.
    Supports multipart attachments, media warning banners, circadian borders,
    and appends an '(edited)' indicator in the embed footer.
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

    try:
        if file_bytes and filename:
            payload = format_discord_payload(
                row,
                bot_name=bot_name,
                author_name=author_name,
                author_icon_url=author_icon_url,
                attachment_filename=filename,
                media_warning=media_warning,
                is_edited=True,
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
                is_edited=True,
            )
            data = json.dumps(payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "TelegramJournalRelay/1.0",
            }

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
        if e.code == 413 and file_bytes:
            logger.warning("[DiscordRelay] Payload too large (HTTP 413) on edit. Retrying without file attachment...")
            return edit_discord_relay(
                webhook_url,
                discord_message_id,
                row,
                file_bytes=None,
                filename=None,
                media_warning="⚠️ Media exceeds Discord upload limit (view in Telegram channel)",
                bot_name=bot_name,
                author_name=author_name,
                author_icon_url=author_icon_url,
                timeout=timeout,
            )
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
    for k, v in list(serializable.items()):
        if str(v) == "NaT":
            serializable[k] = None
        elif isinstance(v, (datetime, date)):
            serializable[k] = v.isoformat()
        elif hasattr(v, "tolist"):
            serializable[k] = v.tolist()
        elif hasattr(v, "item"):
            try:
                serializable[k] = v.item()
            except Exception:
                pass
        elif isinstance(v, float) and math.isnan(v):
            serializable[k] = None

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
            json.dump(entries, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"[DiscordRelay] Failed to write to pending relay queue: {e}")


def flush_pending_relays(
    webhook_url: Optional[str],
    bot_name: str = "Kaya",
    author_name: str = "Journal",
    author_icon_url: Optional[str] = None,
    client: Optional[Any] = None,
    delta_path: Optional[Path] = None,
    timeout: int = 15,
) -> int:
    """
    Attempt to flush any previously queued failed reflections to Discord.
    Supports CREATE, UPDATE, and DELETE actions.
    If a Telegram client is provided, automatically fetches and re-attaches
    media files (e.g. photos) if they failed download previously.
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
        if isinstance(item.get("date"), str):
            try:
                item["date"] = date.fromisoformat(item["date"])
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

        # Attempt to retrieve media attachment if TelegramClient is provided
        file_bytes: Optional[bytes] = None
        filename: Optional[str] = None
        media_warning: Optional[str] = entry.get("media_warning") or item.get("media_warning")

        media_file_id = item.get("media_file_id")
        media_size = item.get("media_file_size") or 0
        max_discord_size = 10 * 1024 * 1024

        if client and media_file_id:
            media_type_label = (item.get("media_type") or "Media").title()
            if media_size > max_discord_size:
                media_warning = f"⚠️ {media_type_label} ({media_size / (1024 * 1024):.1f} MB exceeds Discord limit — view in Telegram channel)"
            else:
                try:
                    file_info = client.get_file(media_file_id)
                    file_path = file_info.get("file_path") if isinstance(file_info, dict) else None
                    if file_path:
                        file_bytes = client.download_file(file_path, max_bytes=max_discord_size)
                        filename = item.get("media_file_name") or "reflection.jpg"
                        if not file_bytes:
                            media_warning = f"⚠️ {media_type_label} download failed or exceeded size limit (view in Telegram channel)"
                    else:
                        media_warning = f"⚠️ {media_type_label} file path unavailable from Telegram (view in Telegram channel)"
                except Exception as e:
                    logger.warning(f"[DiscordRelay] Failed to fetch media from Telegram during flush: {e}")
                    media_warning = f"⚠️ {media_type_label} could not be downloaded (view in Telegram channel)"

        success = False
        target_msg_id = entry.get("discord_message_id") or item.get("discord_message_id")

        if action == "UPDATE" and target_msg_id:
            edit_kwargs: Dict[str, Any] = {
                "bot_name": bot_name,
                "author_name": author_name,
                "author_icon_url": author_icon_url,
                "timeout": timeout,
            }
            if file_bytes is not None or filename is not None or media_warning is not None:
                edit_kwargs["file_bytes"] = file_bytes
                edit_kwargs["filename"] = filename
                edit_kwargs["media_warning"] = media_warning

            success = edit_discord_relay(
                webhook_url,
                target_msg_id,
                item,
                **edit_kwargs,
            )
        elif action == "DELETE" and target_msg_id:
            success = delete_discord_relay(
                webhook_url,
                target_msg_id,
                timeout=timeout,
            )
        else:
            relay_res = send_discord_relay(
                webhook_url,
                item,
                file_bytes=file_bytes,
                filename=filename,
                media_warning=media_warning,
                bot_name=bot_name,
                author_name=author_name,
                author_icon_url=author_icon_url,
                timeout=timeout,
            )
            success = bool(relay_res)
            if success and relay_res != "true" and item.get("id"):
                try:
                    from src.bot.live_sync import update_discord_message_id
                    update_discord_message_id(item["id"], str(relay_res), delta_path=delta_path)
                except Exception:
                    pass

        if success:
            flushed_count += 1
        else:
            remaining.append(entry)

    if remaining:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(remaining, f, indent=2, default=str)
        except Exception:
            pass
    else:
        try:
            path.unlink()
        except Exception:
            pass

    return flushed_count
