"""Theme model: the complete interface colour set.

Every field name doubles as the token name in `assets/styles/main.qss`, so
`surface_secondary` fills the `SURFACE_SECONDARY` placeholder. Adding a colour
therefore never requires updating a mapping table.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Theme:
    """A coherent colour set for the whole interface."""

    key: str
    name: str
    is_dark: bool

    # --- surfaces ---
    background: str  # window background
    surface: str  # panels, cards, input fields
    surface_secondary: str  # toolbars, headers, alternating rows
    surface_hover: str
    surface_active: str  # pressed or active element

    # --- lines ---
    border: str  # ordinary borders and card frames
    border_strong: str  # borders of editable controls
    separator: str  # section dividers

    # --- text ---
    text_primary: str
    text_secondary: str
    text_disabled: str
    text_on_accent: str  # label on an accent-coloured button
    link: str

    # --- accent ---
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str  # background of a selected row
    focus: str  # border of the focused control

    # --- download statuses ---
    success: str
    warning: str
    error: str
    info: str

    # --- individual elements ---
    progress_track: str
    scrollbar: str
    scrollbar_hover: str
    tooltip_background: str
    tooltip_text: str
    menu_background: str
    log_background: str
    placeholder_background: str  # thumbnail frame before the image loads
    overlay_scrim: str  # translucent badge drawn over a thumbnail
    overlay_text: str  # text on that badge

    def tokens(self) -> dict[str, str]:
        """Map of QSS placeholders to values."""
        return {
            f'{{{{{field.name.upper()}}}}}': getattr(self, field.name)
            for field in dataclasses.fields(self)
            if isinstance(getattr(self, field.name), str)
        }
