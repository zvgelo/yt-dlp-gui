"""Details of a failed download: the full message and the attempt history.

The card in the "Failed" tab shows only a short reason; the technical
details and the course of each attempt land here so the list stays clean.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..core.errors import AppErrorCode, FriendlyError
from ..core.models import DownloadTask
from . import labels
from .focus import order_button_box


class ErrorDetailsDialog(QDialog):
    def __init__(self, task: DownloadTask, parent=None):
        super().__init__(parent)
        self._task = task
        self.setMinimumSize(620, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.title_label = QLabel(task.display_title)
        self.title_label.setObjectName('TitleLabel')
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.reason_label = QLabel()
        self.reason_label.setObjectName('StatusError')
        self.reason_label.setWordWrap(True)
        layout.addWidget(self.reason_label)

        self.meta_label = QLabel()
        self.meta_label.setObjectName('MutedLabel')
        self.meta_label.setWordWrap(True)
        self.meta_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.meta_label)

        self.attempts_caption = QLabel()
        self.attempts_caption.setObjectName('SectionLabel')
        layout.addWidget(self.attempts_caption)

        self.attempts_list = QListWidget()
        self.attempts_list.setAccessibleName(self.tr('Attempt history'))
        self.attempts_list.setMaximumHeight(150)
        layout.addWidget(self.attempts_list)

        self.message_caption = QLabel()
        self.message_caption.setObjectName('SectionLabel')
        layout.addWidget(self.message_caption)

        self.message_view = QPlainTextEdit()
        self.message_view.setAccessibleName(self.tr('Original message from yt-dlp'))
        self.message_view.setReadOnly(True)
        # The original yt-dlp message is left untranslated
        self.message_view.setPlainText(task.error or '')
        layout.addWidget(self.message_view, 1)

        self.buttons = QDialogButtonBox()
        self._close_button = self.buttons.addButton('', QDialogButtonBox.ButtonRole.AcceptRole)
        self._close_button.clicked.connect(self.accept)
        layout.addWidget(self.buttons)
        order_button_box(self, self.buttons)

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        task = self._task
        self.setWindowTitle(self.tr('Error details'))
        self._close_button.setText(self.tr('Close'))
        self.attempts_caption.setText(self.tr('Attempt history'))
        self.message_caption.setText(self.tr('Full message from yt-dlp'))

        error = FriendlyError(task.error_code or AppErrorCode.UNKNOWN, task.error)
        self.reason_label.setText(labels.error_text(error))
        self.meta_label.setText(' · '.join(filter(None, [
            self.tr('Category: {0}').format(error.category.value),
            self.tr('Address: {0}').format(task.url),
            self.tr('Playlist: {0}').format(task.request.playlist_title)
            if task.request.playlist_title else '',
        ])))

        self.attempts_list.clear()
        for attempt in task.attempts:
            self.attempts_list.addItem(labels.attempt_line(attempt))
        if not task.attempts:
            self.attempts_list.addItem(self.tr('No recorded attempts'))

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
