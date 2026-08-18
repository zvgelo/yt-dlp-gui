"""The About box: what it claims, in both languages and on every theme.

The version it shows is the one thing a user quotes in a bug report, so it is
checked against the single source of truth rather than against a literal.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from app import APP_TITLE, LICENSE_NAME, PROJECT_URL, __version__
from app.gui.about_dialog import AboutDialog
from app.i18n import TranslationManager
from app.theme import THEMES, ThemeManager


@pytest.fixture(scope='module')
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    return app


@pytest.fixture
def qt_settings(tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         'yt-dlp-gui-tests', 'about')
    settings.clear()
    return settings


@pytest.fixture
def themes(qapp, qt_settings):
    manager = ThemeManager(qt_settings)
    manager.apply(qapp)
    return manager


@pytest.fixture
def dialog(qapp, themes):
    box = AboutDialog(None, themes)
    yield box
    box.deleteLater()


# ------------------------------------------------------------------ content


def test_it_constructs_and_names_the_application(dialog):
    assert dialog.name_label.text() == APP_TITLE
    assert APP_TITLE in dialog.windowTitle()


def test_it_shows_the_current_version(dialog):
    """The one string a bug report quotes; never a literal in two places."""
    assert __version__ in dialog.version_label.text()


def test_the_version_is_not_a_development_placeholder():
    assert not any(mark in __version__ for mark in ('a', 'b', 'rc', 'dev'))


def test_it_describes_what_the_application_is(dialog):
    assert 'yt-dlp' in dialog.description_label.text()


def test_it_lists_the_components_it_is_built_from(dialog):
    """Every row carries a value: a version, or a stated absence."""
    assert set(dialog._value_labels) == {'yt-dlp', 'FFmpeg', 'Deno', 'PySide6', 'Python'}
    for name, label in dialog._value_labels.items():
        assert label.text(), name


def test_the_python_and_qt_rows_report_the_running_interpreter(dialog):
    import sys

    from PySide6 import __version__ as pyside_version

    assert dialog._value_labels['Python'].text() == sys.version.split()[0]
    assert pyside_version in dialog._value_labels['PySide6'].text()


def test_it_reuses_the_cached_diagnostics(dialog, monkeypatch):
    """Opening the box must not run ffmpeg and deno all over again.

    The dialog reads `diagnostics.collect()`, which caches the resolved tools;
    running a helper binary on every open would make the About box the slowest
    thing in the interface.
    """
    from app.core import runtime_tools

    monkeypatch.setattr(runtime_tools, '_run_version',
                        lambda *args, **kwargs: pytest.fail('probed again'))
    AboutDialog(None).deleteLater()


# --------------------------------------------------------------- repository


def test_the_repository_link_comes_from_project_metadata(dialog):
    assert PROJECT_URL in dialog.repository_label.text()
    assert f'href="{PROJECT_URL}"' in dialog.repository_label.text()


def test_the_repository_url_is_a_single_source_of_truth():
    """Nothing may repeat the address; it is read from `app/__init__.py`."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    hardcoded = []
    for path in (root / 'app').rglob('*.py'):
        if path.name == '__init__.py' and path.parent.name == 'app':
            continue
        if PROJECT_URL in path.read_text(encoding='utf-8'):
            hardcoded.append(str(path))
    assert not hardcoded


def test_the_link_is_painted_in_the_theme_accent(qapp, qt_settings):
    """Qt's default blue is not one of our tokens."""
    from app.theme import ThemeManager, active_theme

    themes = ThemeManager(qt_settings)
    themes.set_theme('steel', persist=False)
    themes.apply(qapp)
    box = AboutDialog(None, themes)
    assert f'color: {active_theme().accent}' in box.repository_label.text()
    box.deleteLater()


def test_the_package_metadata_names_the_same_repository():
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text()
    assert f'Repository = "{PROJECT_URL}"' in pyproject


def test_the_repository_link_is_reachable_from_the_keyboard(dialog):
    flags = dialog.repository_label.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.LinksAccessibleByKeyboard
    assert dialog.repository_label.focusPolicy() != Qt.FocusPolicy.NoFocus


# ------------------------------------------------------------------ licence


def test_it_states_the_licence(dialog):
    assert LICENSE_NAME in dialog.license_label.text()


def test_the_licence_text_comes_from_the_build(dialog):
    """`View licence` shows the file that ships, not a remembered text."""
    dialog._toggle_license()
    assert dialog.license_view.isVisibleTo(dialog)
    assert 'public domain' in dialog.license_view.toPlainText()
    assert 'Hide' in dialog.license_button.text()
    dialog._toggle_license()
    assert not dialog.license_view.isVisibleTo(dialog)


# -------------------------------------------------------------- interaction


def test_close_accepts_the_dialog(dialog):
    assert dialog.buttons.buttonRole(dialog.close_button) == \
        QDialogButtonBox.ButtonRole.AcceptRole
    dialog.close_button.click()
    assert not dialog.isVisible()


def test_escape_closes_the_dialog(qapp, themes):
    from PySide6.QtGui import QKeyEvent

    box = AboutDialog(None, themes)
    box.show()
    qapp.processEvents()
    box.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                Qt.KeyboardModifier.NoModifier))
    qapp.processEvents()
    assert not box.isVisible()
    box.deleteLater()


def test_every_focusable_control_has_a_name(dialog):
    from PySide6.QtWidgets import QWidget

    for child in dialog.findChildren(QWidget):
        if child.focusPolicy() == Qt.FocusPolicy.NoFocus or not child.isEnabled():
            continue
        name = child.accessibleName() or getattr(child, 'text', lambda: '')()
        assert name, child.objectName() or type(child).__name__


# ---------------------------------------------------------------- languages


@pytest.mark.parametrize('code', ['en', 'pl'])
def test_it_speaks_both_languages(qapp, qt_settings, themes, code):
    translations = TranslationManager(qt_settings)
    translations.set_language(code, persist=False)
    translations.apply(qapp)
    try:
        box = AboutDialog(None, themes)
        qapp.processEvents()
        title = box.windowTitle()
        assert APP_TITLE in title
        if code == 'pl':
            assert 'O programie' in title
            assert 'Wersja' in box.version_label.text()
            assert 'Graficzny' in box.description_label.text()
        else:
            assert 'About' in title
            assert 'Version' in box.version_label.text()
        box.deleteLater()
    finally:
        translations.set_language('en', persist=False)
        translations.apply(qapp)


# ------------------------------------------------------------------- themes


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_it_renders_on_every_theme(qapp, qt_settings, theme):
    """Constructed and painted under each theme: no unstyled white island."""
    themes = ThemeManager(qt_settings)
    themes.set_theme(theme.key, persist=False)
    themes.apply(qapp)

    box = AboutDialog(None, themes)
    box.resize(520, 420)
    image = box.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    assert image.width() > 0 and image.height() > 0
    assert not box.logo.pixmap().isNull()
    box.deleteLater()


def test_a_theme_change_repaints_the_logo(qapp, qt_settings):
    themes = ThemeManager(qt_settings)
    themes.set_theme('light', persist=False)
    themes.apply(qapp)
    box = AboutDialog(None, themes)
    light = box.logo.pixmap().toImage()

    themes.set_theme('dark', persist=False)
    themes.apply(qapp)
    qapp.processEvents()
    assert box.logo.pixmap().toImage() != light
    box.deleteLater()
