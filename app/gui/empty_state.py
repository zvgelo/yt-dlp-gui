"""Start screen shown when the queue is empty, as in the "main window" mockup.

The icon is drawn as vectors rather than a Unicode glyph or a bitmap: not
every system has a download arrow in its default font, the drawing scales on
HiDPI and, most importantly, it takes the colour of the active theme, so no
per-theme icon file is needed.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..theme import active_theme
from ..theme.color import to_color

_ICON_SIZE = 92
_TEXT_WIDTH = 520


class EmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('EmptyState')

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)

        # Fixed-width column; otherwise wrapped labels do not get the right
        # height inside a centred QVBoxLayout
        content = QWidget()
        content.setFixedWidth(_TEXT_WIDTH)
        content.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(14)

        self._icon = QLabel()
        self._icon.setObjectName('EmptyGlyph')
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self._icon)

        self._headline = QLabel()
        self._headline.setObjectName('EmptyTitle')
        self._headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._headline.setWordWrap(True)
        column.addWidget(self._headline)

        self._hint = QLabel()
        self._hint.setObjectName('EmptyHint')
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        column.addWidget(self._hint)

        outer.addWidget(content, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(2)

        self.retranslate_ui()
        self.restyle()

    def retranslate_ui(self) -> None:
        self._headline.setText(
            self.tr('Copy a link to a video, playlist or channel and click <b>Paste link</b>'))
        self._hint.setText(
            self.tr('Every site yt-dlp knows is supported. Save video as MP4, MKV or WebM, '
                    'audio as MP3, M4A, Opus or FLAC — together with cover art, tags '
                    'and subtitles.'))

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def restyle(self) -> None:
        """Repaint the icon in the colours of the current theme."""
        self._icon.setPixmap(_download_icon(_ICON_SIZE, self.devicePixelRatioF()))


def _download_icon(size: int, ratio: float) -> QPixmap:
    """Arrow above a tray: a simple counterpart of the mockup illustration."""
    ratio = max(1.0, ratio)
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    color = to_color(active_theme().border_strong)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(color, 4.0, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

    unit = size / 100.0
    # arrow shaft
    painter.drawLine(QPointF(50 * unit, 18 * unit), QPointF(50 * unit, 60 * unit))
    # grot
    head = QPainterPath()
    head.moveTo(34 * unit, 46 * unit)
    head.lineTo(50 * unit, 62 * unit)
    head.lineTo(66 * unit, 46 * unit)
    painter.drawPath(head)
    # tacka
    tray = QPainterPath()
    tray.moveTo(24 * unit, 68 * unit)
    tray.lineTo(24 * unit, 82 * unit)
    tray.lineTo(76 * unit, 82 * unit)
    tray.lineTo(76 * unit, 68 * unit)
    painter.drawPath(tray)

    painter.setPen(QPen(color, 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(4 * unit, 4 * unit, 92 * unit, 92 * unit), 8 * unit, 8 * unit)
    painter.end()
    return pixmap
