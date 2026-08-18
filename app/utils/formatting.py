"""Value formatting for display. Units and separators only, no translated words."""

from __future__ import annotations

import re

_UNITS = ('B', 'KB', 'MB', 'GB', 'TB')
URL_RE = re.compile(r'https?://[^\s<>"\']+')

DASH = '—'


def size(value: float | None) -> str:
    """Bytes to a human readable size, e.g. `24.8 MB`."""
    if not value or value < 0:
        return DASH
    amount = float(value)
    for unit in _UNITS:
        if amount < 1024 or unit == _UNITS[-1]:
            precision = 0 if unit == 'B' or amount >= 100 else 1
            return f'{amount:.{precision}f} {unit}'
        amount /= 1024
    return DASH


def speed(value: float | None) -> str:
    if not value or value <= 0:
        return DASH
    return f'{size(value)}/s'


def duration(seconds: float | None) -> str:
    """Seconds to `22:08` or `1:04:45`."""
    if seconds is None or seconds < 0:
        return DASH
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    return f'{minutes:02d}:{secs:02d}'


def eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return DASH
    return duration(seconds)


def bitrate(value: float | None) -> str:
    if not value or value <= 0:
        return DASH
    return f'{round(value)} kbps'


def fps(value: float | None) -> str:
    if not value:
        return ''
    return f'{round(value)} FPS'


def join(*parts: str) -> str:
    """Join non-empty parts with a middle dot."""
    return ' · '.join(p for p in parts if p and p != DASH)


def dot_join(*parts: str) -> str:
    """Bullet-separated variant used in format lists."""
    return ' • '.join(p for p in parts if p and p != DASH)


def extract_urls(text: str) -> list[str]:
    """Extract URLs from arbitrary text, de-duplicated, in order of appearance."""
    found = URL_RE.findall(text or '')
    return list(dict.fromkeys(url.rstrip('.,);]') for url in found))


def plural_items(count: int) -> str:
    """Polish plural form for the item counter.

    Kept for the tests that assert the grammar; the UI uses Qt plural forms.
    """
    if count == 1:
        return 'pozycja'
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return 'pozycje'
    return 'pozycji'


def elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(1, limit - 1)] + '…'
