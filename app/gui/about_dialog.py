"""What this build is: name, version, what it is made of, and its licence.

Deliberately small. The technical block a bug report wants - resolved paths,
platform, build metadata - already lives in Preferences → Diagnostics; this
box answers "what am I running?" in a form a user can read, and takes its
numbers from the same cached `diagnostics.collect()` so opening it never
probes a binary again.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import APP_TITLE, LICENSE_NAME, PROJECT_URL, __version__
from ..core import diagnostics
from ..core.runtime_tools import ToolInfo, ToolState
from ..resources import license_file
from ..theme import active_theme
from . import icons
from .focus import apply_tab_order, order_button_box

#: Rows in the components table, in the order they are shown
_COMPONENTS = ('yt-dlp', 'FFmpeg', 'Deno', 'PySide6', 'Python')


def _tool_version(info: ToolInfo) -> str:
    """A version for a helper binary, or a short reason there is none."""
    if info.state is ToolState.MISSING:
        return ''
    return info.version or ''


class AboutDialog(QDialog):
    """Application identity, versions, repository and licence."""

    def __init__(self, parent=None, themes=None):
        super().__init__(parent)
        self.setObjectName('AboutDialog')
        self.setModal(True)
        self._report = diagnostics.collect()
        self._themes = themes

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(14)
        self.logo = QLabel()
        self.logo.setFixedSize(64, 64)
        header.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignTop)

        identity = QVBoxLayout()
        identity.setSpacing(2)
        self.name_label = QLabel(APP_TITLE)
        self.name_label.setObjectName('TitleLabel')
        identity.addWidget(self.name_label)
        self.version_label = QLabel()
        self.version_label.setObjectName('MutedLabel')
        self.version_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        identity.addWidget(self.version_label)
        identity.addStretch(1)
        header.addLayout(identity, 1)
        layout.addLayout(header)

        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)

        self.components_caption = QLabel()
        self.components_caption.setObjectName('SectionLabel')
        layout.addWidget(self.components_caption)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(4)
        self._value_labels: dict[str, QLabel] = {}
        for row, name in enumerate(_COMPONENTS):
            caption = QLabel(name)
            caption.setObjectName('MutedLabel')
            value = QLabel()
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setAccessibleName(name)
            self._grid.addWidget(caption, row, 0)
            self._grid.addWidget(value, row, 1)
            self._value_labels[name] = value
        self._grid.setColumnStretch(1, 1)
        layout.addLayout(self._grid)

        # A link rather than a button: it is an address, and it is worth being
        # able to read and copy it even where nothing can open a browser.
        self.repository_label = QLabel()
        self.repository_label.setOpenExternalLinks(False)
        self.repository_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.repository_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.repository_label.linkActivated.connect(self._open_repository)
        layout.addWidget(self.repository_label)

        self.license_label = QLabel()
        self.license_label.setWordWrap(True)
        layout.addWidget(self.license_label)

        self.license_view = QPlainTextEdit()
        self.license_view.setObjectName('LogView')
        self.license_view.setReadOnly(True)
        self.license_view.setAccessibleName(self.tr('Licence text'))
        self.license_view.setVisible(False)
        layout.addWidget(self.license_view, 1)

        self.buttons = QDialogButtonBox()
        self.license_button = QPushButton()
        self.license_button.clicked.connect(self._toggle_license)
        self.buttons.addButton(self.license_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.close_button = self.buttons.addButton('', QDialogButtonBox.ButtonRole.AcceptRole)
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.buttons)

        if license_file() is None:
            self.license_button.setVisible(False)

        order_button_box(self, self.buttons)
        apply_tab_order(self, [self.repository_label, self.license_button,
                               self.close_button])

        if themes is not None:
            themes.themeChanged.connect(self._on_theme_changed)

        self.restyle()
        self.retranslate_ui()

    # --------------------------------------------------------------- text

    def retranslate_ui(self) -> None:
        report = self._report
        self.setWindowTitle(self.tr('About {0}').format(APP_TITLE))
        self.setAccessibleName(self.tr('About {0}').format(APP_TITLE))
        self.version_label.setText(self.tr('Version {0}').format(__version__))
        self.description_label.setText(
            self.tr('A desktop graphical interface for yt-dlp.'))
        self.components_caption.setText(self.tr('Built with'))

        missing = self.tr('not found')
        values = {
            'yt-dlp': report.yt_dlp_version or missing,
            'FFmpeg': _tool_version(report.ffmpeg) or missing,
            'Deno': _tool_version(report.js_runtime) or missing,
            # Not translated: two version numbers and the name of a library
            'PySide6': f'{report.pyside_version} (Qt {report.qt_version})'
            if report.pyside_version else missing,
            'Python': report.python_version,
        }
        for name, text in values.items():
            self._value_labels[name].setText(text)

        # tr() outside the f-string: lupdate does not look inside one
        caption = self.tr('Project')
        # The colour goes on the anchor itself: a QLabel link takes its colour
        # from the palette or from an inline style, never from an `a` rule in
        # setStyleSheet, and Qt's default blue is not one of our tokens.
        colour = active_theme().accent
        self.repository_label.setText(
            f'{caption}: <a href="{PROJECT_URL}" style="color: {colour};">'
            f'{PROJECT_URL}</a>')
        self.repository_label.setAccessibleName(self.tr('Project repository'))
        self.license_label.setText(self.tr('Released under {0}.').format(LICENSE_NAME))
        self.license_button.setText(
            self.tr('Hide licence') if self.license_view.isVisibleTo(self)
            else self.tr('View licence'))
        self.license_view.setAccessibleName(self.tr('Licence text'))
        self.close_button.setText(self.tr('Close'))
        self.close_button.setAccessibleName(self.tr('Close'))

    # ------------------------------------------------------------ actions

    def _open_repository(self, url: str) -> None:
        QDesktopServices.openUrl(url)

    def _toggle_license(self) -> None:
        """Show the licence text from the build itself, not from the network."""
        if not self.license_view.isVisibleTo(self):
            path = license_file()
            if path is None:
                return
            try:
                self.license_view.setPlainText(path.read_text(encoding='utf-8'))
            except OSError as error:
                self.license_view.setPlainText(str(error))
            self.license_view.setVisible(True)
            self.resize(self.width(), max(self.height(), 520))
        else:
            self.license_view.setVisible(False)
            self.adjustSize()
        self.retranslate_ui()

    def restyle(self) -> None:
        """The logo and the link colour are painted by us, not by the QSS."""
        ratio = self.devicePixelRatioF() if self.windowHandle() else 1.0
        self.logo.setPixmap(icons.app_logo(64, ratio))

    def _on_theme_changed(self, _theme) -> None:
        self.restyle()
        self.retranslate_ui()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
