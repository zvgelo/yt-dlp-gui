"""Top bar from the mockup: logo, "Paste link", defaults, folder and actions."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from ..core import format_service as fs
from ..core.models import MediaKind
from ..settings import AppSettings
from ..state import AppState
from . import icons, labels

#: How far the default-choice combos may shrink before the window refuses
_COMBO_MIN_WIDTH = 92

#: The destination button keeps room for a shortened folder name and the arrow
_DIR_MIN_WIDTH = 78


class _BarCombo(QComboBox):
    """A combo that prefers to be comfortable but agrees to be narrow.

    `minimumContentsLength` sets both the preferred and the minimum width, and
    with three of these in the bar that alone pushed the smallest usable window
    past 1200 pixels. Overriding the minimum keeps the roomy default while
    letting a narrow window squeeze them.
    """

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), _COMBO_MIN_WIDTH), hint.height())


class TopBar(QWidget):
    """Choices made here are the defaults for new items and for smart mode."""

    pasteRequested = Signal()
    startRequested = Signal()
    pauseRequested = Signal()
    cancelRequested = Signal()
    directoryRequested = Signal()
    settingsRequested = Signal()
    logToggled = Signal()
    defaultsChanged = Signal()

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setObjectName('TopBar')
        self._settings = settings
        self._directory = settings.output_dir

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        self.brand = QLabel()
        self.brand.setObjectName('BrandMark')
        self.brand.setFixedSize(QSize(24, 24))
        layout.addWidget(self.brand)
        layout.addSpacing(8)

        self.paste_button = QPushButton()
        self.paste_button.setObjectName('PasteButton')
        self.paste_button.clicked.connect(self.pasteRequested)
        layout.addWidget(self.paste_button)
        layout.addSpacing(14)

        self.kind_label = _bar_label()
        layout.addWidget(self.kind_label)
        self.kind_combo = self._combo(layout)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)

        self.quality_label = _bar_label()
        layout.addWidget(self.quality_label)
        self.quality_combo = self._combo(layout)
        self.quality_combo.currentIndexChanged.connect(self._emit_defaults)

        self.format_label = _bar_label()
        layout.addWidget(self.format_label)
        self.container_combo = self._combo(layout)
        self.container_combo.currentIndexChanged.connect(self._emit_defaults)

        layout.addSpacing(8)
        self.dir_label = _bar_label()
        layout.addWidget(self.dir_label)
        self.dir_button = QToolButton()
        self.dir_button.setObjectName('DirButton')
        self.dir_button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.dir_button.setMinimumWidth(_DIR_MIN_WIDTH)
        self.dir_button.clicked.connect(self.directoryRequested)
        layout.addWidget(self.dir_button)

        layout.addStretch(1)

        self.start_button = self._action(layout, 'play', self.startRequested)
        self.pause_button = self._action(layout, 'pause', self.pauseRequested)
        self.cancel_button = self._action(layout, 'cancel', self.cancelRequested)
        layout.addSpacing(6)
        self.log_button = self._action(layout, 'log', self.logToggled)
        self.settings_button = self._action(layout, 'settings', self.settingsRequested)

        self.apply_settings(settings)
        self.retranslate_ui()
        self.restyle()

    # ------------------------------------------------------- construction

    def _combo(self, layout: QHBoxLayout) -> QComboBox:
        combo = _BarCombo()
        combo.setObjectName('BarCombo')
        # Without this the combo stretches the bar to its longest entry
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(11)
        # The preferred width stays; a narrow window may shrink it rather than
        # force a horizontal scrollbar on the whole application
        combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        combo.setMinimumWidth(_COMBO_MIN_WIDTH)
        layout.addWidget(combo)
        return combo

    def _action(self, layout: QHBoxLayout, icon_name: str, signal) -> QToolButton:
        button = QToolButton()
        button.setObjectName('BarButton')
        button.setProperty('iconName', icon_name)
        button.setIconSize(QSize(18, 18))
        button.clicked.connect(signal)
        layout.addWidget(button)
        return button

    # --------------------------------------------------------------- text

    def retranslate_ui(self) -> None:
        self.paste_button.setText(self.tr('Paste link'))
        self.paste_button.setToolTip(self.tr('Add addresses from the clipboard (Ctrl+V)'))
        self.kind_label.setText(self.tr('Download:'))
        self.quality_label.setText(self.tr('Quality:'))
        self.format_label.setText(self.tr('Format:'))
        self.dir_label.setText(self.tr('Save to:'))

        # The visible label is next to the control, not inside it, so assistive
        # technology needs the name spelled out
        self.kind_combo.setAccessibleName(self.tr('What to download'))
        self.quality_combo.setAccessibleName(self.tr('Default quality'))
        self.container_combo.setAccessibleName(self.tr('Default format'))
        self.dir_button.setAccessibleName(self.tr('Destination folder'))
        self.dir_button.setToolTip(self.tr('Choose destination folder'))

        for button, text in (
            (self.start_button, self.tr('Resume the queue')),
            (self.pause_button, self.tr('Pause after the current download')),
            (self.cancel_button, self.tr('Cancel selected')),
            (self.log_button, self.tr('Show or hide the log')),
            (self.settings_button, self.tr('Preferences')),
        ):
            button.setToolTip(text)
            # The buttons are icon-only, so the accessible name carries the meaning
            button.setAccessibleName(text)

        self._reload_kinds()
        self._reload_qualities()
        self._reload_containers()
        self.update_directory(self._settings.output_dir)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def restyle(self) -> None:
        """Icons are painted in the theme colour, so refresh them after a change."""
        self.brand.setPixmap(icons.app_logo(24, self.devicePixelRatioF()))
        for button in (self.start_button, self.pause_button, self.cancel_button,
                       self.log_button, self.settings_button):
            button.setIcon(icons.bar_icon(button.property('iconName')))

    # -------------------------------------------------------------- logic

    def apply_settings(self, settings: AppSettings) -> None:
        """Set the bar from the stored preferences without emitting signals."""
        self._settings = settings
        self._reload_kinds()
        self._reload_qualities()
        self._reload_containers()
        self.update_directory(settings.output_dir)

    def update_directory(self, path: str) -> None:
        self._directory = path
        self._update_directory_text()

    def _update_directory_text(self) -> None:
        """Show the folder name, shortened to the width the button has.

        A deep path would otherwise set the minimum width of the whole window.
        The full path stays in the tooltip.
        """
        path = self._directory
        name = os.path.basename(path.rstrip(os.sep)) or path
        caption = f'…{os.sep}{name}'
        room = max(self.dir_button.width(), _DIR_MIN_WIDTH) - 34
        caption = self.dir_button.fontMetrics().elidedText(
            caption, Qt.TextElideMode.ElideMiddle, room)
        self.dir_button.setText(f'{caption}  ▾')
        self.dir_button.setToolTip(path)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_directory_text()

    def apply_state(self, state: AppState, *, running: bool, has_selection: bool) -> None:
        self.start_button.setEnabled(not running)
        self.pause_button.setEnabled(running)
        busy = state in (AppState.DOWNLOADING, AppState.POSTPROCESSING)
        self.cancel_button.setEnabled(has_selection or busy)
        self.paste_button.setEnabled(state is not AppState.ANALYZING)

    @property
    def kind(self) -> MediaKind:
        try:
            return MediaKind(self.kind_combo.currentData())
        except ValueError:
            return MediaKind.VIDEO

    @property
    def quality(self) -> int:
        value = self.quality_combo.currentData()
        return int(value) if value is not None else 0

    @property
    def container(self) -> str:
        return self.container_combo.currentData() or ''

    def _on_kind_changed(self) -> None:
        self._reload_qualities()
        self._reload_containers()
        self._emit_defaults()

    def _reload_kinds(self) -> None:
        _refill(self.kind_combo,
                [(kind.value, labels.media_kind_label(kind)) for kind in MediaKind],
                self._settings.kind)

    def _reload_qualities(self) -> None:
        _refill(self.quality_combo,
                [(value, labels.quality_label(value, kind=self.kind, short=True))
                 for value in fs.QUALITY_LADDER],
                self._settings.quality)

    def _reload_containers(self) -> None:
        if self.kind is MediaKind.AUDIO:
            entries = [(value, labels.audio_format_label(value)) for value in fs.AUDIO_FORMATS]
            preferred = self._settings.audio_format
        else:
            entries = [(value, labels.container_label(value)) for value in fs.VIDEO_CONTAINERS]
            preferred = self._settings.video_container
        _refill(self.container_combo, entries, preferred)

    def _emit_defaults(self) -> None:
        self.defaultsChanged.emit()


def _bar_label() -> QLabel:
    label = QLabel()
    label.setObjectName('BarLabel')
    return label


def _refill(combo: QComboBox, entries, preferred) -> None:
    """Replace the entries, keeping the selection and emitting no signals."""
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
