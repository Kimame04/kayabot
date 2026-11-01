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


def parse_channel_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a Telegram Bot API channel_post object into the standard DataFrame row dictionary.
    Guarantees 100% schema alignment with src.parser.load_export.
    """
    msg_id = int(post.get("message_id", 0))
    raw_date = post.get("date", 0)

    # Telegram API dates are UTC Unix timestamps
    dt_utc = datetime.fromtimestamp(raw_date, tz=timezone.utc)
    # Convert to naive local datetime to match Telegram Desktop HTML exports
    dt_local = dt_utc.astimezone().replace(tzinfo=None)

    text = post.get("text") or post.get("caption") or ""
    tags = _extract_bracket_tags(text)
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
        "date": dt_local.date(),
        "year": dt_local.year,
        "month": dt_local.month,
        "year_month": f"{dt_local.year:04d}-{dt_local.month:02d}",
        "day": dt_local.day,
        "day_of_week": dt_local.weekday(),
        "day_name": dt_local.strftime("%A"),
        "hour": dt_local.hour,
        "minute": dt_local.minute,
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
    return df


def ingest_channel_post(
    post: Dict[str, Any],
    delta_path: Optional[Path] = None,
) -> Tuple[Dict[str, Any], bool]:
    """
    Ingest a channel post (new or edited) and persist it into the live delta Parquet file.
    Returns (parsed_row_dict, is_new_entry).
    """
    row = parse_channel_post(post)
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
        return unified
    except Exception as e:
        if verbose:
            print(f"[LiveSync] Warning: Could not read live delta ({e}), using base archive.")
        return base_df
