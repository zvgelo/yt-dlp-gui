"""The Preferences dialog keeps what it was given."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.core.models import MediaKind
from app.core.ytdlp_service import FFmpegStatus
from app.gui.settings_dialog import SettingsDialog
from app.i18n import TranslationManager
from app.settings import AppSettings
from app.theme import ThemeManager


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def _dialog(settings, ffmpeg=None):
    qt_settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                            'yt-dlp-gui-tests', 'settings-dialog')
    return SettingsDialog(settings, ThemeManager(qt_settings), TranslationManager(qt_settings), ffmpeg)


def test_saving_unchanged_preferences_keeps_the_download_defaults(qapp, tmp_path):
    settings = AppSettings(output_dir=str(tmp_path), kind=MediaKind.AUDIO.value, quality=720,
                           video_container='mkv', audio_format='flac',
                           cookies_from_browser='firefox')
    result = _dialog(settings).result_settings()

    assert result.kind == MediaKind.AUDIO.value
    assert result.quality == 720
    assert result.video_container == 'mkv'
    assert result.audio_format == 'flac'
    assert result.cookies_from_browser == 'firefox'


def test_a_missing_ffmpeg_is_not_shown_as_ok(qapp, tmp_path):
    dialog = _dialog(AppSettings(output_dir=str(tmp_path)),
                     FFmpegStatus(available=False, probe_available=False))
    assert dialog.ffmpeg_status.objectName() == 'StatusWarn'

    dialog = _dialog(AppSettings(output_dir=str(tmp_path)),
                     FFmpegStatus(available=True, probe_available=True, version='8.1.2'))
    assert dialog.ffmpeg_status.objectName() == 'StatusOk'
    assert '8.1.2' in dialog.ffmpeg_status.text()
