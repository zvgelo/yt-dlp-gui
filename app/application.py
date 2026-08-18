"""Application start-up: QApplication, style, settings and main window."""

from __future__ import annotations

import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, APP_TITLE, ORG_NAME, __version__
from .core.ytdlp_service import YtDlpService
from .i18n import TranslationManager
from .settings import SettingsStore
from .theme import ThemeManager

#: Flags handled before Qt starts, so packaging scripts can query a build
VERSION_FLAGS = ('--version', '-V')
DIAGNOSTICS_FLAGS = ('--diagnostics',)
#: Builds the whole interface once and exits; how a release artifact is checked
SELF_TEST_FLAGS = ('--self-test',)
#: Release validation helpers, driven by scripts/validate_appimage.sh
CHECK_URL_FLAG = '--check-url'
CHECK_DOWNLOAD_FLAG = '--check-download'


def _missing_dependency() -> str:
    """Empty string when yt-dlp is available, otherwise a message for the user."""
    try:
        import yt_dlp
    except ImportError:
        return ('The yt-dlp library was not found.\n\n'
                'Install it with:\n    pip install yt-dlp')
    if not hasattr(yt_dlp, 'YoutubeDL'):
        return 'The installed yt-dlp library is incomplete.'
    return ''


def create_application(argv: list[str]) -> QApplication:
    # HiDPI scaling: Qt 6 does it by default, we only force crisp bitmaps
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORG_NAME)
    # Fusion is the only style that fully honours the palette and QSS on
    # every platform; without it dark themes break apart on the native
    # control decorations.
    app.setStyle('Fusion')
    return app


def _handle_query_flags(argv: list[str]) -> int | None:
    """Answer `--version` / `--diagnostics` without opening a window.

    Both are how a build script checks an artifact it just produced, so they
    must work with no display attached. Returns an exit code when the program
    should stop here, otherwise None.
    """
    arguments = argv[1:]
    flags = set(arguments)
    if flags & set(VERSION_FLAGS):
        print(f'{APP_TITLE} {__version__}')
        return 0
    if flags & set(DIAGNOSTICS_FLAGS):
        from .core.diagnostics import collect

        print(collect().as_text())
        return 0

    if CHECK_URL_FLAG in arguments:
        from .selfcheck import check_url

        return check_url(_value_after(arguments, CHECK_URL_FLAG),
                         verbose='--verbose' in arguments)
    if CHECK_DOWNLOAD_FLAG in arguments:
        from .selfcheck import check_download

        return check_download(_value_after(arguments, CHECK_DOWNLOAD_FLAG),
                              _value_after(arguments, '--output') or '.')
    return None


def _value_after(arguments: list[str], flag: str) -> str:
    index = arguments.index(flag) if flag in arguments else -1
    if index < 0 or index + 1 >= len(arguments):
        return ''
    return arguments[index + 1]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    code = _handle_query_flags(argv)
    if code is not None:
        return code

    app = create_application(argv)

    problem = _missing_dependency()
    if problem:
        QMessageBox.critical(None, APP_TITLE, problem)
        return 1

    from .gui.main_window import MainWindow

    store = SettingsStore()
    settings = store.load()
    service = YtDlpService(settings)

    from . import logs
    from .core.diagnostics import collect

    logs.setup(settings.verbose_log)
    logs.install_excepthook()
    logs.log_startup(collect(service.tools))

    # Theme and language are applied before the window is built so nothing
    # flashes in the default colours or in a foreign language
    qt_settings = QSettings(ORG_NAME, APP_NAME)
    theme_manager = ThemeManager(qt_settings)
    theme_manager.apply(app)

    translations = TranslationManager(qt_settings)
    translations.apply(app)

    from .gui import icons
    app.setWindowIcon(icons.app_icon())

    window = MainWindow(settings, store, service, theme_manager, translations)
    # A shutdown that does not go through the window (a signal, session
    # logout) must stop the download thread too, or the process hangs
    app.aboutToQuit.connect(window.shutdown)
    window.show()

    if set(argv[1:]) & set(SELF_TEST_FLAGS):
        return _self_test(app, window)

    urls = [arg for arg in argv[1:] if arg.startswith(('http://', 'https://'))]
    if urls:
        window.add_urls(urls)

    return app.exec()


def _self_test(app: QApplication, window) -> int:
    """Prove a packaged build can actually open its interface.

    Everything a release can get wrong without failing to import - a missing Qt
    platform plugin, an SVG that is not in the bundle, a stylesheet with no
    file behind it - shows up here, and it needs no display and no human.
    """
    from .core.diagnostics import collect
    from .gui.about_dialog import AboutDialog

    app.processEvents()
    # Built, not shown: it reads the licence file and the logo out of the
    # bundle, which is exactly the kind of thing a release can be missing
    about = AboutDialog(window, None)
    checks = {
        'window': window.isVisible(),
        'icons': not window.top_bar.brand.pixmap().isNull(),
        'stylesheet': bool(app.styleSheet()),
        'translations': bool(window.top_bar.paste_button.text()),
        'history': window.history.path.exists(),
        'about': bool(about.version_label.text()) and not about.logo.pixmap().isNull(),
    }
    about.deleteLater()
    diagnostics = collect(window._service.tools)
    for name, ok in checks.items():
        print(f'{name + ":":14} {"ok" if ok else "FAILED"}')
    print(f'{"ffmpeg:":14} {diagnostics.ffmpeg.state.value} ({diagnostics.ffmpeg.source.value})')
    print(f'{"js runtime:":14} {diagnostics.js_runtime.state.value} '
          f'({diagnostics.js_runtime.source.value})')

    window.shutdown()
    return 0 if all(checks.values()) else 1
