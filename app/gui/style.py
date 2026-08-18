"""Wymiary interfejsu.

Colours no longer live here; they belong to `app/theme`. This module keeps
only the metrics needed for manual painting and layout, so that the card
delegate and the widgets work with the same numbers.
"""

from __future__ import annotations

# --- download queue card ---
THUMB_WIDTH = 96
THUMB_HEIGHT = 54
CARD_HEIGHT = 76
CARD_PADDING = 12
CARD_GAP = 14
#: Status column width; must fit the longest label ("Post-processing")
STATUS_COLUMN = 132

# --- media preview in the download dialog ---
PREVIEW_WIDTH = 128
PREVIEW_HEIGHT = 72
