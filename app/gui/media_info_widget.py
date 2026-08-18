"""Download dialog header: thumbnail, title, duration, author and link."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..core.models import MediaInfo
from ..theme import active_theme
from ..utils import formatting as fmt
from ..workers.thumbnail_worker import ThumbnailCache
from . import style


class MediaInfoWidget(QWidget):
    """Counterpart of the top section in the "download options" mockup."""

    def __init__(self, info: MediaInfo, thumbnails: ThumbnailCache, parent=None):
        super().__init__(parent)
        self.setObjectName('DialogHeader')
        self._info = info
        self._thumbnails = thumbnails

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        self._preview = QLabel()
        self._preview.setObjectName('PreviewFrame')
        self._preview.setFixedSize(style.PREVIEW_WIDTH, style.PREVIEW_HEIGHT)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setText('▶')
        self._preview.setScaledContents(False)
        layout.addWidget(self._preview, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(4)

        title = QLabel(info.title)
        title.setObjectName('TitleLabel')
        title.setWordWrap(True)
        column.addWidget(title)

        meta = QLabel(fmt.join(
            fmt.duration(info.duration) if info.duration else '',
            info.author,
            info.extractor,
            self.tr('LIVE') if info.live else '',
        ))
        meta.setObjectName('MutedLabel')
        column.addWidget(meta)

        self._url = info.webpage_url or info.url
        self._link = QLabel()
        self._link.setOpenExternalLinks(True)
        self._link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._link.setToolTip(self._url)
        # A long address must not push the dialog wider than the screen
        self._link.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._update_link()
        column.addWidget(self._link)
        column.addStretch(1)

        layout.addLayout(column, 1)

        thumbnails.loaded.connect(self._on_thumbnail_loaded)
        self._apply_thumbnail()

    def _update_link(self) -> None:
        """Shorten the address to whatever width the label actually has.

        Eliding by character count alone is not enough: the same number of
        characters is a different number of pixels in every theme and font, and
        the dialog can be resized. The full address stays in the tooltip and
        remains the link target.
        """
        available = max(self._link.width(), 120) - 4
        shown = self._link.fontMetrics().elidedText(
            self._url, Qt.TextElideMode.ElideRight, available)
        color = active_theme().link
        self._link.setText(
            f'<a href="{self._url}" style="color:{color}; text-decoration:none;">'
            f'{html.escape(shown)}</a>')

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_link()

    @Slot(str)
    def _on_thumbnail_loaded(self, url: str) -> None:
        if url == self._info.thumbnail_url:
            self._apply_thumbnail()

    def _apply_thumbnail(self) -> None:
        pixmap: QPixmap | None = self._thumbnails.get(
            self._info.thumbnail_url, style.PREVIEW_WIDTH, style.PREVIEW_HEIGHT,
            self.devicePixelRatioF())
        if pixmap is not None and not pixmap.isNull():
            self._preview.setPixmap(pixmap)
