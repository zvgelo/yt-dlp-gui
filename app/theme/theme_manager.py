"""Theme management: QSS rendering, Qt palette, switching and persistence.

A single `assets/styles/main.qss` template with `{{TOKEN}}` placeholders
serves every theme, so there are never three copies of the stylesheet.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ..resources import styles_dir
from .color import to_color
from .theme import Theme
from .themes import DEFAULT_THEME_KEY, THEMES, get_theme

#: QSettings key holding the user choice
SETTINGS_KEY = 'appearance/theme'

_TEMPLATE_PATH = styles_dir() / 'main.qss'
_LEFTOVER_TOKEN_RE = re.compile(r'\{\{[A-Z_]+\}\}')

#: Theme currently applied to the application; read by code that paints manually.
_active: Theme = get_theme(DEFAULT_THEME_KEY)


def active_theme() -> Theme:
    """The theme in force right now.

    Lets widgets that paint with `QPainter` reach for colours without
    threading `ThemeManager` through several constructor layers.
    """
    return _active


class UnresolvedTokensError(RuntimeError):
    """The QSS template uses a token the theme does not define."""


class ThemeManager(QObject):
    """Available themes, current choice, rendering and stylesheet application."""

    themeChanged = Signal(object)  # Theme

    def __init__(self, settings: QSettings | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._settings = settings
        self._template = _read_template()
        self._theme = get_theme(self._stored_key())

    # ------------------------------------------------------------- access

    @property
    def themes(self) -> tuple[Theme, ...]:
        return THEMES

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def key(self) -> str:
        return self._theme.key

    # ------------------------------------------------------------ actions

    def set_theme(self, key: str, *, persist: bool = True) -> bool:
        """Switch theme at runtime. Returns False when nothing changed."""
        theme = get_theme(key)
        if theme.key == self._theme.key:
            return False

        self._theme = theme
        if persist:
            self._store_key(theme.key)
        self.apply()
        return True

    def persist(self) -> None:
        """Store the current theme (`set_theme` is a no-op for an unchanged key)."""
        self._store_key(self._theme.key)

    def apply(self, app: QApplication | None = None) -> None:
        """Apply the current theme to the application and notify listeners."""
        global _active
        _active = self._theme

        app = app or QApplication.instance()
        if app is not None:
            app.setPalette(build_palette(self._theme))
            app.setStyleSheet(self.stylesheet())
        self.themeChanged.emit(self._theme)

    def stylesheet(self, theme: Theme | None = None) -> str:
        return self.render(theme or self._theme, self._template)

    @staticmethod
    def render(theme: Theme, template: str | None = None) -> str:
        """Substitute the theme tokens into the QSS template."""
        result = template if template is not None else _read_template()
        for token, value in theme.tokens().items():
            result = result.replace(token, value)

        leftover = sorted(set(_LEFTOVER_TOKEN_RE.findall(result)))
        if leftover:
            raise UnresolvedTokensError(
                f'QSS template uses tokens unknown to the theme: {", ".join(leftover)}')
        return result

    # ------------------------------------------------------------ storage

    def _stored_key(self) -> str:
        if self._settings is None:
            return DEFAULT_THEME_KEY
        value = self._settings.value(SETTINGS_KEY, DEFAULT_THEME_KEY)
        return str(value) if value else DEFAULT_THEME_KEY

    def _store_key(self, key: str) -> None:
        if self._settings is not None:
            self._settings.setValue(SETTINGS_KEY, key)
            self._settings.sync()


def build_palette(theme: Theme) -> QPalette:
    """Qt palette that complements the QSS.

    QSS does not reach native dialogs drawn by the style (QFileDialog,
    QMessageBox, internal view elements), so the colours must also land in
    the palette; otherwise dark themes end up with bright islands.
    """
    palette = QPalette()

    background = to_color(theme.background)
    surface = to_color(theme.surface)
    text = to_color(theme.text_primary)
    disabled = to_color(theme.text_disabled)
    accent = to_color(theme.accent)

    palette.setColor(QPalette.ColorRole.Window, background)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, surface)
    palette.setColor(QPalette.ColorRole.AlternateBase, to_color(theme.surface_secondary))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, disabled)

    palette.setColor(QPalette.ColorRole.Button, to_color(theme.surface))
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, to_color(theme.error))

    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, to_color(theme.text_on_accent))
    palette.setColor(QPalette.ColorRole.Link, to_color(theme.link))
    palette.setColor(QPalette.ColorRole.LinkVisited, to_color(theme.link))

    palette.setColor(QPalette.ColorRole.ToolTipBase, to_color(theme.tooltip_background))
    palette.setColor(QPalette.ColorRole.ToolTipText, to_color(theme.tooltip_text))

    palette.setColor(QPalette.ColorRole.Light, to_color(theme.surface_hover))
    palette.setColor(QPalette.ColorRole.Midlight, to_color(theme.surface_secondary))
    palette.setColor(QPalette.ColorRole.Mid, to_color(theme.border))
    palette.setColor(QPalette.ColorRole.Dark, to_color(theme.border_strong))
    palette.setColor(QPalette.ColorRole.Shadow, QColor(0, 0, 0, 60))

    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText, QPalette.ColorRole.HighlightedText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base,
                     to_color(theme.surface_secondary))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button,
                     to_color(theme.surface_secondary))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight,
                     to_color(theme.surface_active))
    return palette


def _read_template() -> str:
    try:
        return _TEMPLATE_PATH.read_text(encoding='utf-8')
    except OSError:
        return ''
