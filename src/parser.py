"""
Universal Telegram Desktop HTML Export Parser.

Parses Telegram channel or group chat HTML exports into structured pandas DataFrames.
Decouples data extraction from analysis so any export folder can be swapped seamlessly.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from bs4 import BeautifulSoup


def _sanitize_reactions(r: Any) -> Dict[str, int]:
    """Sanitize reaction dictionary, stripping out None/NaN/non-positive counts."""
    if isinstance(r, str):
        try:
            r = json.loads(r)
        except Exception:
            return {}
    if not isinstance(r, dict):
        return {}
    cleaned = {}
    for k, v in r.items():
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            try:
                c = int(v)
                if c > 0:
                    cleaned[str(k)] = c
            except (ValueError, TypeError):
                pass
    return cleaned


def _find_export_html_files(export_dir: Path) -> List[Path]:
    """
    Find and sort all messages*.html files in the export directory in numerical order.
    E.g.: messages.html (1), messages2.html (2), messages3.html (3), ...
    """
    html_files = list(export_dir.glob("messages*.html"))
    if not html_files:
        # Fallback to any html files in export_dir
        html_files = [p for p in export_dir.glob("*.html") if "messages" in p.name.lower()]

    def file_sort_key(path: Path) -> int:
        match = re.search(r"messages(\d+)?\.html$", path.name)
        if match:
            num = match.group(1)
            return int(num) if num else 1
        return 999999

    return sorted(html_files, key=file_sort_key)


def _extract_bracket_tags(text: str) -> List[str]:
    """
    Extract bracket tags like [project sekai], [work], [f1] from message text.
    Returns normalized lowercase tags.
    """
    raw_tags = re.findall(r"\[([a-zA-Z0-9 _\-\'\"\/]+)\]", text)
    tags = []
    for tag in raw_tags:
        cleaned = tag.strip().lower()
        if 1 <= len(cleaned) <= 35 and cleaned not in tags:
            tags.append(cleaned)
    return tags


def parse_telegram_html(file_path: Path) -> List[Dict[str, Any]]:
    """
    Parse a single Telegram export HTML file and return a list of message dicts.
    """
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    messages_data: List[Dict[str, Any]] = []
    message_divs = soup.find_all("div", class_=re.compile(r"\bmessage\b"))

    last_seen_dt: Optional[datetime] = None

    for msg in message_divs:
        classes = msg.get("class", [])
        if "service" in classes:
            # Service message (channel created, date dividers, etc.)
            continue

        raw_id = msg.get("id", "")
        id_match = re.search(r"message(\d+)", raw_id)
        msg_id = int(id_match.group(1)) if id_match else None

        # Timestamp from title attribute: e.g. "7 December 2023, 18:08:28"
        date_div = msg.find("div", class_=re.compile(r"\bdate\b"))
        dt: Optional[datetime] = None
        if date_div and date_div.get("title"):
            title_str = date_div["title"].strip()
            clean_title = title_str.split(" UTC")[0].strip()
            for fmt in (
                "%d %B %Y, %H:%M:%S",
                "%d %B %Y %H:%M:%S",
                "%d.%m.%Y %H:%M:%S",
                "%d-%m-%Y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
            ):
                try:
                    dt = datetime.strptime(clean_title, fmt)
                    last_seen_dt = dt
                    break
                except ValueError:
                    pass

        if dt is None:
            dt = last_seen_dt

        # Text content
        text_div = msg.find("div", class_="text")
        text = ""
        if text_div:
            # Replace <br> with newline to preserve paragraph structure
            for br in text_div.find_all("br"):
                br.replace_with("\n")
            text = text_div.get_text().strip()

        # Tags extracted from brackets
        tags = _extract_bracket_tags(text)
        first_tag = tags[0] if tags else None

        # Reactions
        reactions: Dict[str, int] = {}
        total_reactions = 0
        reactions_div = msg.find("div", class_="reactions")
        if reactions_div:
            reaction_spans = reactions_div.find_all("span", class_="reaction")
            for r_span in reaction_spans:
                emoji_elem = r_span.find("span", class_="emoji")
                count_elem = r_span.find("span", class_="count")
                if emoji_elem:
                    emoji = emoji_elem.get_text().strip()
                    count = int(count_elem.get_text().strip()) if count_elem else 1
                    reactions[emoji] = count
                    total_reactions += count

        # Reply reference
        reply_to_id: Optional[int] = None
        reply_div = msg.find("div", class_="reply_to")
        if reply_div:
            reply_link = reply_div.find("a", href=re.compile(r"#go_to_message\d+"))
            if reply_link and reply_link.get("href"):
                rep_match = re.search(r"message(\d+)", reply_link["href"])
                if rep_match:
                    reply_to_id = int(rep_match.group(1))

        # Media checks
        has_photo = bool(msg.find("div", class_=re.compile(r"media_photo")))
        has_media = bool(msg.find("div", class_=re.compile(r"media_wrap")))

        # Forward checks
        fwd_div = msg.find("div", class_=re.compile(r"forwarded"))
        is_forwarded = bool(fwd_div)
        forward_source_name: Optional[str] = None
        if is_forwarded and fwd_div:
            from_name = fwd_div.find("div", class_="from_name")
            if from_name:
                forward_source_name = from_name.get_text().strip()

        messages_data.append(
            {
                "id": msg_id,
                "timestamp": dt,
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
                "is_forwarded": is_forwarded,
                "forward_source_name": forward_source_name,
            }
        )

    return messages_data


def load_export(
    export_dir_path: str | Path,
    use_cache: bool = True,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Universal entry point to load and parse any Telegram export folder.

    Parameters:
        export_dir_path: Path to the ChatExport folder.
        use_cache: If True, uses/updates a fast cache inside .cache/
        verbose: If True, prints parsing progress.

    Returns:
        pd.DataFrame containing structured message logs with calendar features.
    """
    export_dir = Path(export_dir_path).expanduser().resolve()
    if not export_dir.exists() or not export_dir.is_dir():
        raise FileNotFoundError(f"Export directory not found: {export_dir}")

    html_files = _find_export_html_files(export_dir)
    if not html_files:
        raise FileNotFoundError(f"No messages*.html files found in {export_dir}")

    cache_dir = export_dir / ".cache"
    cache_file = cache_dir / "parsed_messages.parquet"

    # Check cache validity against newest HTML file
    newest_mtime = max(f.stat().st_mtime for f in html_files)
    if use_cache and cache_file.exists():
        if cache_file.stat().st_mtime >= newest_mtime:
            if verbose:
                print(f"[Parser] Loading cached data from {cache_file.name}...")
            df = pd.read_parquet(cache_file)
            if "tags" in df.columns:
                df["tags"] = df["tags"].apply(lambda t: list(t) if hasattr(t, "__iter__") and not isinstance(t, (str, bytes)) else [])
            if "reactions" in df.columns:
                df["reactions"] = df["reactions"].apply(_sanitize_reactions)
                df["total_reactions"] = df["reactions"].apply(lambda r: sum(r.values()))
            return df

    if verbose:
        print(f"[Parser] Found {len(html_files)} HTML export file(s) in {export_dir.name}:")
        for f in html_files:
            print(f"  - {f.name} ({f.stat().st_size / 1024:.1f} KB)")
        print("[Parser] Parsing messages...")

    all_messages: List[Dict[str, Any]] = []
    for f in html_files:
        all_messages.extend(parse_telegram_html(f))

    if not all_messages:
        raise ValueError("No valid messages found in export HTML files.")

    df = pd.DataFrame(all_messages)

    # Clean and order
    if "id" in df.columns and df["id"].notna().any():
        df = df.drop_duplicates(subset=["id"]).sort_values("id").reset_index(drop=True)

    # Ensure timestamp is datetime
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # Sanitize reactions and total reactions
    if "reactions" in df.columns:
        df["reactions"] = df["reactions"].apply(_sanitize_reactions)
        df["total_reactions"] = df["reactions"].apply(lambda r: sum(r.values()))

    # Temporal feature engineering
    df["date"] = df["timestamp"].dt.date
    df["year"] = df["timestamp"].dt.year
    df["month"] = df["timestamp"].dt.month
    df["year_month"] = df["timestamp"].dt.to_period("M").astype(str)
    df["day"] = df["timestamp"].dt.day
    df["day_of_week"] = df["timestamp"].dt.dayofweek  # 0=Monday, 6=Sunday
    df["day_name"] = df["timestamp"].dt.day_name()
    df["hour"] = df["timestamp"].dt.hour
    df["minute"] = df["timestamp"].dt.minute

    if verbose:
        print(f"[Parser] Successfully parsed {len(df):,} messages.")
        print(f"[Parser] Time range: {df['timestamp'].min()} -> {df['timestamp'].max()}")

    # Save cache
    if use_cache:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache_file, index=False)
            if verbose:
                print(f"[Parser] Saved cache to {cache_file}")
        except Exception as e:
            if verbose:
                print(f"[Parser] Note: Could not write cache file ({e}). Continuing without cache.")

    return df
