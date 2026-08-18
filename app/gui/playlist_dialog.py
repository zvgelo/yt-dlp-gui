"""Playlist dialog: pick the items to download and the shared format settings.

Playlist entries come from `extract_flat` and carry no format list, so the
quality is chosen from the generic ladder and yt-dlp resolves the concrete
format while downloading each item.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import format_service as fs
from ..core.models import (
    QUALITY_BEST,
    DownloadRequest,
    DownloadTask,
    MediaInfo,
    MediaKind,
    PlaylistEntry,
)
from ..settings import AppSettings
from ..utils import formatting as fmt
from . import labels
from .focus import order_button_box


class PlaylistDialog(QDialog):
    def __init__(self, info: MediaInfo, settings: AppSettings, *, ffmpeg_available: bool, parent=None):
        super().__init__(parent)
        self._info = info
        self._settings = settings
        self._ffmpeg = ffmpeg_available

        self.setWindowTitle(self.tr('Download playlist'))
        self.setMinimumSize(680, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        layout.addWidget(self._build_header())
        layout.addLayout(self._build_selection_row())
        layout.addWidget(self._build_list(), 1)
        layout.addLayout(self._build_format_row())
        layout.addLayout(self._build_path_row())
        layout.addWidget(self._build_buttons())
        order_button_box(self, self._button_box)

        self._on_kind_changed()
        self._update_counter()

    # ------------------------------------------------------- construction

    def _build_header(self) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)

        title = QLabel(self._info.playlist_title or self._info.title)
        title.setObjectName('TitleLabel')
        title.setWordWrap(True)
        column.addWidget(title)

        meta = QLabel(fmt.join(
            labels.entry_count_label(self._info),
            self._info.author,
            self._info.extractor,
        ))
        meta.setObjectName('MutedLabel')
        column.addWidget(meta)

        if not self._info.entries_complete:
            # Never pretend the list is complete; the user has to know
            warning = QLabel(self.tr('The full playlist could not be loaded. Below are the '
                                     'items that could be read; more may exist.'))
            warning.setObjectName('StatusWarn')
            warning.setWordWrap(True)
            column.addWidget(warning)
        return box

    def _build_selection_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        select_all = QPushButton(self.tr('Select all'))
        select_all.clicked.connect(lambda: self._set_all(True))
        row.addWidget(select_all)

        deselect_all = QPushButton(self.tr('Deselect all'))
        deselect_all.clicked.connect(lambda: self._set_all(False))
        row.addWidget(deselect_all)

        row.addStretch(1)
        self.counter_label = QLabel()
        self.counter_label.setObjectName('MutedLabel')
        row.addWidget(self.counter_label)
        return row

    def _build_list(self) -> QListWidget:
        self.list_widget = QListWidget()
        self.list_widget.setAccessibleName(self.tr('Playlist items'))
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemChanged.connect(lambda *_: self._update_counter())

        for entry in self._info.entries:
            item = QListWidgetItem(_entry_label(entry))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list_widget.addItem(item)
        return self.list_widget

    def _build_format_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.kind_combo = QComboBox()
        for kind in MediaKind:
            self.kind_combo.addItem(labels.media_kind_label(kind), kind.value)
        _select(self.kind_combo, self._settings.kind)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self.kind_combo.setEnabled(self._ffmpeg)
        self.kind_combo.setAccessibleName(self.tr('What to download'))
        row.addWidget(self.kind_combo)

        quality_label = QLabel(self.tr('Quality:'))
        quality_label.setObjectName('MutedLabel')
        row.addWidget(quality_label)

        self.quality_combo = QComboBox()
        self.quality_combo.setMinimumWidth(170)
        self.quality_combo.setAccessibleName(self.tr('Quality'))
        quality_label.setBuddy(self.quality_combo)
        row.addWidget(self.quality_combo)

        format_label = QLabel(self.tr('Format:'))
        format_label.setObjectName('MutedLabel')
        row.addWidget(format_label)

        self.container_combo = QComboBox()
        self.container_combo.setMinimumWidth(170)
        self.container_combo.setAccessibleName(self.tr('Format'))
        format_label.setBuddy(self.container_combo)
        row.addWidget(self.container_combo)

        row.addStretch(1)
        return row

    def _build_path_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.subdir_check = QCheckBox(self.tr('Separate folder'))
        self.subdir_check.setChecked(self._settings.create_playlist_folder)
        row.addWidget(self.subdir_check)

        self.number_check = QCheckBox(self.tr('Number files'))
        self.number_check.setChecked(self._settings.number_playlist_files)
        self.number_check.setToolTip(self.tr('Add the playlist position before the file name'))
        row.addWidget(self.number_check)
        row.addSpacing(8)

        self.path_edit = QLineEdit(self._settings.output_dir)
        self.path_edit.setAccessibleName(self.tr('Destination folder'))
        row.addWidget(self.path_edit, 1)
        browse = QPushButton('…')
        browse.setFixedWidth(44)
        browse.setAccessibleName(self.tr('Choose destination folder'))
        browse.setToolTip(self.tr('Choose destination folder'))
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        return row

    def _build_buttons(self) -> QDialogButtonBox:
        box = QDialogButtonBox()
        cancel = box.addButton(self.tr('Cancel'), QDialogButtonBox.ButtonRole.RejectRole)
        self._accept_button = box.addButton(self.tr('Add to queue'),
                                            QDialogButtonBox.ButtonRole.AcceptRole)
        self._accept_button.setProperty('accent', True)
        self._accept_button.setDefault(True)
        cancel.clicked.connect(self.reject)
        self._accept_button.clicked.connect(self.accept)
        self._button_box = box
        return box

    # -------------------------------------------------------------- logic

    def _on_kind_changed(self) -> None:
        audio = self._kind() is MediaKind.AUDIO

        self.quality_combo.clear()
        if audio:
            self.quality_combo.addItem(labels.quality_label(QUALITY_BEST), QUALITY_BEST)
            for rate in fs.AUDIO_QUALITY_STEPS:
                self.quality_combo.addItem(fmt.bitrate(rate), rate)
        else:
            for value in fs.QUALITY_LADDER:
                self.quality_combo.addItem(labels.quality_label(value), value)
            _select(self.quality_combo, self._settings.quality)

        self.container_combo.clear()
        if audio:
            for value in fs.AUDIO_FORMATS:
                self.container_combo.addItem(labels.audio_format_label(value), value)
            preferred = self._settings.audio_format
        else:
            for value in fs.VIDEO_CONTAINERS:
                self.container_combo.addItem(labels.container_label(value), value)
            preferred = self._settings.video_container
        _select(self.container_combo, preferred)
        self.container_combo.setEnabled(self._ffmpeg or audio is False)

    def _kind(self) -> MediaKind:
        try:
            return MediaKind(self.kind_combo.currentData())
        except ValueError:
            return MediaKind.VIDEO

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.list_widget.blockSignals(True)
        for row in range(self.list_widget.count()):
            self.list_widget.item(row).setCheckState(state)
        self.list_widget.blockSignals(False)
        self._update_counter()

    def _update_counter(self) -> None:
        selected = len(self._selected_entries())
        total = self.list_widget.count()
        self.counter_label.setText(self.tr('Selected {0} of {1}').format(selected, total))
        self._accept_button.setEnabled(selected > 0)

    def _selected_entries(self) -> list[PlaylistEntry]:
        entries = []
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.checkState() is Qt.CheckState.Checked:
                entries.append(item.data(Qt.ItemDataRole.UserRole))
        return entries

    def _browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, self.tr('Destination folder'), self.path_edit.text())
        if directory:
            self.path_edit.setText(directory)

    # ------------------------------------------------------------ result

    def build_tasks(self) -> list[DownloadTask]:
        kind = self._kind()
        audio = kind is MediaKind.AUDIO
        container = '' if audio else (self.container_combo.currentData() or '')
        audio_format = (self.container_combo.currentData() or '') if audio else self._settings.audio_format
        quality = self.quality_combo.currentData()
        output_dir = self.path_edit.text().strip() or self._settings.output_dir
        # The playlist title always goes into the request; a separate option
        # decides whether a folder is created, and the playlist name never
        # becomes part of the filename
        playlist_title = self._info.playlist_title

        tasks = []
        for entry in self._selected_entries():
            request = DownloadRequest(
                # Canonical single-media URL: the discovered URL may still
                # carry playlist context and would re-enumerate the playlist
                url=entry.download_url,
                source_url=entry.url,
                output_dir=output_dir,
                kind=kind,
                quality=quality if quality is not None else QUALITY_BEST,
                container=container,
                audio_format=audio_format,
                write_subtitles=self._settings.write_subtitles,
                auto_subtitles=self._settings.auto_subtitles,
                embed_subtitles=self._settings.embed_subtitles and self._ffmpeg,
                subtitle_languages=self._settings.subtitle_language_list,
                embed_metadata=self._settings.embed_metadata and self._ffmpeg,
                embed_chapters=self._settings.embed_chapters and self._ffmpeg,
                embed_thumbnail=self._settings.embed_thumbnail and self._ffmpeg,
                write_thumbnail=self._settings.write_thumbnail,
                write_info_json=self._settings.write_info_json,
                write_description=self._settings.write_description,
                parse_artist_title=self._settings.parse_artist_title,
                playlist_title=playlist_title,
                playlist_index=entry.index,
                create_playlist_folder=self.subdir_check.isChecked(),
                number_playlist_files=self.number_check.isChecked(),
            )
            tasks.append(DownloadTask(
                request=request,
                title=entry.title,
                uploader=entry.uploader or self._info.author,
                duration=entry.duration,
                thumbnail_url=entry.thumbnail_url,
                quality_label='' if quality in (None, QUALITY_BEST)
                else str(self.quality_combo.currentText()),
            ))
        return tasks

    def applied_settings(self) -> AppSettings:
        kind = self._kind()
        changes = {
            'kind': kind.value,
            'output_dir': self.path_edit.text().strip() or self._settings.output_dir,
            'create_playlist_folder': self.subdir_check.isChecked(),
            'number_playlist_files': self.number_check.isChecked(),
        }
        if kind is MediaKind.AUDIO:
            changes['audio_format'] = self.container_combo.currentData() or ''
        else:
            changes['video_container'] = self.container_combo.currentData() or ''
            quality = self.quality_combo.currentData()
            if quality is not None:
                changes['quality'] = quality
        return self._settings.replace(**changes)


def _entry_label(entry: PlaylistEntry) -> str:
    duration = fmt.duration(entry.duration) if entry.duration else ''
    return fmt.join(f'{entry.index:>3}. {entry.title}', duration)


def _select(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)
