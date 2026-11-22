"""
Weekly Digest Visual Presentation Layer.

Transforms WeeklyDigest domain models into template context and renders
interactive Notion-like HTML dashboards via the centralized Jinja2 engine (src/renderer.py).
Zero embedded HTML strings. Matches the user's authentic Notion journal page layout.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.renderer import render_template, render_to_file
from .models import DayGroup, DigestEntry, WeeklyDigest
from .formatter import format_digest_markdown, format_digest_json


def _format_wordle_text(raw_text: str) -> str:
    """Formats Wordle or puzzle emoji lines with compact breaks."""
    lines = raw_text.splitlines()
    escaped_lines: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect grid lines (lines composed largely of emoji blocks)
        if any(block in line for block in ["⬛", "🟩", "🟨", "🟦", "🟪", "⬜"]):
            grid_group = [html.escape(line)]
            while i + 1 < len(lines) and any(block in lines[i + 1] for block in ["⬛", "🟩", "🟨", "🟦", "🟪", "⬜"]):
                i += 1
                grid_group.append(html.escape(lines[i]))
            escaped_lines.append("<br />".join(grid_group))
        else:
            escaped_lines.append(html.escape(line))
        i += 1
    return "<br />".join(escaped_lines)


def format_digest_visual_context(digest: WeeklyDigest) -> Dict[str, Any]:
    """
    Constructs the structured context dictionary required by templates/weekly_digest.html.
    Faithfully matches the user's authentic Notion weekly recap page.
    """
    # Format header dates nicely
    try:
        start_dt = datetime.strptime(digest.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(digest.end_date, "%Y-%m-%d")
        date_range_str = f"{start_dt.strftime('%b %d, %Y')} → {end_dt.strftime('%b %d, %Y')}"
    except Exception:
        date_range_str = f"{digest.start_date} → {digest.end_date}"

    # Build daily data matching Notion structure
    days_data: List[Dict[str, Any]] = []
    for day in digest.days:
        has_photo = day.has_media or any(e.has_photo for e in day.entries)
        photos = [e.media_path or "reflection.jpg" for e in day.entries if e.has_photo]

        entries_data = []
        for e in day.entries:
            text_clean = e.text.strip()
            formatted_html = _format_wordle_text(text_clean) if text_clean else "<i>(Media only reflection)</i>"

            # Transform bracket tags like [reading] into Notion mention pills
            for t in e.tags:
                escaped_tag = html.escape(f"[{t}]")
                mention_pill = f'<span class="notion-mention">🏷️ {html.escape(t)}</span>'
                formatted_html = formatted_html.replace(escaped_tag, mention_pill)

            entries_data.append({
                "id": e.id,
                "time_str": e.time_str,
                "formatted_html": formatted_html,
                "tags": e.tags,
                "has_photo": e.has_photo,
                "media_path": e.media_path,
            })

        days_data.append({
            "day_name": day.day_name,
            "date_str": day.date_str,
            "has_photo": has_photo and bool(photos),
            "photos": photos,
            "entries": entries_data,
        })

    return {
        "digest": digest,
        "date_range_str": date_range_str,
        "days_data": days_data,
        "markdown_source": format_digest_markdown(digest),
        "json_source": format_digest_json(digest, indent=2),
    }


def render_digest_html(digest: WeeklyDigest) -> str:
    """
    Renders a WeeklyDigest into a standalone HTML string via templates/weekly_digest.html.
    """
    context = format_digest_visual_context(digest)
    return render_template("weekly_digest.html", context)


def generate_digest_html_file(
    digest: WeeklyDigest,
    output_path: Union[str, Path],
) -> Path:
    """
    Renders and writes the standalone Weekly Digest HTML dashboard to disk.
    """
    out_file = Path(output_path).expanduser().resolve()
    context = format_digest_visual_context(digest)
    return render_to_file("weekly_digest.html", context, out_file)
