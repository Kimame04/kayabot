"""
Weekly Digest Domain Models.

Strongly typed dataclasses representing extracted weekly journal entries,
day groupings, and tag-routed memory clusters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class DigestEntry:
    """Represents an individual journal entry within the weekly window."""
    id: int
    timestamp: datetime
    date_str: str
    time_str: str
    day_name: str
    day_of_week: int  # 0=Monday, 6=Sunday (Python standard)
    text: str
    word_count: int
    char_count: int
    tags: List[str] = field(default_factory=list)
    has_photo: bool = False
    has_media: bool = False
    media_type: Optional[str] = None
    media_path: Optional[str] = None
    reactions: Dict[str, int] = field(default_factory=dict)
    total_reactions: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "date": self.date_str,
            "time": self.time_str,
            "day_name": self.day_name,
            "day_of_week": self.day_of_week,
            "text": self.text,
            "word_count": self.word_count,
            "char_count": self.char_count,
            "tags": list(self.tags),
            "has_photo": self.has_photo,
            "has_media": self.has_media,
            "media_type": self.media_type,
            "media_path": self.media_path,
            "reactions": self.reactions,
            "total_reactions": self.total_reactions,
        }


@dataclass
class DayGroup:
    """Represents all entries logged on a single calendar day."""
    date_str: str
    day_name: str
    entries: List[DigestEntry] = field(default_factory=list)
    total_messages: int = 0
    total_words: int = 0
    has_media: bool = False
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date_str,
            "day_name": self.day_name,
            "total_messages": self.total_messages,
            "total_words": self.total_words,
            "has_media": self.has_media,
            "tags": self.tags,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass
class WeeklyDigest:
    """
    Complete weekly digest package containing Sunday-to-Saturday daily groups,
    tag-based cross-posting buckets, and high-level summary KPIs.
    """
    label: str               # e.g., "2026-48"
    year: int
    week_num: int
    start_date: str          # Sunday ISO date "YYYY-MM-DD"
    end_date: str            # Saturday ISO date "YYYY-MM-DD"
    days: List[DayGroup]     # 7 days (Sunday through Saturday)
    tagged_groups: Dict[str, List[DigestEntry]] = field(default_factory=dict)
    total_messages: int = 0
    total_words: int = 0
    active_days: int = 0
    total_photos: int = 0
    all_tags: List[Tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "year": self.year,
            "week_num": self.week_num,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "summary": {
                "total_messages": self.total_messages,
                "total_words": self.total_words,
                "active_days": self.active_days,
                "total_photos": self.total_photos,
                "tags_summary": [{"tag": t, "count": c} for t, c in self.all_tags],
            },
            "days": [d.to_dict() for d in self.days],
            "tagged_groups": {
                tag: [e.to_dict() for e in entries]
                for tag, entries in self.tagged_groups.items()
            },
        }
