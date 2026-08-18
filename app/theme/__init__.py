"""Application theming.

Public API:

    from app.theme import ThemeManager, active_theme

`active_theme()` returns the theme currently applied to the application. It
exists for the few places that paint manually with `QPainter` and therefore
cannot be styled through QSS; everything else is styled by
`assets/styles/main.qss`.
"""

from .theme import Theme
from .theme_manager import ThemeManager, active_theme
from .themes import DARK, DEFAULT_THEME_KEY, LIGHT, STEEL, THEMES, get_theme

__all__ = [
    'DARK',
    'DEFAULT_THEME_KEY',
    'LIGHT',
    'STEEL',
    'THEMES',
    'Theme',
    'ThemeManager',
    'active_theme',
    'get_theme',
]
