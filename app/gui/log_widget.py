"""Log panel: yt-dlp logger messages forwarded by signals from the workers.

Entries are stored as (level, text) pairs rather than ready HTML, so that
after a theme change the panel repaints in the new colours instead of
leaving stale lines behind.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QEvent, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import Theme, active_theme

MAX_ENTRIES = 5000


def level_color(theme: Theme, level: str) -> str:
    return {
        'ERROR': theme.error,
        'WARN': theme.warning,
        'DEBUG': theme.text_disabled,
        'INFO': theme.text_secondary,
    }.get(level, theme.text_primary)


class LogDock(QDockWidget):
    """Log dock; hidden by default so it does not flood the main view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('LogDock')
        self._entries: deque[tuple[str, str]] = deque(maxlen=MAX_ENTRIES)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        self._view = QPlainTextEdit()
        self._view.setObjectName('LogView')
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(MAX_ENTRIES)
        layout.addWidget(self._view, 1)

        controls = QHBoxLayout()
        self._debug_check = QCheckBox()
        self._debug_check.setChecked(True)
        self._debug_check.toggled.connect(lambda *_: self.restyle())
        controls.addWidget(self._debug_check)
        controls.addStretch(1)

        self._copy_button = QPushButton()
        self._copy_button.clicked.connect(self._copy_all)
        controls.addWidget(self._copy_button)

        self._clear_button = QPushButton()
        self._clear_button.clicked.connect(self.clear)
        controls.addWidget(self._clear_button)

        layout.addLayout(controls)
        self.setWidget(container)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr('Log'))
        self._debug_check.setText(self.tr('Show diagnostic messages'))
        self._copy_button.setText(self.tr('Copy'))
        self._clear_button.setText(self.tr('Clear'))

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    @Slot(str, str)
    def append(self, level: str, message: str) -> None:
        self._entries.append((level, message or ''))
        if level == 'DEBUG' and not self._debug_check.isChecked():
            return
        self._view.appendHtml(_format(active_theme(), level, message or ''))
        self._view.moveCursor(QTextCursor.MoveOperation.End)

    def restyle(self) -> None:
        """Przerysowuje dziennik w kolorach aktualnego motywu."""
        show_debug = self._debug_check.isChecked()
        theme = active_theme()
        html = ''.join(
            _format(theme, level, message)
            for level, message in self._entries
            if show_debug or level != 'DEBUG'
        )
        self._view.clear()
        if html:
            self._view.appendHtml(html)
            self._view.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self) -> None:
        self._entries.clear()
        self._view.clear()

    def _copy_all(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._view.toPlainText())


def _format(theme: Theme, level: str, message: str) -> str:
    text = message.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return f'<div style="color:{level_color(theme, level)}">[{level}] {text}</div>'
