"""
Weekly Digest Feature Package.

Extracts structured weekly journal digests and tag-routed memory streams
from Telegram channel history.
"""

from .models import DayGroup, DigestEntry, WeeklyDigest
from .logic import (
    build_weekly_digest,
    format_week_label,
    get_previous_week_bounds,
    get_sunday_start_bounds,
    parse_week_label,
    week_bounds_from_label,
)
from .formatter import (
    export_digest,
    format_digest_json,
    format_digest_markdown,
)
from .visual import render_digest_html, generate_digest_html_file
from .html_renderer import format_digest_html

__all__ = [
    "DigestEntry",
    "DayGroup",
    "WeeklyDigest",
    "build_weekly_digest",
    "export_digest",
    "format_digest_html",
    "format_digest_json",
    "format_digest_markdown",
    "format_week_label",
    "generate_digest_html_file",
    "get_previous_week_bounds",
    "get_sunday_start_bounds",
    "parse_week_label",
    "render_digest_html",
    "week_bounds_from_label",
]
