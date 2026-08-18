"""Format selection: video/audio mode, container and the quality list.

The simple view shows only the resolutions actually available for the given
media (no hard-coded `format_id`, no invented 4K). The advanced view lists
the concrete stream variants.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import format_service as fs
from ..core.models import QUALITY_BEST, MediaInfo, MediaKind
from ..settings import AppSettings
from ..utils import formatting as fmt
from . import labels


class FormatWidget(QWidget):
    """The "Download Video / Format / quality list" section from the mockup."""

    changed = Signal()

    def __init__(self, info: MediaInfo, settings: AppSettings, *, ffmpeg_available: bool, parent=None):
        super().__init__(parent)
        self._info = info
        self._settings = settings
        self._ffmpeg = ffmpeg_available
        self._group = QButtonGroup(self)
        self._group.buttonToggled.connect(lambda *_: self.changed.emit())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(self._build_controls())
        layout.addWidget(self._build_list(), 1)

        self.retranslate_ui()

    # ------------------------------------------------------- construction

    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.kind_combo = QComboBox()
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        row.addWidget(self.kind_combo)
        if not self._ffmpeg:
            self.kind_combo.setEnabled(False)

        row.addSpacing(16)
        self.format_label = QLabel()
        self.format_label.setObjectName('MutedLabel')
        row.addWidget(self.format_label)

        self.container_combo = QComboBox()
        self.container_combo.setMinimumWidth(190)
        self.container_combo.currentIndexChanged.connect(self._on_container_changed)
        row.addWidget(self.container_combo)

        row.addStretch(1)
        self.advanced_check = QCheckBox()
        self.advanced_check.toggled.connect(lambda *_: self._reload_rows())
        row.addWidget(self.advanced_check)
        return row

    def _build_list(self) -> QWidget:
        self._scroll = QScrollArea()
        self._scroll.setObjectName('FormatList')
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setMinimumHeight(220)

        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(10, 8, 12, 8)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(4)
        self._grid.setColumnStretch(2, 1)
        self._scroll.setWidget(self._host)
        return self._scroll

    # --------------------------------------------------------------- text

    def retranslate_ui(self) -> None:
        self.format_label.setText(self.tr('Format:'))
        self.kind_combo.setAccessibleName(self.tr('What to download'))
        self.container_combo.setAccessibleName(self.tr('Format'))
        self._scroll.setAccessibleName(self.tr('Quality'))
        self.advanced_check.setText(self.tr('Advanced view'))
        self.advanced_check.setToolTip(self.tr('Show individual streams: codec, FPS, container'))
        if not self._ffmpeg:
            self.kind_combo.setToolTip(self.tr('Extracting audio requires FFmpeg'))
        self._reload_kinds()
        self._reload_containers()
        self._reload_rows()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    # -------------------------------------------------------------- logic

    def _on_kind_changed(self) -> None:
        self._reload_containers()
        self._reload_rows()

    def _on_container_changed(self) -> None:
        # Changing the container changes which stream is picked for a given
        # resolution, so the list has to reflect it
        self._reload_rows()

    @property
    def kind(self) -> MediaKind:
        try:
            return MediaKind(self.kind_combo.currentData())
        except ValueError:
            return MediaKind.VIDEO

    @property
    def is_audio(self) -> bool:
        return self.kind is MediaKind.AUDIO

    def container(self) -> str:
        return '' if self.is_audio else (self.container_combo.currentData() or '')

    def audio_format(self) -> str:
        return (self.container_combo.currentData() or '') if self.is_audio else self._settings.audio_format

    def quality(self) -> int:
        button = self._group.checkedButton()
        if button is None:
            return QUALITY_BEST
        return int(button.property('quality') or QUALITY_BEST)

    def format_selector(self) -> str:
        button = self._group.checkedButton()
        return (button.property('selector') or '') if button else ''

    def quality_label(self) -> str:
        """Label of the selected quality, remembered on the queue card."""
        button = self._group.checkedButton()
        if button is None:
            return ''
        return button.property('shortLabel') or ''

    def expected_size(self) -> int | None:
        button = self._group.checkedButton()
        return button.property('filesize') if button else None

    def _reload_kinds(self) -> None:
        _refill(self.kind_combo,
                [(kind.value, labels.media_kind_label(kind)) for kind in MediaKind],
                self._settings.kind)

    def _reload_containers(self) -> None:
        if self.is_audio:
            entries = [(value, labels.audio_format_label(value)) for value in fs.AUDIO_FORMATS]
            preferred = self._settings.audio_format
        else:
            entries = [(value, labels.container_label(value)) for value in fs.VIDEO_CONTAINERS]
            preferred = self._settings.video_container
        _refill(self.container_combo, entries, preferred)

        if not self._ffmpeg and not self.is_audio:
            # Without FFmpeg there is no merging or remuxing; the source
            # container is all we get
            self.container_combo.setEnabled(False)
            self.container_combo.setToolTip(self.tr('Changing the container requires FFmpeg'))
            index = self.container_combo.findData('')
            if index >= 0:
                self.container_combo.setCurrentIndex(index)

    def _reload_rows(self) -> None:
        for button in list(self._group.buttons()):
            self._group.removeButton(button)
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        rows = self._advanced_rows() if self.advanced_check.isChecked() else self._simple_rows()
        for position, row in enumerate(rows):
            self._add_row(position, *row)
        self._grid.setRowStretch(len(rows), 1)

        buttons = self._group.buttons()
        if buttons:
            buttons[0].setChecked(True)
        self.changed.emit()

    def _simple_rows(self):
        """(grade, label, details, size, quality, selector)"""
        if self.is_audio:
            options = fs.audio_quality_options(self._info.formats)
            details = labels.audio_quality_details
        else:
            options = fs.quality_options(self._info.formats, self.container())
            details = labels.quality_details
        return [(labels.quality_grade_label(option.grade),
                 option.label or labels.quality_label(option.value, kind=self.kind),
                 details(option), option.filesize, option.value, '')
                for option in options]

    def _advanced_rows(self):
        variants = (fs.audio_variants(self._info.formats) if self.is_audio
                    else fs.video_variants(self._info.formats))
        if not variants:
            return self._simple_rows()
        return [(labels.quality_grade_label(v.grade), v.label, '', v.filesize, QUALITY_BEST, v.selector)
                for v in variants]

    def _add_row(self, position: int, grade: str, label: str, details: str,
                 filesize: int | None, quality: int, selector: str) -> None:
        radio = QRadioButton(grade)
        radio.setProperty('quality', quality)
        radio.setProperty('selector', selector)
        radio.setProperty('filesize', filesize)
        radio.setProperty('shortLabel', label)
        self._group.addButton(radio, position)
        self._grid.addWidget(radio, position, 0)

        strong = QLabel(label)
        font = strong.font()
        font.setBold(True)
        strong.setFont(font)
        self._grid.addWidget(strong, position, 1)

        muted = QLabel(details)
        muted.setObjectName('MutedLabel')
        self._grid.addWidget(muted, position, 2)

        size = QLabel(fmt.size(filesize) if filesize else fmt.DASH)
        size.setObjectName('MutedLabel')
        size.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(size, position, 3)


def _refill(combo: QComboBox, entries, preferred) -> None:
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for value, text in entries:
        combo.addItem(text, value)
    for candidate in (current, preferred):
        index = combo.findData(candidate)
        if index >= 0:
            combo.setCurrentIndex(index)
            break
    else:
        combo.setCurrentIndex(0)
    combo.blockSignals(False)
