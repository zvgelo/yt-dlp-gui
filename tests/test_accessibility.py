"""Keyboard navigation and accessible names for every interactive control.

An icon-only button or a combo box whose label sits beside it announces nothing
on its own. The rule this file enforces: every focusable control carries a name
- its own text, an explicit `accessibleName`, or the form label it is buddied
to - and the focus chain follows the visible layout rather than the order the
widgets happened to be constructed in.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from app.core.models import FormatInfo, MediaInfo, PlaylistEntry
from app.gui.download_dialog import DownloadDialog
from app.gui.options_widget import OptionsWidget
from app.gui.playlist_dialog import PlaylistDialog
from app.gui.settings_dialog import SettingsDialog
from app.gui.top_bar import TopBar
from app.i18n import TranslationManager
from app.settings import AppSettings
from app.theme import ThemeManager
from app.workers.thumbnail_worker import ThumbnailCache


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return AppSettings(output_dir=str(tmp_path))


@pytest.fixture
def info():
    return MediaInfo(
        url='https://example.com/v', title='Example', media_id='v', extractor='Youtube',
        duration=120.0, uploader='Author',
        formats=(FormatInfo(format_id='137', ext='mp4', height=1080, vcodec='avc1',
                            acodec='none', filesize=1000),
                 FormatInfo(format_id='140', ext='m4a', height=None, vcodec='none',
                            acodec='mp4a', filesize=100)))


@pytest.fixture
def playlist_info():
    return MediaInfo(url='https://example.com/list', title='Mix', is_playlist=True,
                     playlist_title='Mix',
                     entries=tuple(PlaylistEntry(url=f'https://example.com/{i}',
                                                 title=f'Track {i}', index=i)
                                   for i in range(1, 6)))


def _buddy_label(widget: QWidget) -> str:
    parent = widget.parentWidget()
    if parent is None:
        return ''
    for label in parent.findChildren(QLabel):
        if label.buddy() is widget:
            return label.text()
    return ''


def _name(widget: QWidget) -> str:
    text = widget.text() if hasattr(widget, 'text') else ''
    return widget.accessibleName() or _buddy_label(widget) or text


def _focusable(root: QWidget) -> list[QWidget]:
    return [child for child in root.findChildren(QWidget)
            if child.focusPolicy() != Qt.FocusPolicy.NoFocus
            and child.isVisibleTo(root)
            and not child.objectName().startswith('qt_')]


def _unnamed(root: QWidget) -> list[str]:
    return sorted(f'{w.__class__.__name__}#{w.objectName()}'
                  for w in _focusable(root) if not _name(w).strip())


def _chain(root: QWidget) -> list[str]:
    """Names in focus-chain order, which is what Tab actually walks."""
    start = root.nextInFocusChain()
    seen, out, current = set(), [], start
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if (current.focusPolicy() != Qt.FocusPolicy.NoFocus
                and current.isVisibleTo(root)
                and not current.objectName().startswith('qt_')):
            out.append(_name(current))
        current = current.nextInFocusChain()
        if current is start:
            break
    return out


# ------------------------------------------------------------- accessible names


def test_the_top_bar_names_every_control(qapp, settings):
    bar = TopBar(settings)
    bar.show()
    assert _unnamed(bar) == []
    # The action buttons are icon-only, so the name is all a screen reader has
    for button in (bar.start_button, bar.pause_button, bar.cancel_button,
                   bar.log_button, bar.settings_button):
        assert button.accessibleName()
        assert button.toolTip()


def test_the_download_dialog_names_every_control(qapp, info, settings):
    dialog = DownloadDialog(info, settings, ThumbnailCache(), ffmpeg_available=True)
    dialog.show()
    assert _unnamed(dialog) == []


def test_the_playlist_dialog_names_every_control(qapp, playlist_info, settings):
    dialog = PlaylistDialog(playlist_info, settings, ffmpeg_available=True)
    dialog.show()
    assert _unnamed(dialog) == []


def test_the_settings_dialog_names_every_control(qapp, settings, tmp_path):
    from PySide6.QtCore import QSettings

    qt_settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                            'yt-dlp-gui-tests', 'accessibility')
    dialog = SettingsDialog(settings, ThemeManager(qt_settings),
                            TranslationManager(qt_settings))
    dialog.show()
    assert _unnamed(dialog) == []


def test_form_labels_are_buddies(qapp, settings):
    """`QFormLayout.addRow(label, field)` does not do this on its own."""
    from PySide6.QtCore import QSettings

    qt_settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                            'yt-dlp-gui-tests', 'accessibility')
    dialog = SettingsDialog(settings, ThemeManager(qt_settings),
                            TranslationManager(qt_settings))
    dialog.show()
    assert _buddy_label(dialog.theme_combo) == dialog.theme_row_label.text()
    assert _buddy_label(dialog.language_combo) == dialog.language_row_label.text()
    # A row whose field is a layout still points at the control, not the button
    assert _buddy_label(dialog.dir_edit) == dialog.dir_row_label.text()


def test_the_three_browse_buttons_are_told_apart(qapp, settings):
    """They all read "Choose…"; only the accessible name says what for."""
    from PySide6.QtCore import QSettings

    qt_settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                            'yt-dlp-gui-tests', 'accessibility')
    dialog = SettingsDialog(settings, ThemeManager(qt_settings),
                            TranslationManager(qt_settings))
    names = {dialog.dir_browse.accessibleName(),
             dialog.cookies_browse.accessibleName(),
             dialog.ffmpeg_browse.accessibleName()}
    assert len(names) == 3
    assert '' not in names


# ------------------------------------------------------------------- tab order


def test_the_download_dialog_tab_order_follows_the_layout(qapp, info, settings):
    dialog = DownloadDialog(info, settings, ThumbnailCache(), ffmpeg_available=True)
    dialog.show()
    chain = _chain(dialog)

    def position(name: str) -> int:
        return next(index for index, entry in enumerate(chain) if entry == name)

    # format controls, then options, then the destination, then the buttons
    assert position(dialog.format_widget.kind_combo.accessibleName()) \
        < position(dialog.options_widget.path_edit.accessibleName())
    assert position(dialog.options_widget.path_edit.accessibleName()) < position('Download')
    assert position('Download') < position('Cancel')


def test_the_playlist_dialog_ends_with_its_buttons(qapp, playlist_info, settings):
    dialog = PlaylistDialog(playlist_info, settings, ffmpeg_available=True)
    dialog.show()
    chain = _chain(dialog)
    assert chain[-2:] == ['Add to queue', 'Cancel']
    assert chain.index('Playlist items') < chain.index('Add to queue')


def test_the_settings_dialog_starts_with_appearance(qapp, settings):
    from PySide6.QtCore import QSettings

    qt_settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                            'yt-dlp-gui-tests', 'accessibility')
    dialog = SettingsDialog(settings, ThemeManager(qt_settings),
                            TranslationManager(qt_settings))
    dialog.show()
    chain = [entry for entry in _chain(dialog) if entry]
    assert chain.index(dialog.theme_row_label.text()) \
        < chain.index(dialog.language_row_label.text())
    assert chain.index(dialog.language_row_label.text()) < chain.index('Save')
    assert chain[-2:] == ['Save', 'Cancel']


def test_no_control_traps_the_focus(qapp, info, settings):
    """Tabbing forward from any control must eventually come back around."""
    dialog = DownloadDialog(info, settings, ThumbnailCache(), ffmpeg_available=True)
    dialog.show()
    controls = _focusable(dialog)
    assert len(controls) >= 5
    for control in controls:
        assert control.nextInFocusChain() is not control
        assert control.previousInFocusChain() is not control


def test_options_labels_describe_their_fields(qapp, info, settings):
    widget = OptionsWidget(info, settings, ffmpeg_available=True)
    widget.show()
    assert widget.language_combo.accessibleName()
    assert widget.path_edit.accessibleName()
    assert widget.browse_button.accessibleName()


# -------------------------------------------------------------------- i18n


def test_accessible_names_are_translated(qapp, settings, tmp_path):
    """Nothing is hard-coded: switching the language renames the controls too."""
    from PySide6.QtCore import QSettings

    qt_settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                            'yt-dlp-gui-tests', 'accessibility-i18n')
    translations = TranslationManager(qt_settings)
    bar = TopBar(settings)
    bar.show()

    translations.set_language('en')
    qapp.processEvents()
    english = bar.settings_button.accessibleName()

    translations.set_language('pl')
    qapp.processEvents()
    polish = bar.settings_button.accessibleName()

    translations.set_language('en')
    qapp.processEvents()

    assert english and polish
    assert english != polish
