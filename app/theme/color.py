"""Conversion of theme colour values to `QColor`.

Themes store colours as CSS strings because they go straight into QSS. Code
that paints manually needs `QColor`, including for the `rgba(r, g, b, a)` form
that `QColor` does not parse on its own.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QColor

_RGBA_RE = re.compile(
    r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)',
    re.IGNORECASE,
)


def to_color(value: str) -> QColor:
    """Convert `'#1e2126'` or `'rgba(0, 0, 0, 165)'` into a `QColor`."""
    match = _RGBA_RE.fullmatch((value or '').strip())
    if match is None:
        return QColor(value)

    red, green, blue, alpha = match.groups()
    if alpha is None:
        return QColor(int(red), int(green), int(blue))
    # CSS allows 0-1 fractions as well as Qt's 0-255 notation
    alpha_value = float(alpha)
    alpha_255 = round(alpha_value * 255) if alpha_value <= 1 else round(alpha_value)
    return QColor(int(red), int(green), int(blue), max(0, min(255, alpha_255)))
