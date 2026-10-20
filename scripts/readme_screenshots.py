#!/usr/bin/env python3
"""Render the README screenshots from the real interface.

    python scripts/readme_screenshots.py [--out assets/readme/screenshots] [--scale 2]

The windows are the application's own widgets, built offscreen against a
throw-away profile and filled with demo items. Nothing is downloaded and no
real settings, history or thumbnails are touched; the cover images are
generated, so the pictures carry no third-party artwork.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _isolate(scale: float) -> None:
    """Point every Qt location at a temporary profile before Qt starts."""
    home = Path(tempfile.mkdtemp(prefix='yt-dlp-gui-shots-'))
    for name in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        os.environ[name] = str(home / name.lower())
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ['QT_SCALE_FACTOR'] = str(scale)
    os.environ['YTDLP_GUI_SKIP_RUNTIME_HINT'] = '1'


def _cover(index: int):
    """An abstract 16:9 cover: two soft colour fields and a play mark."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QPolygonF

    palettes = [('#2b5876', '#4e4376'), ('#d76d77', '#ffaf7b'), ('#134e5e', '#71b280'),
                ('#373b44', '#4286f4'), ('#c33764', '#1d2671'), ('#ee9ca7', '#ffdde1'),
                ('#0f2027', '#2c5364'), ('#f7971e', '#ffd200')]
    first, second = palettes[index % len(palettes)]
    pixmap = QPixmap(480, 270)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, 480, 270)
    gradient.setColorAt(0, QColor(first))
    gradient.setColorAt(1, QColor(second))
    painter.fillRect(pixmap.rect(), gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 40))
    painter.drawEllipse(QPointF(380 - index * 23 % 200, 60 + index * 37 % 150), 150, 150)
    painter.setBrush(QColor(255, 255, 255, 200))
    painter.drawPolygon(QPolygonF([QPointF(220, 105), QPointF(220, 165), QPointF(270, 135)]))
    painter.end()
    return pixmap


#: A neutral folder, so no real home directory ends up in a picture
DEMO_FOLDER = '~/Videos'

DEMO_VIDEOS = [
    ('Building a home studio on a budget', 'Workshop Notes', 1312.0),
    ('Morning jazz session — live from the rooftop', 'Open Air Sessions', 3605.0),
    ('How sourdough actually works', 'Kitchen Science', 846.0),
    ('Night train across the mountains (4K)', 'Slow Travel', 5420.0),
    ('Intro to synthesizers, part 3', 'Patch Cable', 1104.0),
    ('Lecture 7: Graph algorithms', 'Open Courseware', 4380.0),
]


def _populate(window) -> None:
    """Queue demo items in the states a real session goes through."""
    from app.core.errors import AppErrorCode
    from app.core.models import (
        DownloadProgress,
        DownloadRequest,
        DownloadResult,
        DownloadTask,
        MediaKind,
        PlaylistJob,
    )
    from app.state import TaskState

    controller = window.controller
    controller.pause()
    out = DEMO_FOLDER

    def task(i, title, author, duration, **request):
        url = f'https://example.com/watch/{i}'
        window.thumbnails._source[f'demo://{i}'] = _cover(i)
        return DownloadTask(request=DownloadRequest(url=url, output_dir=out, **request),
                            title=title, uploader=author, duration=duration,
                            thumbnail_url=f'demo://{i}', media_id=f'demo{i}', extractor='Generic',
                            quality_label='' if request.get('kind') is MediaKind.AUDIO else '1080p')

    tasks = [task(i, *video) for i, video in enumerate(DEMO_VIDEOS[:4])]
    tasks[1] = task(1, *DEMO_VIDEOS[1], kind=MediaKind.AUDIO, audio_format='mp3')
    controller.enqueue(tasks, autostart=False)

    playlist = PlaylistJob(title='Intro to synthesizers', source_url='https://example.com/list/1',
                           uploader='Patch Cable', thumbnail_url='demo://4',
                           discovered_items=2, enumeration_complete=True)
    controller.enqueue([task(4, *DEMO_VIDEOS[4]), task(5, *DEMO_VIDEOS[5])],
                       autostart=False, playlist=playlist)

    every = controller.tasks
    downloading, audio, finished, failed, pl_done, _pl_queued = every
    downloading.state = TaskState.DOWNLOADING
    downloading.progress = DownloadProgress(status='downloading', downloaded_bytes=318_000_000,
                                            total_bytes=512_000_000, speed=8_400_000, eta=23)
    downloading.percent = downloading.progress.percent or 0
    for done in (audio, finished, pl_done):
        done.state = TaskState.FINISHED
        done.percent = 100.0
        done.result = DownloadResult.classify(completed=1, total=1)
        done.filepath = f'{out}/{done.title}.mp4'
    failed.state = TaskState.ERROR
    failed.error_code = AppErrorCode.GEO_RESTRICTED
    failed.error = 'The uploader has not made this video available in your country'
    controller._active_id = downloading.id
    controller._refresh_state()
    window._refresh()


def _save(widget, path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    for _ in range(5):
        QApplication.processEvents()
    widget.grab().save(str(path))
    print(f'wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=ROOT / 'assets' / 'readme' / 'screenshots')
    parser.add_argument('--scale', type=float, default=2.0)
    args = parser.parse_args()

    _isolate(args.scale)
    sys.path.insert(0, str(ROOT))
    args.out.mkdir(parents=True, exist_ok=True)

    from PySide6.QtCore import QSettings

    from app import APP_NAME, ORG_NAME
    from app.application import create_application
    from app.core.models import FormatInfo, MediaInfo, SubtitleTrack
    from app.core.ytdlp_service import YtDlpService
    from app.gui.download_dialog import DownloadDialog
    from app.gui.main_window import MainWindow
    from app.gui.settings_dialog import SettingsDialog
    from app.i18n import TranslationManager
    from app.settings import SettingsStore
    from app.theme import ThemeManager

    app = create_application([sys.argv[0]])
    qt_settings = QSettings(ORG_NAME, APP_NAME)
    themes = ThemeManager(qt_settings)
    translations = TranslationManager(qt_settings)
    translations.set_language('en', persist=False)
    translations.apply(app)

    store = SettingsStore()
    settings = dataclasses.replace(store.load(), output_dir=DEMO_FOLDER)
    service = YtDlpService(settings)

    themes.set_theme('light', persist=False)
    themes.apply(app)
    window = MainWindow(settings, store, service, themes, translations)
    window.resize(1180, 600)
    window.show()
    _populate(window)

    _save(window, args.out / 'main-window-light.png')

    themes.set_theme('dark', persist=False)
    themes.apply(app)
    _save(window, args.out / 'main-window-dark.png')

    info = MediaInfo(
        url='https://example.com/watch/2', title=DEMO_VIDEOS[2][0], media_id='demo2',
        extractor='Generic', duration=DEMO_VIDEOS[2][2], uploader=DEMO_VIDEOS[2][1],
        thumbnail_url='demo://2',
        formats=(
            FormatInfo(format_id='401', ext='mp4', height=2160, width=3840, vcodec='av01', acodec='none',
                       filesize=1_210_000_000, fps=30),
            FormatInfo(format_id='137', ext='mp4', height=1080, width=1920, vcodec='avc1', acodec='none',
                       filesize=212_000_000, fps=30),
            FormatInfo(format_id='136', ext='mp4', height=720, width=1280, vcodec='avc1', acodec='none',
                       filesize=96_000_000, fps=30),
            FormatInfo(format_id='140', ext='m4a', vcodec='none', acodec='mp4a', abr=129,
                       filesize=13_700_000),
            FormatInfo(format_id='251', ext='webm', vcodec='none', acodec='opus', abr=135,
                       filesize=12_900_000),
        ),
        subtitles=(SubtitleTrack('en', 'English', automatic=False),
                   SubtitleTrack('de', 'German', automatic=True)),
    )
    themes.set_theme('light', persist=False)
    themes.apply(app)
    dialog = DownloadDialog(info, settings, window.thumbnails, ffmpeg_available=True, parent=window)
    dialog.show()
    _save(dialog, args.out / 'download-dialog.png')
    dialog.close()

    themes.set_theme('steel', persist=False)
    themes.apply(app)
    preferences = SettingsDialog(settings, themes, translations, parent=window)
    preferences.show()
    _save(preferences, args.out / 'preferences-steel.png')
    preferences.reject()

    window.shutdown()
    window.thumbnails.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
