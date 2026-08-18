"""Tests for the theme system: model, QSS rendering, switching and persistence."""

from __future__ import annotations

import dataclasses

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from app.theme import DEFAULT_THEME_KEY, THEMES, Theme, ThemeManager, active_theme, get_theme
from app.theme.color import to_color
from app.theme.theme_manager import SETTINGS_KEY, build_palette


@pytest.fixture(scope='module')
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def manager(tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         'yt-dlp-gui-test', 'themes')
    settings.clear()
    return ThemeManager(settings)


# --------------------------------------------------------------- definicje


def test_there_are_three_themes():
    assert [theme.key for theme in THEMES] == ['light', 'dark', 'steel']


def test_every_theme_defines_all_colours():
    for theme in THEMES:
        for field in dataclasses.fields(Theme):
            value = getattr(theme, field.name)
            if field.name in ('key', 'name') or isinstance(value, bool):
                continue
            assert value, f'{theme.key}: no value for {field.name}'
            assert to_color(value).isValid(), f'{theme.key}: {field.name}={value!r} nie jest kolorem'


def test_steel_differs_from_dark():
    dark, steel = get_theme('dark'), get_theme('steel')
    differences = [
        f.name for f in dataclasses.fields(Theme)
        if f.name not in ('key', 'name') and getattr(dark, f.name) != getattr(steel, f.name)
    ]
    # Steel is meant to be its own theme, not a shade of Dark
    assert len(differences) > 20
    assert dark.accent != steel.accent
    assert steel.is_dark and dark.is_dark


def test_an_unknown_key_yields_the_default():
    assert get_theme('nie-ma-takiego').key == DEFAULT_THEME_KEY


# ----------------------------------------------------------------- render


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_qss_leaves_no_tokens_behind(theme):
    qss = ThemeManager.render(theme)
    assert '{{' not in qss
    assert len(qss) > 1000


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_qss_contains_the_theme_colours(theme):
    qss = ThemeManager.render(theme)
    assert theme.background in qss
    assert theme.accent in qss
    assert theme.text_primary in qss


def test_a_template_with_an_unknown_token_is_detected():
    from app.theme.theme_manager import UnresolvedTokensError

    with pytest.raises(UnresolvedTokensError):
        ThemeManager.render(get_theme('dark'), 'QWidget { color: {{NIE_ISTNIEJE}}; }')


# ---------------------------------------------------------------- switching


def test_switching_without_a_restart(qapp, manager):
    manager.apply(qapp)
    for key in ('light', 'dark', 'steel', 'light'):
        manager.set_theme(key)
        assert manager.key == key
        assert active_theme().key == key
        assert manager.theme.background in qapp.styleSheet()


def test_set_theme_returns_false_when_nothing_changes(manager):
    manager.set_theme('steel')
    assert manager.set_theme('steel') is False


def test_change_signal(qapp, manager):
    widziane = []
    manager.themeChanged.connect(lambda theme: widziane.append(theme.key))
    manager.set_theme('light')
    manager.set_theme('steel')
    assert widziane == ['light', 'steel']


def test_the_preview_does_not_persist(manager):
    manager.set_theme('steel', persist=True)
    manager.set_theme('light', persist=False)
    # Still steel on disk, so Cancel in preferences can restore the previous one
    assert manager._settings.value(SETTINGS_KEY) == 'steel'


# ----------------------------------------------------------------- zapis


def test_the_theme_survives_a_restart(tmp_path, qapp):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    def new_settings():
        return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         'yt-dlp-gui-test', 'persist')

    first = ThemeManager(new_settings())
    first.set_theme('steel')

    # Nowa instancja = kolejne uruchomienie aplikacji
    second = ThemeManager(new_settings())
    assert second.key == 'steel'


def test_default_theme_without_a_stored_setting(tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         'yt-dlp-gui-test', 'pusty')
    settings.clear()
    assert ThemeManager(settings).key == DEFAULT_THEME_KEY


# ---------------------------------------------------------------- paleta


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_the_palette_mirrors_the_theme(qapp, theme):
    from PySide6.QtGui import QPalette

    palette = build_palette(theme)
    assert palette.color(QPalette.ColorRole.Window) == QColor(theme.background)
    assert palette.color(QPalette.ColorRole.Base) == QColor(theme.surface)
    assert palette.color(QPalette.ColorRole.WindowText) == QColor(theme.text_primary)
    assert palette.color(QPalette.ColorGroup.Disabled,
                         QPalette.ColorRole.Text) == QColor(theme.text_disabled)


# -------------------------------------------------------------- readability


def _contrast(first: str, second: str) -> float:
    def luminance(value: str) -> float:
        color = to_color(value)
        channels = []
        for component in (color.redF(), color.greenF(), color.blueF()):
            channels.append(component / 12.92 if component <= 0.03928
                            else ((component + 0.055) / 1.055) ** 2.4)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_text_is_readable(theme):
    """Primary text must meet WCAG AA (4.5:1) on both surfaces."""
    assert _contrast(theme.text_primary, theme.surface) >= 4.5
    assert _contrast(theme.text_primary, theme.background) >= 4.5
    assert _contrast(theme.text_primary, theme.log_background) >= 4.5
    assert _contrast(theme.tooltip_text, theme.tooltip_background) >= 4.5


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_secondary_text_and_statuses_are_visible(theme):
    """Secondary text and statuses: the 3:1 threshold for large or bold text."""
    assert _contrast(theme.text_secondary, theme.surface) >= 3.0
    assert _contrast(theme.text_disabled, theme.surface) >= 2.0
    for status in (theme.success, theme.warning, theme.error, theme.info, theme.link):
        assert _contrast(status, theme.surface) >= 3.0
    assert _contrast(theme.text_on_accent, theme.accent) >= 3.0


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_borders_and_surfaces_are_distinguishable(theme):
    """Frames and hover states must not blend into the background."""
    assert _contrast(theme.border, theme.surface) >= 1.08
    assert _contrast(theme.border_strong, theme.surface) >= 1.15
    assert theme.surface_hover != theme.surface
    assert theme.surface_active != theme.surface_hover
    assert _contrast(theme.scrollbar, theme.surface) >= 1.15


# ------------------------------------------------------------- theme audit


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_focus_is_visible_and_distinct(theme):
    """Focus must stand out from the background without mimicking hover."""
    assert _contrast(theme.focus, theme.surface) >= 2.5
    assert _contrast(theme.focus, theme.background) >= 2.0
    # A focus ring that matches hover or the disabled surface says nothing
    assert theme.focus != theme.surface_hover
    assert theme.focus != theme.surface_active
    assert theme.focus != theme.border


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_a_selected_row_stays_readable(theme):
    """`accent_soft` is the background of a selected card."""
    assert _contrast(theme.text_primary, theme.accent_soft) >= 4.5
    assert _contrast(theme.text_secondary, theme.accent_soft) >= 2.5
    assert theme.accent_soft != theme.surface_hover


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_menus_tooltips_and_progress_are_readable(theme):
    assert _contrast(theme.text_primary, theme.menu_background) >= 4.5
    assert _contrast(theme.tooltip_text, theme.tooltip_background) >= 4.5
    # The tooltip must not melt into the surface behind it
    assert _contrast(theme.tooltip_background, theme.surface) >= 1.3
    # Progress: the filled part against the track, and the label over both
    assert _contrast(theme.accent, theme.progress_track) >= 1.5
    assert _contrast(theme.text_primary, theme.progress_track) >= 4.5
    assert _contrast(theme.text_on_accent, theme.accent) >= 3.0


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_thumbnail_overlays_are_readable(theme):
    """The duration badge is drawn over an unknown image, hence the scrim."""
    assert _contrast(theme.overlay_text, '#000000') >= 4.5
    assert _contrast(theme.text_secondary, theme.placeholder_background) >= 2.5


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_disabled_controls_read_as_disabled_but_stay_legible(theme):
    """Clearly inactive, still readable: below the active text, above noise."""
    disabled = _contrast(theme.text_disabled, theme.surface)
    primary = _contrast(theme.text_primary, theme.surface)
    assert 2.0 <= disabled < primary
    assert _contrast(theme.text_disabled, theme.surface_secondary) >= 1.9


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_surface_levels_are_told_apart(theme):
    """Cards, toolbars and the window must not merge into one flat area."""
    levels = (theme.background, theme.surface, theme.surface_secondary)
    assert len(set(levels)) == 3
    assert _contrast(theme.surface, theme.background) >= 1.03


def test_dark_themes_avoid_pure_black_and_pure_white():
    for theme in (get_theme('dark'), get_theme('steel')):
        assert theme.background.lower() not in ('#000000', '#000')
        assert theme.surface.lower() not in ('#000000', '#000')
        # Pure white text on a dark surface glares; keep it slightly muted
        assert theme.text_primary.lower() not in ('#ffffff', '#fff')


def test_steel_is_cooler_than_dark():
    """Steel must stay its own theme, not a slightly different Dark."""
    dark, steel = get_theme('dark'), get_theme('steel')
    for field in ('background', 'surface', 'surface_secondary'):
        dark_color = to_color(getattr(dark, field))
        steel_color = to_color(getattr(steel, field))
        # Cooler means more blue than red
        assert steel_color.blue() - steel_color.red() > dark_color.blue() - dark_color.red()
    # Steel draws stronger borders than Dark
    assert _contrast(steel.border, steel.surface) > _contrast(dark.border, dark.surface)
    assert steel.accent != dark.accent


@pytest.mark.parametrize('theme', THEMES, ids=lambda t: t.key)
def test_every_task_state_has_a_readable_colour(theme):
    """The status column is painted by hand, so it needs its own check."""
    from app.gui.card_delegate import state_color
    from app.state import TaskState

    for state in TaskState:
        color = state_color(theme, state)
        assert color, f'{state} has no colour'
        assert _contrast(color, theme.surface) >= 3.0, f'{state} is hard to read'


def test_status_colours_come_from_the_theme_only():
    """No widget may invent a colour of its own."""
    import re
    from pathlib import Path

    literal = re.compile(r"['\"]#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})['\"]")
    offenders = []
    for path in sorted(Path('app/gui').rglob('*.py')):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if literal.search(line) and 'noqa' not in line:
                offenders.append(f'{path}:{number}: {line.strip()}')
    assert offenders == [], 'hard-coded colours outside the theme system'
