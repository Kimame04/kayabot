"""
Live Channel Ingestion Engine.
Captures incoming Telegram channel posts, extracts metadata/tags matching parser schema,
and maintains a live delta Parquet storage layer seamlessly merged with historical exports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.bot.config import get_repo_root
from src.parser import _extract_bracket_tags, _sanitize_reactions, load_export


def get_live_delta_path(export_dir: Optional[Path] = None) -> Path:
    """Return the destination path for the live delta Parquet store."""
    if export_dir and export_dir.exists() and export_dir.is_dir():
        cache_dir = export_dir / ".cache"
    else:
        cache_dir = get_repo_root() / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "live_messages.parquet"


def parse_channel_post(
    post: Dict[str, Any],
    suppress_tags: Optional[List[str]] = None,
    strip_suppress_tags: bool = True,
) -> Dict[str, Any]:
    """
    Parse a Telegram Bot API channel_post object into the standard DataFrame row dictionary.
    Guarantees 100% schema alignment with src.parser.load_export.
    Supports configurable Discord webhook suppression tags (e.g. [nowh]).
    """
    msg_id = int(post.get("message_id", 0))
    raw_date = post.get("date", 0)

    # Telegram API dates are UTC Unix timestamps
    dt_utc = datetime.fromtimestamp(raw_date, tz=timezone.utc)
    # Convert to naive local datetime to match Telegram Desktop HTML exports
    dt_local = dt_utc.astimezone().replace(tzinfo=None)

    raw_text = post.get("text") or post.get("caption") or ""
    tags = _extract_bracket_tags(raw_text)

    # Evaluate Discord webhook suppression
    skip_discord = False
    cleaned_text = raw_text
    if suppress_tags:
        suppress_set = {t.strip().lower().strip("[]#") for t in suppress_tags if t.strip()}
        matched_suppress = [t for t in tags if t.lower() in suppress_set]
        if matched_suppress:
            skip_discord = True
            if strip_suppress_tags:
                tags = [t for t in tags if t.lower() not in suppress_set]
                for stag in matched_suppress:
                    cleaned_text = re.sub(rf"\[{re.escape(stag)}\]", "", cleaned_text, flags=re.IGNORECASE)
                cleaned_lines = [
                    re.sub(r"[ \t]+", " ", line).strip()
                    for line in cleaned_text.splitlines()
                ]
                cleaned_text = "\n".join(cleaned_lines).strip()

    text = cleaned_text
    first_tag = tags[0] if tags else None

    # Media checks and metadata extraction
    media_file_id: Optional[str] = None
    media_type: Optional[str] = None
    media_file_size: Optional[int] = None
    media_file_name: Optional[str] = None

    if post.get("photo"):
        has_photo = True
        media_type = "photo"
        photos = post["photo"]
        if isinstance(photos, list) and photos:
            best = photos[-1]
            media_file_id = best.get("file_id")
            media_file_size = best.get("file_size")
            media_file_name = "reflection.jpg"
    else:
        has_photo = False

    video = post.get("video")
    document = post.get("document")
    audio = post.get("audio") or post.get("voice")

    if video:
        media_type = "video"
        media_file_id = video.get("file_id")
        media_file_size = video.get("file_size")
        media_file_name = video.get("file_name") or "reflection.mp4"
    elif document:
        media_type = "document"
        media_file_id = document.get("file_id")
        media_file_size = document.get("file_size")
        media_file_name = document.get("file_name") or "document.bin"
    elif audio:
        media_type = "audio"
        media_file_id = audio.get("file_id")
        media_file_size = audio.get("file_size")
        media_file_name = audio.get("file_name") or "audio.mp3"

    has_photo = bool(post.get("photo"))
    has_media = bool(video or document or audio)

    # Reactions (if included in post object)
    raw_reactions = post.get("reactions") or {}
    reactions = _sanitize_reactions(raw_reactions)
    total_reactions = sum(reactions.values())

    # Reply reference
    reply_to = post.get("reply_to_message")
    reply_to_id = int(reply_to["message_id"]) if reply_to and "message_id" in reply_to else None

    # Forward reference (supports Bot API 7.0+ forward_origin and legacy forward fields)
    is_forwarded = False
    forward_source_name: Optional[str] = None
    forward_source_type: Optional[str] = None
    forward_source_url: Optional[str] = None
    forward_date: Optional[datetime] = None

    raw_origin = post.get("forward_origin")
    if isinstance(raw_origin, dict):
        is_forwarded = True
        origin_type = raw_origin.get("type")
        forward_source_type = origin_type
        origin_date_ts = raw_origin.get("date")
        if origin_date_ts:
            origin_utc = datetime.fromtimestamp(origin_date_ts, tz=timezone.utc)
            forward_date = origin_utc.astimezone().replace(tzinfo=None)

        if origin_type == "channel":
            chat = raw_origin.get("chat") or {}
            forward_source_name = chat.get("title") or chat.get("username")
            username = chat.get("username")
            orig_msg_id = raw_origin.get("message_id")
            if username and orig_msg_id:
                forward_source_url = f"https://t.me/{username}/{orig_msg_id}"
            elif username:
                forward_source_url = f"https://t.me/{username}"
        elif origin_type == "chat":
            chat = raw_origin.get("sender_chat") or {}
            forward_source_name = chat.get("title") or chat.get("username")
            username = chat.get("username")
            if username:
                forward_source_url = f"https://t.me/{username}"
        elif origin_type == "user":
            u = raw_origin.get("sender_user") or {}
            name_parts = [u.get("first_name"), u.get("last_name")]
            forward_source_name = " ".join(filter(None, name_parts)).strip() or u.get("username")
            if u.get("username"):
                forward_source_url = f"https://t.me/{u.get('username')}"
        elif origin_type == "hidden_user":
            forward_source_name = raw_origin.get("sender_user_name")
    elif (
        post.get("forward_date")
        or post.get("forward_from")
        or post.get("forward_from_chat")
        or post.get("forward_sender_name")
    ):
        is_forwarded = True
        legacy_date_ts = post.get("forward_date")
        if legacy_date_ts:
            legacy_utc = datetime.fromtimestamp(legacy_date_ts, tz=timezone.utc)
            forward_date = legacy_utc.astimezone().replace(tzinfo=None)

        if post.get("forward_from_chat"):
            chat = post["forward_from_chat"]
            forward_source_type = chat.get("type", "channel")
            forward_source_name = chat.get("title") or chat.get("username")
            username = chat.get("username")
            orig_msg_id = post.get("forward_from_message_id")
            if username and orig_msg_id:
                forward_source_url = f"https://t.me/{username}/{orig_msg_id}"
            elif username:
                forward_source_url = f"https://t.me/{username}"
        elif post.get("forward_from"):
            u = post["forward_from"]
            forward_source_type = "user"
            name_parts = [u.get("first_name"), u.get("last_name")]
            forward_source_name = " ".join(filter(None, name_parts)).strip() or u.get("username")
            if u.get("username"):
                forward_source_url = f"https://t.me/{u.get('username')}"
        elif post.get("forward_sender_name"):
            forward_source_type = "hidden_user"
            forward_source_name = post.get("forward_sender_name")

    # Edit metadata
    edit_date_ts = post.get("edit_date")
    is_edited = bool(edit_date_ts)
    edit_date: Optional[datetime] = None
    if edit_date_ts:
        edit_utc = datetime.fromtimestamp(edit_date_ts, tz=timezone.utc)
        edit_date = edit_utc.astimezone().replace(tzinfo=None)

    return {
        "id": msg_id,
        "timestamp": dt_local,
        "text": text,
        "char_count": len(text),
        "word_count": len(text.split()),
        "tags": tags,
        "first_tag": first_tag,
        "reactions": reactions,
        "total_reactions": total_reactions,
        "reply_to_id": reply_to_id,
        "has_photo": has_photo,
        "has_media": has_media,
        "media_type": media_type,
        "media_file_id": media_file_id,
        "media_file_size": media_file_size,
        "media_file_name": media_file_name,
        "is_forwarded": is_forwarded,
        "forward_source_name": forward_source_name,
        "forward_source_type": forward_source_type,
        "forward_source_url": forward_source_url,
        "forward_date": forward_date,
        "is_edited": is_edited,
        "edit_date": edit_date,
        "discord_message_id": None,
        "date": dt_local.date(),
        "year": dt_local.year,
        "month": dt_local.month,
        "year_month": f"{dt_local.year:04d}-{dt_local.month:02d}",
        "day": dt_local.day,
        "day_of_week": dt_local.weekday(),
        "day_name": dt_local.strftime("%A"),
        "hour": dt_local.hour,
        "minute": dt_local.minute,
        "skip_discord": skip_discord,
    }


import json

def _save_delta_df(df: pd.DataFrame, path: Path) -> None:
    """Save delta DataFrame ensuring complex struct fields like reactions write safely."""
    save_df = df.copy()
    if "reactions" in save_df.columns:
        save_df["reactions"] = save_df["reactions"].apply(
            lambda r: json.dumps(r) if isinstance(r, dict) else "{}"
        )
    save_df.to_parquet(path, index=False)


def _load_delta_df(path: Path) -> pd.DataFrame:
    """Load delta DataFrame and restore reaction dictionaries."""
    df = pd.read_parquet(path)
    if "tags" in df.columns:
        df["tags"] = df["tags"].apply(lambda t: list(t) if hasattr(t, "__iter__") and not isinstance(t, (str, bytes)) else [])
    if "reactions" in df.columns:
        df["reactions"] = df["reactions"].apply(_sanitize_reactions)
        df["total_reactions"] = df["reactions"].apply(lambda r: sum(r.values()) if isinstance(r, dict) else 0)
    if "skip_discord" in df.columns:
        df["skip_discord"] = df["skip_discord"].fillna(False).astype(bool)
    if "is_forwarded" in df.columns:
        df["is_forwarded"] = df["is_forwarded"].fillna(False).astype(bool)
    if "is_edited" in df.columns:
        df["is_edited"] = df["is_edited"].fillna(False).astype(bool)
    if "discord_message_id" in df.columns:
        df["discord_message_id"] = df["discord_message_id"].astype(object)
    return df


def update_discord_message_id(
    msg_id: int,
    discord_message_id: Optional[str],
    delta_path: Optional[Path] = None,
) -> None:
    """Update or clear the stored discord_message_id for an entry in the live delta Parquet file."""
    path = delta_path or get_live_delta_path()
    if not path.exists():
        return
    try:
        df = _load_delta_df(path)
        if df.empty or msg_id not in df["id"].values:
            return
        if "discord_message_id" not in df.columns:
            df["discord_message_id"] = None
        df.loc[df["id"] == msg_id, "discord_message_id"] = (
            str(discord_message_id) if discord_message_id else None
        )
        _save_delta_df(df, path)
    except Exception as e:
        import logging
        logging.getLogger("live_sync").warning(f"[LiveSync] Failed to update discord_message_id for #{msg_id}: {e}")


def ingest_channel_post(
    post: Dict[str, Any],
    delta_path: Optional[Path] = None,
    suppress_tags: Optional[List[str]] = None,
    strip_suppress_tags: bool = True,
) -> Tuple[Dict[str, Any], bool]:
    """
    Ingest a channel post (new or edited) and persist it into the live delta Parquet file.
    Preserves existing discord_message_id upon edits.
    Returns (parsed_row_dict, is_new_entry).
    """
    row = parse_channel_post(
        post,
        suppress_tags=suppress_tags,
        strip_suppress_tags=strip_suppress_tags,
    )
    path = delta_path or get_live_delta_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    new_df = pd.DataFrame([row])
    # Ensure timestamp is datetime dtype
    new_df["timestamp"] = pd.to_datetime(new_df["timestamp"])

    is_new = True
    if path.exists():
        try:
            existing_df = _load_delta_df(path)
            if not existing_df.empty:
                # Check if this ID already existed
                if row["id"] in existing_df["id"].values:
                    is_new = False
                    prior_matches = existing_df.loc[existing_df["id"] == row["id"]]
                    if not prior_matches.empty:
                        prior_val = prior_matches.iloc[0].get("discord_message_id")
                        if pd.notna(prior_val) and str(prior_val).strip() and str(prior_val) != "None":
                            row["discord_message_id"] = str(prior_val).strip()
                            new_df["discord_message_id"] = row["discord_message_id"]

                # Combine and replace existing ID with updated version
                combined = pd.concat([existing_df, new_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["id"], keep="last")
                combined = combined.sort_values("timestamp").reset_index(drop=True)
                _save_delta_df(combined, path)
                return row, is_new
        except Exception:
            # If corrupted, overwrite with new df
            pass

    _save_delta_df(new_df, path)
    return row, is_new


def load_unified_journal(
    export_dir: Path,
    delta_path: Optional[Path] = None,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Load the unified journal dataset combining:
    1. Historical Base Archive (ChatExport directory via load_export)
    2. Live Delta Layer (live_messages.parquet)
    Deduplicates on message ID so live edits seamlessly supersede older copies.
    """
    base_df = load_export(export_dir, verbose=verbose)
    path = delta_path or get_live_delta_path(export_dir)

    if not path.exists():
        return base_df

    try:
        live_df = _load_delta_df(path)
        if live_df.empty:
            return base_df

        # Ensure schema alignment
        live_df["timestamp"] = pd.to_datetime(live_df["timestamp"])

        if "reactions" in live_df.columns:
            live_df["reactions"] = live_df["reactions"].apply(_sanitize_reactions)
            live_df["total_reactions"] = live_df["reactions"].apply(lambda r: sum(r.values()))

        # Combine base + live delta
        combined = pd.concat([base_df, live_df], ignore_index=True)
        # Deduplicate on ID, keeping the latest live entry
        unified = (
            combined.drop_duplicates(subset=["id"], keep="last")
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        if verbose:
            live_count = len(unified) - len(base_df)
            if live_count > 0:
                print(f"[LiveSync] Merged {live_count} live delta entries with historical archive.")

        # Filter out tombstoned/deleted IDs
        deleted_ids = get_deleted_ids(export_dir)
        if deleted_ids and not unified.empty:
            orig_len = len(unified)
            unified = unified[~unified["id"].isin(deleted_ids)].reset_index(drop=True)
            purged = orig_len - len(unified)
            if verbose and purged > 0:
                print(f"[LiveSync] Filtered {purged} deleted/tombstoned reflection(s) from unified archive.")

        return unified
    except Exception as e:
        if verbose:
            print(f"[LiveSync] Warning: Could not read live delta ({e}), using base archive.")
        return base_df


def get_deleted_ids_path(export_dir: Optional[Path] = None) -> Path:
    """Return path to persistent tombstone store for deleted reflection IDs."""
    if export_dir and export_dir.exists() and export_dir.is_dir():
        cache_dir = export_dir / ".cache"
    else:
        cache_dir = get_repo_root() / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "deleted_ids.json"


def get_deleted_ids(export_dir: Optional[Path] = None) -> set[int]:
    """Load set of tombstoned/deleted reflection message IDs."""
    path = get_deleted_ids_path(export_dir)
    if not path.exists():
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {int(i) for i in data if str(i).isdigit()}
    except Exception:
        return set()


def record_deleted_id(msg_id: int, export_dir: Optional[Path] = None) -> None:
    """Record a reflection ID in the persistent tombstone store."""
    path = get_deleted_ids_path(export_dir)
    current = get_deleted_ids(export_dir)
    current.add(int(msg_id))
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(current)), f, indent=2)
    except Exception as e:
        import logging
        logging.getLogger("live_sync").warning(f"[LiveSync] Failed to record tombstone for #{msg_id}: {e}")


def delete_channel_post(
    msg_id: int,
    delta_path: Optional[Path] = None,
    export_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """
    Purge a reflection from the live delta Parquet file and register its ID in the tombstone store.
    Returns the removed row dictionary (including discord_message_id) if found in delta.
    """
    record_deleted_id(msg_id, export_dir=export_dir)
    path = delta_path or get_live_delta_path(export_dir)

    removed_row: Optional[Dict[str, Any]] = None
    if path.exists():
        try:
            df = _load_delta_df(path)
            if not df.empty and msg_id in df["id"].values:
                match = df.loc[df["id"] == msg_id].iloc[0]
                removed_row = match.to_dict()
                df = df[df["id"] != msg_id].reset_index(drop=True)
                _save_delta_df(df, path)
        except Exception as e:
            import logging
            logging.getLogger("live_sync").warning(f"[LiveSync] Failed to purge #{msg_id} from delta: {e}")

    return removed_row


def reconcile_channel_deletions(
    client: Any,
    channel_id: int | str,
    delta_path: Optional[Path] = None,
    export_dir: Optional[Path] = None,
    discord_webhook_url: Optional[str] = None,
    limit: int = 50,
) -> List[int]:
    """
    Active reconciliation probe. Checks if the latest 'limit' delta messages
    still exist in the Telegram channel using zero-noise edit_message_reply_markup.
    Automatically purges deleted entries locally and from Discord.
    Returns list of detected deleted message IDs.
    """
    from src.bot.client import TelegramAPIError
    from src.bot.discord_relay import delete_discord_relay

    path = delta_path or get_live_delta_path(export_dir)
    if not path.exists():
        return []

    try:
        df = _load_delta_df(path)
        if df.empty:
            return []
    except Exception:
        return []

    probe_entries = df.tail(limit).to_dict(orient="records")
    reconciled_ids: List[int] = []

    for entry in probe_entries:
        mid = int(entry["id"])
        try:
            # Zero-noise probe: attempts to set reply markup (which is already None)
            client.edit_message_reply_markup(chat_id=channel_id, message_id=mid)
        except TelegramAPIError as e:
            err_str = str(e).lower()
            # If message was deleted in Telegram, Telegram returns 400 Bad Request
            if "message to edit not found" in err_str or "message can't be edited" in err_str or "message_id_invalid" in err_str:
                deleted_row = delete_channel_post(mid, delta_path=path, export_dir=export_dir)
                discord_id = (deleted_row or {}).get("discord_message_id") or entry.get("discord_message_id")
                if discord_webhook_url and discord_id:
                    delete_discord_relay(discord_webhook_url, str(discord_id))
                reconciled_ids.append(mid)
        except Exception:
            pass

    return reconciled_ids
