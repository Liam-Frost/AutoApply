"""Shared HTML utilities for ATS scrapers."""

from __future__ import annotations

from html.parser import HTMLParser


class _HTMLStripper(HTMLParser):
    """Strips HTML tags, extracting text content."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def strip_html(html: str) -> str:
    """Remove HTML tags from a string, returning plain text."""
    if not html:
        return ""
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()
