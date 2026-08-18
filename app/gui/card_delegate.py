"""Painting a queue item as a card, following the "main window 2" mockup.

A card holds a thumbnail with a duration badge, a title and a metadata row
(`22:08 - 113.4 MB - MP4 - 1080p - Author`), plus a progress bar described as
`24.8 MB / 36.2 MB - 8.4 MB/s - ETA 00:02` while the download runs.

Colours come from the active theme (`app.theme.active_theme()`) because QSS
does not reach `QPainter` drawing. Every font derives from `option.font` and
never from `painter.font()`: the painter is shared between items and would
carry the changes over.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..core.models import DownloadResultStatus, DownloadTask, MediaKind, PlaylistJob
from ..state import TaskState
from ..theme import Theme, active_theme
from ..theme.color import to_color
from ..utils import formatting as fmt
from ..workers.thumbnail_worker import ThumbnailCache
from . import labels, style
from .queue_model import PLAYLIST_ROLE, TASK_ROLE


def _ratio(option: QStyleOptionViewItem) -> float:
    """The device pixel ratio of the screen the view is on.

    Thumbnails are bitmaps, so on a HiDPI display they have to be produced at
    the real resolution; everything else here is drawn as vectors.
    """
    widget = getattr(option, 'widget', None)
    return widget.devicePixelRatioF() if widget is not None else 1.0


def state_color(theme: Theme, state: TaskState) -> str:
    """Task status colour, taken solely from the theme palette."""
    return {
        TaskState.QUEUED: theme.text_secondary,
        TaskState.DOWNLOADING: theme.accent,
        TaskState.POSTPROCESSING: theme.warning,
        TaskState.FINISHED: theme.success,
        TaskState.COMPLETED_WITH_ERRORS: theme.warning,
        TaskState.ERROR: theme.error,
        TaskState.CANCELLED: theme.text_secondary,
        TaskState.INTERRUPTED: theme.warning,
        TaskState.NEEDS_REVIEW: theme.warning,
        TaskState.RETRYING: theme.warning,
        TaskState.SKIPPED_DUPLICATE: theme.text_secondary,
        TaskState.SKIPPED_BY_USER: theme.text_secondary,
    }.get(state, theme.text_secondary)


class CardDelegate(QStyledItemDelegate):
    def __init__(self, thumbnails: ThumbnailCache, parent=None):
        super().__init__(parent)
        self._thumbnails = thumbnails
        #: Screen ratio of the view being painted, refreshed on every paint
        self._ratio = 1.0

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), style.CARD_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        self._ratio = _ratio(option)
        playlist: PlaylistJob | None = index.data(PLAYLIST_ROLE)
        if playlist is not None:
            self._paint_playlist(painter, option, playlist)
            return

        task: DownloadTask | None = index.data(TASK_ROLE)
        if task is None:
            return

        theme = active_theme()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        base = QFont(option.font)

        self._paint_background(
            painter, rect, theme,
            selected=bool(option.state & QStyle.StateFlag.State_Selected),
            hovered=bool(option.state & QStyle.StateFlag.State_MouseOver),
        )

        thumb = QRect(
            rect.left() + style.CARD_PADDING,
            rect.top() + (rect.height() - style.THUMB_HEIGHT) // 2,
            style.THUMB_WIDTH, style.THUMB_HEIGHT,
        )
        self._paint_thumbnail(painter, thumb, task, base, theme)

        left = thumb.right() + style.CARD_GAP
        right = rect.right() - style.STATUS_COLUMN
        width = max(80, right - left)

        self._paint_title(painter, QRect(left, rect.top() + 14, width, 19), task, base, theme)
        body = QRect(left, rect.top() + 37, width, 22)
        if task.state.shows_progress:
            self._paint_progress(painter, body, task, base, theme)
        else:
            self._paint_summary(painter, body, task, base, theme)

        self._paint_state(
            painter, QRect(right + 6, rect.top(), style.STATUS_COLUMN - 18, rect.height()),
            task, base, theme)

        painter.setPen(QPen(to_color(theme.separator), 1))
        painter.drawLine(rect.left() + style.CARD_PADDING, rect.bottom(),
                         rect.right() - style.CARD_PADDING, rect.bottom())
        painter.restore()

    def _paint_playlist(self, painter: QPainter, option: QStyleOptionViewItem,
                        job: PlaylistJob) -> None:
        """Playlist row: title, counters and the overall status."""
        theme = active_theme()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        base = QFont(option.font)

        self._paint_background(
            painter, rect, theme,
            selected=bool(option.state & QStyle.StateFlag.State_Selected),
            hovered=bool(option.state & QStyle.StateFlag.State_MouseOver),
        )

        thumb = QRect(rect.left() + style.CARD_PADDING,
                      rect.top() + (rect.height() - style.THUMB_HEIGHT) // 2,
                      style.THUMB_WIDTH, style.THUMB_HEIGHT)
        self._paint_playlist_thumbnail(painter, thumb, job, base, theme)

        left = thumb.right() + style.CARD_GAP
        right = rect.right() - style.STATUS_COLUMN
        width = max(80, right - left)

        title_font = QFont(base)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(to_color(theme.text_primary))
        _draw_elided(painter, QRect(left, rect.top() + 14, width, 19), job.title, title_font)

        body = QRect(left, rect.top() + 37, width, 22)
        if job.is_active:
            self._paint_playlist_progress(painter, body, job, base, theme)
        else:
            font = _small(painter, base)
            painter.setPen(to_color(theme.text_secondary))
            _draw_elided(painter, body, labels.playlist_summary(job), font)

        status_font = QFont(base)
        status_font.setBold(job.is_active)
        painter.setFont(status_font)
        painter.setPen(QColor(_playlist_status_color(theme, job)))
        painter.drawText(QRect(right + 6, rect.top(), style.STATUS_COLUMN - 18, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         labels.playlist_status_badge(job))

        painter.setPen(QPen(to_color(theme.separator), 1))
        painter.drawLine(rect.left() + style.CARD_PADDING, rect.bottom(),
                         rect.right() - style.CARD_PADDING, rect.bottom())
        painter.restore()

    def _paint_playlist_thumbnail(self, painter: QPainter, rect: QRect, job: PlaylistJob,
                                  base: QFont, theme: Theme) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 4, 4)
        painter.save()
        painter.setClipPath(path)
        pixmap = self._thumbnails.get(job.thumbnail_url, rect.width(), rect.height(),
                                      self._ratio)
        if pixmap is not None and not pixmap.isNull():
            painter.drawPixmap(rect, pixmap)
        else:
            painter.fillRect(rect, to_color(theme.placeholder_background))
            painter.setPen(to_color(theme.text_secondary))
            painter.setFont(_resized(base, +4))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, '☰')
        painter.restore()
        painter.setPen(QPen(to_color(theme.border), 1))
        painter.drawPath(path)

    def _paint_playlist_progress(self, painter: QPainter, rect: QRect, job: PlaylistJob,
                                 base: QFont, theme: Theme) -> None:
        bar = QRect(rect.left(), rect.top() + 1, rect.width(), 5)
        track = QPainterPath()
        track.addRoundedRect(QRectF(bar), 2.5, 2.5)
        painter.fillPath(track, to_color(theme.progress_track))

        fraction = max(0.0, min(1.0, job.percent / 100.0))
        if fraction > 0:
            filled = QRect(bar.left(), bar.top(), int(bar.width() * fraction), bar.height())
            path = QPainterPath()
            path.addRoundedRect(QRectF(filled), 2.5, 2.5)
            painter.fillPath(path, to_color(theme.accent))

        font = _small(painter, base)
        painter.setPen(to_color(theme.text_secondary))
        _draw_elided(painter, QRect(rect.left(), bar.bottom() + 2, rect.width(), 15),
                     labels.playlist_summary(job), font)

    # ------------------------------------------------------------- fragments

    def _paint_background(self, painter: QPainter, rect: QRect, theme: Theme,
                          *, selected: bool, hovered: bool) -> None:
        if not (selected or hovered):
            return
        inner = QRectF(rect.adjusted(6, 2, -6, -2))
        path = QPainterPath()
        path.addRoundedRect(inner, 5, 5)
        painter.fillPath(path, to_color(theme.accent_soft if selected else theme.surface_hover))
        if selected:
            painter.setPen(QPen(to_color(theme.accent), 1))
            painter.drawPath(path)

    def _paint_thumbnail(self, painter: QPainter, rect: QRect, task: DownloadTask,
                         base: QFont, theme: Theme) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 4, 4)

        painter.save()
        painter.setClipPath(path)
        pixmap: QPixmap | None = self._thumbnails.get(
            task.thumbnail_url, rect.width(), rect.height(), self._ratio)
        if pixmap is not None and not pixmap.isNull():
            painter.drawPixmap(rect, pixmap)
        else:
            painter.fillRect(rect, to_color(theme.placeholder_background))
            painter.setPen(to_color(theme.text_secondary))
            painter.setFont(_resized(base, +4))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             '♪' if task.kind is MediaKind.AUDIO else '▶')
        painter.restore()

        if task.duration:
            self._paint_duration_badge(painter, rect, fmt.duration(task.duration), base, theme)

        painter.setPen(QPen(to_color(theme.border), 1))
        painter.drawPath(path)

    def _paint_duration_badge(self, painter: QPainter, thumb: QRect, text: str,
                              base: QFont, theme: Theme) -> None:
        font = _resized(base, -2)
        painter.setFont(font)

        width = QFontMetrics(font).horizontalAdvance(text) + 8
        badge = QRect(thumb.right() - width - 3, thumb.bottom() - 16, width, 14)
        path = QPainterPath()
        path.addRoundedRect(QRectF(badge), 2, 2)
        painter.fillPath(path, to_color(theme.overlay_scrim))
        painter.setPen(to_color(theme.overlay_text))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_title(self, painter: QPainter, rect: QRect, task: DownloadTask,
                     base: QFont, theme: Theme) -> None:
        font = QFont(base)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(to_color(theme.text_primary))
        _draw_elided(painter, rect, task.display_title, font)

    def _paint_summary(self, painter: QPainter, rect: QRect, task: DownloadTask,
                       base: QFont, theme: Theme) -> None:
        font = _small(painter, base)
        if task.state is TaskState.ERROR:
            painter.setPen(to_color(theme.error))
            text = labels.failure_summary(task)
        elif task.state is TaskState.RETRYING:
            painter.setPen(to_color(theme.warning))
            text = labels.retry_summary(task)
        elif task.state is TaskState.COMPLETED_WITH_ERRORS and task.result is not None:
            painter.setPen(to_color(theme.warning))
            text = labels.describe_result(task.result)
        elif task.state.needs_decision:
            painter.setPen(to_color(theme.warning))
            text = labels.duplicate_summary(task)
        elif task.state.is_skipped:
            painter.setPen(to_color(theme.text_secondary))
            text = labels.skipped_summary(task)
        else:
            painter.setPen(to_color(theme.text_secondary))
            text = task.summary or task.url
        _draw_elided(painter, rect, text, font)

    def _paint_progress(self, painter: QPainter, rect: QRect, task: DownloadTask,
                        base: QFont, theme: Theme) -> None:
        bar = QRect(rect.left(), rect.top() + 1, rect.width(), 5)
        track = QPainterPath()
        track.addRoundedRect(QRectF(bar), 2.5, 2.5)
        painter.fillPath(track, to_color(theme.progress_track))

        processing = task.state is TaskState.POSTPROCESSING
        fraction = 1.0 if processing else max(0.0, min(1.0, task.percent / 100.0))
        if fraction > 0:
            filled = QRect(bar.left(), bar.top(), int(bar.width() * fraction), bar.height())
            path = QPainterPath()
            path.addRoundedRect(QRectF(filled), 2.5, 2.5)
            painter.fillPath(path, to_color(theme.warning if processing else theme.accent))

        font = _small(painter, base)
        painter.setPen(to_color(theme.text_secondary))
        if processing:
            text = (labels.postprocess_stage_label(task.stage) if task.stage
                    else labels.processing_fallback())
        else:
            text = labels.describe_progress(task.progress) or labels.connecting_label()
        _draw_elided(painter, QRect(rect.left(), bar.bottom() + 2, rect.width(), 15), text, font)

    def _paint_state(self, painter: QPainter, rect: QRect, task: DownloadTask,
                     base: QFont, theme: Theme) -> None:
        font = QFont(base)
        font.setBold(task.state.is_active)
        painter.setFont(font)
        painter.setPen(QColor(state_color(theme, task.state)))

        text = labels.task_state_badge(task.state, task.percent)
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)


def _resized(base: QFont, delta: int) -> QFont:
    """A copy of the font larger or smaller by `delta`.

    QSS sets `font-size` in pixels, so `pointSizeF()` can be -1; both modes
    have to be handled or the text collapses to the minimum size.
    """
    font = QFont(base)
    if base.pixelSize() > 0:
        font.setPixelSize(max(8, base.pixelSize() + delta))
    else:
        font.setPointSizeF(max(7.0, base.pointSizeF() + delta))
    return font


def _small(painter: QPainter, base: QFont) -> QFont:
    font = _resized(base, -2)
    font.setBold(False)
    painter.setFont(font)
    return font


def _draw_elided(painter: QPainter, rect: QRect, text: str, font: QFont) -> None:
    metrics = QFontMetrics(font)
    painter.drawText(
        rect,
        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
        metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width()),
    )


def _playlist_status_color(theme: Theme, job: PlaylistJob) -> str:
    if job.is_active:
        return theme.accent
    return {
        DownloadResultStatus.SUCCESS: theme.success,
        DownloadResultStatus.PARTIAL_SUCCESS: theme.warning,
        DownloadResultStatus.ERROR: theme.error,
        DownloadResultStatus.CANCELLED: theme.text_secondary,
    }.get(job.status, theme.text_secondary)
