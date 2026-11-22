"""
Weekly Digest Domain Logic.

Extracts, filters, and groups Telegram journal entries into Sunday-to-Saturday
weekly cycles, indexes bracket tags, and calculates summary metrics.
Zero dependencies on Notion or external networks.
"""

from __future__ import annotations

import collections
from datetime import date, datetime, timedelta
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .models import DayGroup, DigestEntry, WeeklyDigest


DAY_NAMES = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
]


def _safe_int(val: Any, default: int = 0) -> int:
    """Safely convert value to integer, handling NaN, None, and strings."""
    if val is None or pd.isna(val):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_sunday_start_bounds(target_date: date) -> Tuple[date, date]:
    """
    Given any calendar date, compute the Sunday-to-Saturday window containing it.
    Sunday is the first day of the weekly recap cycle (index 0).
    """
    # Python weekday(): Monday is 0, Sunday is 6
    # Days since preceding Sunday: (weekday + 1) % 7
    days_since_sunday = (target_date.weekday() + 1) % 7
    sunday = target_date - timedelta(days=days_since_sunday)
    saturday = sunday + timedelta(days=6)
    return sunday, saturday


def get_previous_week_bounds(reference_date: Optional[date] = None) -> Tuple[date, date]:
    """
    Get the Sunday-to-Saturday window for the week preceding reference_date.
    Defaults to date.today() if reference_date is omitted.
    """
    ref = reference_date or date.today()
    current_sun, _ = get_sunday_start_bounds(ref)
    prev_sun = current_sun - timedelta(days=7)
    prev_sat = prev_sun + timedelta(days=6)
    return prev_sun, prev_sat


def parse_week_label(week_label: str) -> Tuple[int, int]:
    """
    Parses strings like '2026-48' or '2026-W48' into (year, week_num).
    Raises ValueError on invalid formats.
    """
    match = re.match(r"^(\d{4})[-_]?[wW]?(\d{1,2})$", week_label.strip())
    if not match:
        raise ValueError(
            f"Invalid week label format '{week_label}'. Expected format 'YYYY-WW' (e.g. '2026-48')."
        )
    return int(match.group(1)), int(match.group(2))


def week_bounds_from_label(week_label: str) -> Tuple[date, date, str]:
    """
    Calculates Sunday-to-Saturday date bounds from a week label like '2026-47'.
    Follows standard ISO calendar week definition where Monday belongs to ISO week N,
    and Sunday is the preceding start day of the 7-day recap window.
    """
    year, week_num = parse_week_label(week_label)
    # ISO Monday for week_num (%G=ISO year, %V=ISO week, %u=1 for Monday)
    iso_mon = datetime.strptime(f"{year}-W{week_num:02d}-1", "%G-W%V-%u").date()
    # Sunday preceding Monday:
    sunday = iso_mon - timedelta(days=1)
    saturday = sunday + timedelta(days=6)
    canonical_label = f"{year}-{week_num:02d}"
    return sunday, saturday, canonical_label


def format_week_label(sunday: date) -> str:
    """
    Generate canonical 'YYYY-WW' label for a Sunday-starting week.
    Follows true calendar week where Monday (sunday + 1 day) defines the ISO week number.
    """
    monday = sunday + timedelta(days=1)
    iso_year, iso_week, _ = monday.isocalendar()
    return f"{iso_year}-{iso_week:02d}"


def build_weekly_digest(
    df: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    label: Optional[str] = None,
    week_label: Optional[str] = None,
) -> WeeklyDigest:
    """
    Build a complete WeeklyDigest object from a Telegram messages DataFrame.

    Parameters:
        df: DataFrame parsed via src.parser.load_export
        start_date: Start date of the week (Sunday).
        end_date: End date of the week (Saturday).
        label: Custom label (e.g. '2026-48').
        week_label: Optional shorthand string like '2026-48' to auto-resolve bounds.

    Returns:
        WeeklyDigest dataclass instance.
    """
    if df.empty:
        raise ValueError("Cannot build weekly digest from an empty DataFrame.")

    # Auto-resolve bounds if week_label passed
    if week_label:
        start_date, end_date, resolved_label = week_bounds_from_label(week_label)
        label = label or resolved_label

    if start_date is None or end_date is None:
        raise ValueError("Both start_date and end_date must be provided or resolved.")

    if start_date > end_date:
        raise ValueError(f"start_date ({start_date}) cannot be after end_date ({end_date}).")

    if label is None:
        label = format_week_label(start_date)

    year, week_num = parse_week_label(label)

    # Ensure timestamp and date columns exist
    working_df = df.copy()
    if "date" not in working_df.columns:
        if "timestamp" not in working_df.columns:
            raise KeyError("DataFrame must contain 'timestamp' or 'date' column.")
        working_df["timestamp"] = pd.to_datetime(working_df["timestamp"])
        working_df["date"] = working_df["timestamp"].dt.date
    else:
        # Convert date column to datetime.date if not already
        working_df["date"] = pd.to_datetime(working_df["date"]).dt.date

    # Filter messages within date range [start_date, end_date]
    mask = (working_df["date"] >= start_date) & (working_df["date"] <= end_date)
    # Ignore soft-deleted / tombstoned items if present
    if "is_deleted" in working_df.columns:
        mask &= ~working_df["is_deleted"].fillna(False).astype(bool)

    window_df = working_df[mask].sort_values("timestamp").reset_index(drop=True)

    # Build 7 calendar days starting from Sunday
    days: List[DayGroup] = []
    tagged_groups: Dict[str, List[DigestEntry]] = collections.defaultdict(list)
    all_tag_counts: collections.Counter[str] = collections.Counter()
    total_photos = 0

    curr_date = start_date
    while curr_date <= end_date:
        day_name = curr_date.strftime("%A")
        day_entries: List[DigestEntry] = []
        day_words = 0
        day_tags: List[str] = []
        day_has_media = False

        day_subset = window_df[window_df["date"] == curr_date]
        for _, row in day_subset.iterrows():
            ts = pd.to_datetime(row["timestamp"])
            time_str = ts.strftime("%H:%M")
            tags = list(row.get("tags") or [])
            if hasattr(tags, "__iter__") and not isinstance(tags, (str, bytes)):
                tags = [str(t).strip().lower() for t in tags if str(t).strip()]
            else:
                tags = []

            has_photo = bool(row.get("has_photo", False))
            has_media = bool(row.get("has_media", False)) or has_photo
            if has_photo:
                total_photos += 1
            if has_media:
                day_has_media = True

            reactions = row.get("reactions") or {}
            if not isinstance(reactions, dict):
                reactions = {}

            entry = DigestEntry(
                id=_safe_int(row.get("id"), 0),
                timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                date_str=str(curr_date),
                time_str=time_str,
                day_name=day_name,
                day_of_week=curr_date.weekday(),
                text=str(row.get("text", "") or "").strip(),
                word_count=_safe_int(row.get("word_count"), 0),
                char_count=_safe_int(row.get("char_count"), 0),
                tags=tags,
                has_photo=has_photo,
                has_media=has_media,
                media_type=str(row.get("media_type")) if pd.notna(row.get("media_type")) else None,
                media_path=str(row.get("media_file_name")) if pd.notna(row.get("media_file_name")) else None,
                reactions=reactions,
                total_reactions=_safe_int(row.get("total_reactions"), 0),
            )

            day_entries.append(entry)
            day_words += entry.word_count

            for t in tags:
                if t not in day_tags:
                    day_tags.append(t)
                all_tag_counts[t] += 1
                tagged_groups[t].append(entry)

        day_group = DayGroup(
            date_str=str(curr_date),
            day_name=day_name,
            entries=day_entries,
            total_messages=len(day_entries),
            total_words=day_words,
            has_media=day_has_media,
            tags=day_tags,
        )
        days.append(day_group)
        curr_date += timedelta(days=1)

    total_messages = sum(d.total_messages for d in days)
    total_words = sum(d.total_words for d in days)
    active_days = sum(1 for d in days if d.total_messages > 0)
    sorted_tags = all_tag_counts.most_common()

    return WeeklyDigest(
        label=label,
        year=year,
        week_num=week_num,
        start_date=str(start_date),
        end_date=str(end_date),
        days=days,
        tagged_groups=dict(tagged_groups),
        total_messages=total_messages,
        total_words=total_words,
        active_days=active_days,
        total_photos=total_photos,
        all_tags=sorted_tags,
    )
