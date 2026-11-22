"""
Weekly Digest HTML Renderer (Bridge).

Delegates rendering to src.digest.visual using the centralized Jinja2 template engine
(templates/weekly_digest.html). Retained for clean backwards compatibility.
"""

from __future__ import annotations

from .models import WeeklyDigest
from .visual import render_digest_html, generate_digest_html_file

# Backwards compatible alias
format_digest_html = render_digest_html

__all__ = [
    "format_digest_html",
    "render_digest_html",
    "generate_digest_html_file",
]
