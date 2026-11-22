"""
Test helpers and fixtures for self-contained automated testing.
"""

from __future__ import annotations

from pathlib import Path
from src.synthetic import generate_synthetic_journal, export_to_telegram_html


def get_test_export_dir() -> Path:
    """
    Return path to a valid Telegram export directory for testing.
    Prioritizes ChatExport_sample, falls back to private export if present,
    or generates ChatExport_sample on-the-fly so tests are 100% self-contained.
    """
    sample_dir = Path("ChatExport_sample")
    if sample_dir.exists() and (sample_dir / "messages.html").exists():
        return sample_dir

    for candidate in sorted(Path(".").glob("ChatExport_*")):
        if candidate.is_dir() and candidate.name != "ChatExport_sample" and (candidate / "messages.html").exists():
            return candidate

    # Generate synthetic sample fixture on-the-fly
    messages = generate_synthetic_journal(num_messages=400, seed=42)
    export_to_telegram_html(messages, sample_dir, messages_per_file=250)
    return sample_dir
