"""Per-download options: subtitles, metadata, cover art and target folder.

The subtitle language list comes from the `subtitles` / `automatic_captions`
of the given media, never from a hard-coded list.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import MediaInfo
from ..settings import AppSettings

ALL_LANGUAGES = ('all',)


class OptionsWidget(QWidget):
    """Lower part of the download dialog, above the buttons."""

    def __init__(self, info: MediaInfo, settings: AppSettings, *, ffmpeg_available: bool, parent=None):
        super().__init__(parent)
        self._info = info
        self._settings = settings
        self._ffmpeg = ffmpeg_available
        self._audio_mode = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(self._build_subtitles_row())
        layout.addLayout(self._build_extras_row())
        layout.addLayout(self._build_path_row())
        self.retranslate_ui()

    # ------------------------------------------------------- construction

    def _build_subtitles_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.subs_check = QCheckBox()
        self.subs_check.setChecked(self._settings.write_subtitles and bool(self._info.subtitles))
        self.subs_check.setEnabled(bool(self._info.subtitles))
        self.subs_check.toggled.connect(self._sync_subtitle_controls)
        row.addWidget(self.subs_check)

        row.addSpacing(12)
        self.language_label = QLabel()
        self.language_label.setObjectName('MutedLabel')
        row.addWidget(self.language_label)

        self.language_combo = QComboBox()
        self.language_combo.setMinimumWidth(220)
        row.addWidget(self.language_combo)

        self.embed_subs_check = QCheckBox()
        self.embed_subs_check.setChecked(self._settings.embed_subtitles and self._ffmpeg)
        self.embed_subs_check.setEnabled(self._ffmpeg)
        row.addWidget(self.embed_subs_check)

        row.addStretch(1)
        return row

    def _build_extras_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)

        self.metadata_check = QCheckBox()
        self.metadata_check.setChecked(self._settings.embed_metadata and self._ffmpeg)
        self.metadata_check.setEnabled(self._ffmpeg)
        row.addWidget(self.metadata_check)

        self.thumbnail_check = QCheckBox()
        self.thumbnail_check.setChecked(self._settings.embed_thumbnail and self._ffmpeg)
        self.thumbnail_check.setEnabled(self._ffmpeg)
        row.addWidget(self.thumbnail_check)

        self.chapters_check = QCheckBox()
        self.chapters_check.setChecked(self._settings.embed_chapters and self._ffmpeg)
        self.chapters_check.setEnabled(self._ffmpeg)
        row.addWidget(self.chapters_check)

        row.addStretch(1)
        return row

    def _build_path_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit(self._settings.output_dir)
        row.addWidget(self.path_edit, 1)

        self.browse_button = QPushButton('…')
        self.browse_button.setFixedWidth(44)
        self.browse_button.clicked.connect(self._browse)
        row.addWidget(self.browse_button)
        return row

    # --------------------------------------------------------------- text

    def retranslate_ui(self) -> None:
        self.subs_check.setText(self.tr('Download subtitles'))
        self.language_label.setText(self.tr('Language:'))
        self.embed_subs_check.setText(self.tr('Embed in file'))
        self.metadata_check.setText(self.tr('Save metadata'))
        self.thumbnail_check.setText(self.tr('Embed cover art'))
        self.chapters_check.setText(self.tr('Save chapters'))
        self.path_edit.setPlaceholderText(self.tr('Destination folder'))
        self.path_edit.setAccessibleName(self.tr('Destination folder'))
        self.language_combo.setAccessibleName(self.tr('Subtitle language'))
        self.browse_button.setToolTip(self.tr('Choose destination folder'))
        self.browse_button.setAccessibleName(self.tr('Choose destination folder'))

        if not self._info.subtitles:
            self.subs_check.setToolTip(self.tr('This item offers no subtitles'))
        if not self._ffmpeg:
            self.embed_subs_check.setToolTip(self.tr('Embedding subtitles requires FFmpeg'))
            for widget in (self.metadata_check, self.thumbnail_check, self.chapters_check):
                widget.setToolTip(self.tr('Requires FFmpeg'))

        self._fill_languages()
        self._sync_subtitle_controls()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    # -------------------------------------------------------------- logic

    def _fill_languages(self) -> None:
        current = self.language_combo.currentData()
        self.language_combo.blockSignals(True)
        self.language_combo.clear()

        preferred = self._settings.subtitle_language_list
        available = {track.language for track in self._info.subtitles}
        matching = tuple(lang for lang in preferred if lang in available)
        if matching:
            self.language_combo.addItem(
                self.tr('Preferred ({0})').format(', '.join(matching)), matching)
        for track in self._info.subtitles:
            suffix = self.tr(' (auto)') if track.automatic else ''
            self.language_combo.addItem(
                f'{track.display_name}{suffix} [{track.language}]', (track.language,))
        self.language_combo.addItem(self.tr('All available'), ALL_LANGUAGES)

        index = self.language_combo.findData(current)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        self.language_combo.blockSignals(False)

    def set_audio_mode(self, audio: bool) -> None:
        """Subtitles do not apply in audio-only mode."""
        self._audio_mode = audio
        for widget in (self.subs_check, self.language_combo,
                       self.embed_subs_check, self.language_label):
            widget.setVisible(not audio)
        self._sync_subtitle_controls()

    def _sync_subtitle_controls(self) -> None:
        if self._audio_mode:
            return
        enabled = self.subs_check.isChecked() and self.subs_check.isEnabled()
        self.language_combo.setEnabled(enabled and self.language_combo.count() > 1)
        self.embed_subs_check.setEnabled(enabled and self._ffmpeg)

    def _browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, self.tr('Destination folder'), self.path_edit.text())
        if directory:
            self.path_edit.setText(directory)

    # ------------------------------------------------------------ reading

    @property
    def output_dir(self) -> str:
        return self.path_edit.text().strip() or self._settings.output_dir

    @property
    def write_subtitles(self) -> bool:
        if self._audio_mode:
            return False
        return self.subs_check.isChecked() and self.subs_check.isEnabled()

    @property
    def subtitle_languages(self) -> tuple[str, ...]:
        data = self.language_combo.currentData()
        return tuple(data) if data else self._settings.subtitle_language_list

    @property
    def auto_subtitles(self) -> bool:
        """Fetch automatic captions when the chosen language has only that variant."""
        if not self.write_subtitles:
            return False
        languages = set(self.subtitle_languages)
        if 'all' in languages:
            return self._settings.auto_subtitles
        return any(track.automatic and track.language in languages for track in self._info.subtitles)

    @property
    def embed_subtitles(self) -> bool:
        return self.embed_subs_check.isChecked() and self.embed_subs_check.isEnabled()

    @property
    def embed_metadata(self) -> bool:
        return self.metadata_check.isChecked() and self.metadata_check.isEnabled()

    @property
    def embed_thumbnail(self) -> bool:
        return self.thumbnail_check.isChecked() and self.thumbnail_check.isEnabled()

    @property
    def embed_chapters(self) -> bool:
        return self.chapters_check.isChecked() and self.chapters_check.isEnabled()
