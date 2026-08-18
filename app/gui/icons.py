"""Icons and the brand mark, rendered from SVG in the active theme colours.

One set of SVG files serves every theme: the `{{FG}}` and `{{ACCENT}}`
tokens are substituted before rendering, so there are no separate
`logo_light.png` / `logo_dark.png` bitmaps.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..resources import icons_dir
from ..theme import active_theme

ICONS_DIR = icons_dir()

#: Application icon sizes (title bar, taskbar, window switcher)
APP_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

_pixmap_cache: dict[tuple[str, int, float, str, str], QPixmap] = {}


def _render(name: str, size: int, ratio: float, foreground: str, accent: str) -> QPixmap:
    key = (name, size, round(ratio, 2), foreground, accent)
    cached = _pixmap_cache.get(key)
    if cached is not None:
        return cached

    path = ICONS_DIR / f'{name}.svg'
    try:
        source = path.read_text(encoding='utf-8')
    except OSError:
        pixmap = QPixmap()
        _pixmap_cache[key] = pixmap
        return pixmap

    source = source.replace('{{FG}}', foreground).replace('{{ACCENT}}', accent)
    renderer = QSvgRenderer(QByteArray(source.encode('utf-8')))

    ratio = max(1.0, ratio)
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()

    _pixmap_cache[key] = pixmap
    return pixmap


def clear_cache() -> None:
    """Called after a theme change; icons must pick up the new colours."""
    _pixmap_cache.clear()


def pixmap(name: str, size: int = 24, ratio: float = 1.0, color: str | None = None) -> QPixmap:
    theme = active_theme()
    return _render(name, size, ratio, color or theme.text_secondary, theme.accent)


def icon(name: str, size: int = 24, color: str | None = None) -> QIcon:
    """Icon including a variant for the disabled state."""
    theme = active_theme()
    result = QIcon()
    result.addPixmap(_render(name, size, 2.0, color or theme.text_secondary, theme.accent),
                     QIcon.Mode.Normal)
    result.addPixmap(_render(name, size, 2.0, theme.text_primary, theme.accent),
                     QIcon.Mode.Active)
    result.addPixmap(_render(name, size, 2.0, theme.text_disabled, theme.text_disabled),
                     QIcon.Mode.Disabled)
    return result


def bar_icon(name: str) -> QIcon:
    return icon(name, 20)


def app_logo(size: int = 64, ratio: float = 1.0) -> QPixmap:
    """Brand mark: arrow in the text colour, head in the accent colour."""
    theme = active_theme()
    return _render('app_logo', size, ratio, theme.text_primary, theme.accent)


def app_icon() -> QIcon:
    """The window and application icon, in several sizes."""
    theme = active_theme()
    result = QIcon()
    for size in APP_ICON_SIZES:
        result.addPixmap(_render('app_logo', size, 1.0, theme.text_primary, theme.accent))
    return result
