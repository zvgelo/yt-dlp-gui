"""Rendered checks for Light, Dark and Steel.

The colour tokens are tested in `test_theme.py`; this file renders real widgets
and looks at the pixels, which is the only way to catch a panel that ignores
the stylesheet, an icon that vanishes on one theme, or a label the layout
cannot fit.
"""

from __future__ import annotations

import itertools

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QAbstractButton, QApplication, QMenu, QWidget

from app.core.models import FormatInfo, MediaInfo
from app.gui import icons
from app.gui.download_dialog import DownloadDialog
from app.gui.media_info_widget import MediaInfoWidget
from app.gui.settings_dialog import SettingsDialog
from app.gui.top_bar import TopBar
from app.i18n import TranslationManager
from app.settings import AppSettings
from app.theme import THEMES, ThemeManager
from app.theme.color import to_color
from app.workers.thumbnail_worker import ThumbnailCache

#: Anything brighter than this in a dark theme is an unstyled panel
LIGHT_ISLAND = 0.35

ICON_NAMES = ('download', 'play', 'pause', 'cancel', 'retry', 'settings', 'folder',
              'language', 'theme', 'log', 'review', 'skip', 'check', 'video', 'audio',
              'playlist')


@pytest.fixture(scope='module')
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    return app


@pytest.fixture
def settings(tmp_path):
    return AppSettings(output_dir=str(tmp_path))


@pytest.fixture
def qt_settings():
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                     'yt-dlp-gui-tests', 'visual')


@pytest.fixture
def thumbnails():
    """Owned by Python for the whole test: the dialogs hold a plain reference."""
    cache = ThumbnailCache()
    yield cache
    cache.shutdown()


@pytest.fixture
def info():
    return MediaInfo(
        url='https://www.youtube.com/watch?v=NPmRmfodJmk', title='A sample track',
        media_id='NPmRmfodJmk', extractor='Youtube', duration=248.0, uploader='Author',
        formats=(FormatInfo(format_id='137', ext='mp4', height=1080, vcodec='avc1',
                            acodec='none', filesize=118_000_000, fps=60),
                 FormatInfo(format_id='140', ext='m4a', height=None, vcodec='none',
                            acodec='mp4a', filesize=4_000_000)))


def _luminance(color: QColor) -> float:
    channels = []
    for component in (color.redF(), color.greenF(), color.blueF()):
        channels.append(component / 12.92 if component <= 0.03928
                        else ((component + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _mean_luminance(widget: QWidget) -> float:
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    step = max(1, image.width() // 60)
    values = [_luminance(image.pixelColor(x, y))
              for y in range(0, image.height(), step)
              for x in range(0, image.width(), step)]
    return sum(values) / max(len(values), 1)


def _apply(qapp, qt_settings, key: str) -> ThemeManager:
    themes = ThemeManager(qt_settings)
    themes.set_theme(key, persist=False)
    themes.apply(qapp)
    return themes


# --------------------------------------------------------------------- icons


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_every_icon_is_visible_on_every_theme(qapp, qt_settings, theme):
    """An icon painted in the surface colour is an icon nobody can see."""
    _apply(qapp, qt_settings, theme.key)
    surface = _luminance(to_color(theme.surface))

    for name in ICON_NAMES:
        for size in (16, 24, 32):
            image = icons.pixmap(name, size).toImage().convertToFormat(
                QImage.Format.Format_ARGB32)
            visible = 0
            for y in range(image.height()):
                for x in range(image.width()):
                    color = image.pixelColor(x, y)
                    if color.alpha() < 40:
                        continue
                    lighter, darker = sorted((_luminance(color), surface), reverse=True)
                    if (lighter + 0.05) / (darker + 0.05) >= 1.6:
                        visible += 1
            assert visible >= 8, f'{name}@{size} is invisible on {theme.key}'


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_the_logo_renders_on_every_theme(qapp, qt_settings, theme):
    _apply(qapp, qt_settings, theme.key)
    logo = icons.app_logo(64)
    assert not logo.isNull()
    assert logo.toImage().convertToFormat(QImage.Format.Format_ARGB32).pixelColor(
        32, 20).alpha() > 0


def test_icons_are_repainted_after_a_theme_change(qapp, qt_settings):
    """The cache has to be dropped, or the old colours stay on screen."""
    _apply(qapp, qt_settings, 'light')
    light = icons.pixmap('settings', 24).toImage()
    _apply(qapp, qt_settings, 'dark')
    dark = icons.pixmap('settings', 24).toImage()
    assert light != dark


# ------------------------------------------------------------------ surfaces


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_widgets_follow_the_theme(qapp, qt_settings, settings, info, thumbnails, theme):
    """No light islands in a dark theme, no dark ones in Light."""
    _apply(qapp, qt_settings, theme.key)
    themes = ThemeManager(qt_settings)
    translations = TranslationManager(qt_settings)

    widgets = {
        'top bar': TopBar(settings),
        'download dialog': DownloadDialog(info, settings, thumbnails,
                                          ffmpeg_available=True),
        'preferences': SettingsDialog(settings, themes, translations),
    }
    menu = QMenu()
    menu.addAction('An action')
    menu.addAction('A disabled action').setEnabled(False)
    widgets['context menu'] = menu

    for label, widget in widgets.items():
        widget.show()
        qapp.processEvents()
        measured = _mean_luminance(widget)
        if theme.is_dark:
            assert measured < LIGHT_ISLAND, f'{label} stayed light on {theme.key}'
        else:
            assert measured > LIGHT_ISLAND, f'{label} stayed dark on {theme.key}'
        widget.close()


def test_switching_repaints_widgets_that_already_exist(qapp, qt_settings, settings):
    """The stylesheet is reapplied to live widgets, not only to new ones."""
    bar = TopBar(settings)
    bar.show()

    _apply(qapp, qt_settings, 'light')
    qapp.processEvents()
    light = _mean_luminance(bar)

    _apply(qapp, qt_settings, 'dark')
    qapp.processEvents()
    dark = _mean_luminance(bar)

    _apply(qapp, qt_settings, 'steel')
    qapp.processEvents()
    steel = _mean_luminance(bar)

    assert light > LIGHT_ISLAND
    assert dark < LIGHT_ISLAND
    assert steel < LIGHT_ISLAND
    # Steel is its own theme, so it must not render identically to Dark
    assert abs(steel - dark) > 0.002
    bar.close()


def test_a_dialog_opened_after_a_switch_uses_the_new_theme(qapp, qt_settings, settings,
                                                          info, thumbnails):
    _apply(qapp, qt_settings, 'light')
    _apply(qapp, qt_settings, 'dark')
    dialog = DownloadDialog(info, settings, thumbnails, ffmpeg_available=True)
    dialog.show()
    qapp.processEvents()
    assert _mean_luminance(dialog) < LIGHT_ISLAND
    dialog.close()


# ------------------------------------------------------------------ long text


@pytest.mark.parametrize('language', ['en', 'pl'])
def test_button_captions_fit_in_both_languages(qapp, qt_settings, settings, language):
    """Polish is longer than English; nothing may end up clipped."""
    translations = TranslationManager(qt_settings)
    translations.set_language(language, persist=False)
    bar = TopBar(settings)
    bar.resize(1000, 56)
    bar.show()
    qapp.processEvents()

    for button in bar.findChildren(QAbstractButton):
        if not button.text() or not button.isVisibleTo(bar):
            continue
        needed = button.fontMetrics().horizontalAdvance(button.text())
        assert needed <= button.width(), f'"{button.text()}" does not fit'
    bar.close()
    translations.set_language('en', persist=False)


def test_a_long_address_is_elided_rather_than_clipped(qapp, qt_settings, settings,
                                                     thumbnails):
    """The link shortens to the width it has and keeps the full URL usable."""
    _apply(qapp, qt_settings, 'dark')
    long_url = 'https://www.youtube.com/watch?v=NPmRmfodJmk&' + 'x' * 300
    info = MediaInfo(url=long_url, title='A sample track', media_id='NPmRmfodJmk',
                     extractor='Youtube', duration=248.0)
    dialog = DownloadDialog(info, settings, thumbnails, ffmpeg_available=True)
    dialog.resize(700, 560)
    dialog.show()
    qapp.processEvents()

    media = dialog.findChild(MediaInfoWidget)
    assert media is not None
    assert media._link.toolTip() == long_url
    assert long_url in media._link.text(), 'the full address must stay the link target'
    assert '…' in media._link.text() or len(media._url) < 60
    dialog.close()


# --------------------------------------------------------------------- layout


def test_the_top_bar_can_be_squeezed(qapp, settings):
    """A deep destination path must not dictate the width of the window.

    The bar used to demand more than 1200 pixels, which does not fit a 1366
    wide screen once the system scales it.
    """
    bar = TopBar(settings)
    bar.show()
    comfortable = bar.sizeHint().width()
    minimum = bar.minimumSizeHint().width()

    assert minimum < comfortable, 'the bar cannot give any ground'
    assert minimum <= 1060, f'the bar demands {minimum}px'

    bar.resize(minimum, bar.sizeHint().height())
    qapp.processEvents()
    widgets = sorted((w for w in (bar.paste_button, bar.kind_combo, bar.quality_combo,
                                  bar.container_combo, bar.dir_button, bar.settings_button)
                      if w.isVisible()), key=lambda w: w.x())
    for first, second in itertools.pairwise(widgets):
        assert first.x() + first.width() <= second.x(), 'controls overlap when squeezed'
    bar.close()


def test_a_deep_destination_path_is_shortened(qapp, settings):
    bar = TopBar(settings)
    bar.resize(900, 56)
    bar.show()
    qapp.processEvents()

    deep = '/home/someone/Media/Video/Downloads/YouTube/Music/Playlists/Favourites'
    bar.update_directory(deep)
    qapp.processEvents()

    assert bar.dir_button.toolTip() == deep
    needed = bar.dir_button.fontMetrics().horizontalAdvance(bar.dir_button.text())
    assert needed <= bar.dir_button.width() + 8, 'the folder name is clipped'
    bar.close()


# ---------------------------------------------------------------------- HiDPI


def test_thumbnails_are_rendered_at_the_screen_resolution(qapp):
    """A bitmap scaled up from logical pixels looks soft on a HiDPI screen."""
    from PySide6.QtGui import QPixmap

    from app.workers.thumbnail_worker import ThumbnailCache

    cache = ThumbnailCache()
    source = QPixmap(400, 300)
    source.fill(QColor('#336699'))
    cache._source['fake://thumb'] = source

    normal = cache.get('fake://thumb', 96, 54, 1.0)
    retina = cache.get('fake://thumb', 96, 54, 2.0)

    assert normal is not None and retina is not None
    # Same logical size, twice the pixels, and Qt is told about it
    assert normal.width() == 96
    assert retina.width() == 192
    assert retina.devicePixelRatio() == 2.0
    assert retina.size() / retina.devicePixelRatio() == normal.size()


def test_thumbnail_variants_are_cached_per_ratio(qapp):
    from PySide6.QtGui import QPixmap

    from app.workers.thumbnail_worker import ThumbnailCache

    cache = ThumbnailCache()
    source = QPixmap(400, 300)
    source.fill(QColor('#336699'))
    cache._source['fake://thumb'] = source

    cache.get('fake://thumb', 96, 54, 1.0)
    cache.get('fake://thumb', 96, 54, 2.0)
    assert len(cache._variants) == 2, 'one ratio must not evict the other'
