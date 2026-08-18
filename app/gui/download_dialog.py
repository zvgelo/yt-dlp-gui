"""The "Download media" dialog, mirroring the `download options.jpg` mockup."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..core.models import DownloadRequest, DownloadTask, MediaInfo
from ..settings import AppSettings
from ..workers.thumbnail_worker import ThumbnailCache
from .focus import order_button_box
from .format_widget import FormatWidget
from .media_info_widget import MediaInfoWidget
from .options_widget import OptionsWidget


class DownloadDialog(QDialog):
    """Returns a ready `DownloadTask` carrying the user choices."""

    def __init__(self, info: MediaInfo, settings: AppSettings, thumbnails: ThumbnailCache,
                 *, ffmpeg_available: bool, parent=None):
        super().__init__(parent)
        self._info = info
        self._settings = settings

        self.setWindowTitle(self.tr('Download item'))
        self.setMinimumSize(700, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(MediaInfoWidget(info, thumbnails, self))

        if not ffmpeg_available:
            layout.addWidget(_ffmpeg_warning())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 14, 18, 8)
        body_layout.setSpacing(12)

        self.format_widget = FormatWidget(info, settings, ffmpeg_available=ffmpeg_available)
        self.format_widget.changed.connect(self._update_summary)
        body_layout.addWidget(self.format_widget, 1)

        self.options_widget = OptionsWidget(info, settings, ffmpeg_available=ffmpeg_available)
        self.options_widget.set_audio_mode(self.format_widget.is_audio)
        body_layout.addWidget(self.options_widget)
        layout.addWidget(body, 1)

        layout.addWidget(_separator())
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 10, 18, 14)
        footer_layout.setSpacing(8)

        self.summary_label = QLabel()
        self.summary_label.setObjectName('Hint')
        footer_layout.addWidget(self.summary_label)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton(self.tr('Cancel'), QDialogButtonBox.ButtonRole.RejectRole)
        self._download_button = buttons.addButton(self.tr('Download'),
                                                  QDialogButtonBox.ButtonRole.AcceptRole)
        self._download_button.setProperty('accent', True)
        self._download_button.setDefault(True)
        cancel.clicked.connect(self.reject)
        self._download_button.clicked.connect(self.accept)
        footer_layout.addWidget(buttons)
        layout.addWidget(footer)
        order_button_box(self, buttons)

        self._update_summary()

    # ------------------------------------------------------------ result

    def build_task(self) -> DownloadTask:
        fw, ow = self.format_widget, self.options_widget
        request = DownloadRequest(
            url=self._info.webpage_url or self._info.url,
            output_dir=ow.output_dir,
            kind=fw.kind,
            quality=fw.quality(),
            container=fw.container(),
            audio_format=fw.audio_format(),
            format_selector=fw.format_selector(),
            write_subtitles=ow.write_subtitles,
            auto_subtitles=ow.auto_subtitles,
            embed_subtitles=ow.embed_subtitles,
            subtitle_languages=ow.subtitle_languages,
            embed_metadata=ow.embed_metadata,
            embed_chapters=ow.embed_chapters,
            embed_thumbnail=ow.embed_thumbnail,
            write_thumbnail=self._settings.write_thumbnail,
            write_info_json=self._settings.write_info_json,
            write_description=self._settings.write_description,
            parse_artist_title=self._settings.parse_artist_title,
        )
        return DownloadTask(
            request=request,
            media_id=self._info.media_id,
            extractor=self._info.extractor,
            title=self._info.title,
            uploader=self._info.author,
            duration=self._info.duration,
            thumbnail_url=self._info.thumbnail_url,
            quality_label=fw.quality_label(),
            expected_size=fw.expected_size(),
        )

    def applied_settings(self) -> AppSettings:
        """The user choices, remembered as the new defaults."""
        fw = self.format_widget
        changes = {
            'kind': fw.kind.value,
            'output_dir': self.options_widget.output_dir,
        }
        if fw.is_audio:
            changes['audio_format'] = fw.audio_format()
        else:
            changes['video_container'] = fw.container()
        return self._settings.replace(**changes)

    # ------------------------------------------------------------ preview

    def _update_summary(self) -> None:
        self.options_widget.set_audio_mode(self.format_widget.is_audio)
        from ..core.format_service import build_selector
        from ..utils import formatting as fmt

        task = self.build_task()
        selector = build_selector(task.request)
        size = fmt.size(task.expected_size) if task.expected_size else self.tr('unknown')
        self.summary_label.setText(
            self.tr('yt-dlp selector: {0}   ·   estimated size: {1}').format(selector, size))


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName('Separator')
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


def _ffmpeg_warning() -> QLabel:
    from PySide6.QtCore import QCoreApplication

    label = QLabel(QCoreApplication.translate(
        'DownloadDialog',
        'FFmpeg was not found — merging video with audio, audio conversion and '
        'embedding cover art or subtitles are unavailable.'))
    label.setObjectName('StatusWarn')
    label.setWordWrap(True)
    label.setContentsMargins(18, 10, 18, 0)
    return label
