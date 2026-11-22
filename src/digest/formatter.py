"""
Weekly Digest Formatter & Serializer.

Converts WeeklyDigest domain models into structured JSON and clean Markdown
documents matching the user's journal conventions. Zero external dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .models import DayGroup, DigestEntry, WeeklyDigest


def format_digest_json(digest: WeeklyDigest, indent: int = 2) -> str:
    """
    Serialize WeeklyDigest to a formatted JSON string.
    Preserves Unicode emojis (ensure_ascii=False).
    """
    return json.dumps(digest.to_dict(), indent=indent, ensure_ascii=False)


def format_digest_markdown(digest: WeeklyDigest) -> str:
    """
    Renders WeeklyDigest to clean Markdown matching the user's Notion structure:
    - 7 days (Sunday to Saturday) with daily bullet points
    - Media annotations
    - Template slots for Weekly Retrospectives (Biggest win, Biggest challenge, etc.)
    """
    lines: List[str] = []

    # Title & Metadata
    lines.append(f"# 🧩 {digest.label}")
    lines.append("")
    lines.append(
        f"*Period: {digest.start_date} (Sunday) to {digest.end_date} (Saturday) • "
        f"{digest.total_messages:,} entries • {digest.total_words:,} words • "
        f"{digest.active_days}/7 active days*"
    )

    if digest.all_tags:
        top_tags_str = ", ".join(f"`[{t}]` ({c})" for t, c in digest.all_tags[:8])
        lines.append(f"*Active Topics: {top_tags_str}*")

    lines.append("")
    lines.append("## A quick summary of events that happened the last week")
    lines.append("")

    for day in digest.days:
        lines.append(f"- **{day.day_name}** ({day.date_str})")
        if not day.entries:
            lines.append("  - *(No entries logged)*")
        else:
            for entry in day.entries:
                # Format text with indentation if multiline
                raw_text = entry.text
                if entry.has_photo or entry.has_media:
                    media_name = entry.media_path or ("Photo" if entry.has_photo else "Media")
                    media_tag = f" 📷 *[{media_name}]*"
                else:
                    media_tag = ""

                text_lines = raw_text.splitlines() if raw_text else ["*(Media only)*"]
                first_line = text_lines[0] + media_tag
                lines.append(f"  - {first_line}")
                for sub_line in text_lines[1:]:
                    if sub_line.strip():
                        lines.append(f"    {sub_line}")
                    else:
                        lines.append("")
        lines.append("")

    # Weekly Retrospective Template (exact match with user's Notion structure)
    lines.append("## Biggest win")
    lines.append("")
    lines.append("One sentence describing the greatest accomplishment of the week")
    lines.append("")
    lines.append("## Biggest challenge")
    lines.append("")
    lines.append("One sentence describing your greatest concern or obstacle faced this week")
    lines.append("")
    lines.append("## Looking back on this week’s goals")
    lines.append("")
    lines.append("## Outcomes for next week")
    lines.append("")
    lines.append("1. Health")
    lines.append("2. Work")
    lines.append("3. Social")
    lines.append("4. Educational")
    lines.append("5. Leisure")
    lines.append("")

    return "\n".join(lines)


def export_digest(
    digest: WeeklyDigest,
    out_dir: Union[str, Path],
    formats: Optional[List[str]] = None,
) -> Dict[str, Path]:
    """
    Exports the weekly digest into the specified formats in out_dir.

    Parameters:
        digest: The WeeklyDigest instance.
        out_dir: Directory where files will be created.
        formats: List of formats to generate, e.g. ["json", "md"]. Defaults to both.

    Returns:
        Dict mapping format name to written Path.
    """
    target_formats = [f.lower().strip() for f in (formats or ["json", "md"])]
    output_path = Path(out_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    written_files: Dict[str, Path] = {}
    safe_label = digest.label.replace("/", "-").replace(" ", "_")

    if "json" in target_formats:
        json_file = output_path / f"digest_{safe_label}.json"
        json_content = format_digest_json(digest)
        json_file.write_text(json_content, encoding="utf-8")
        written_files["json"] = json_file

    if "md" in target_formats or "markdown" in target_formats:
        md_file = output_path / f"digest_{safe_label}.md"
        md_content = format_digest_markdown(digest)
        md_file.write_text(md_content, encoding="utf-8")
        written_files["md"] = md_file

    if "html" in target_formats:
        from .visual import generate_digest_html_file
        html_file = output_path / f"digest_{safe_label}.html"
        generate_digest_html_file(digest, html_file)
        written_files["html"] = html_file

    return written_files
