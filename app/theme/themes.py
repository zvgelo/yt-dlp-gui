"""The three bundled themes: Light, Dark and Steel."""

from __future__ import annotations

from .theme import Theme

#: Light: neutral surfaces, high text contrast, green accent.
LIGHT = Theme(
    key='light',
    name='Light',
    is_dark=False,

    background='#f5f6f8',
    surface='#ffffff',
    surface_secondary='#eceff3',
    surface_hover='#e8ecf1',
    surface_active='#dde3ea',

    border='#d6dae1',
    border_strong='#bfc6cf',
    separator='#e4e7ec',

    text_primary='#20242a',
    text_secondary='#69707a',
    text_disabled='#a2a8b0',
    text_on_accent='#ffffff',
    link='#1a73e8',

    accent='#43a047',
    accent_hover='#4caf50',
    accent_pressed='#388e3c',
    accent_soft='#e4f3e6',
    focus='#43a047',

    success='#2e9e52',
    warning='#b86e00',
    error='#d93025',
    info='#1a73e8',

    progress_track='#dee3e9',
    scrollbar='#c7cdd6',
    scrollbar_hover='#a2a8b0',
    tooltip_background='#2b3138',
    tooltip_text='#f5f6f8',
    menu_background='#ffffff',
    log_background='#fbfcfd',
    placeholder_background='#dfe4ea',
    overlay_scrim='rgba(0, 0, 0, 165)',
    overlay_text='#ffffff',
)

#: Dark: several graphite levels, no pure black, restrained contrast.
DARK = Theme(
    key='dark',
    name='Dark',
    is_dark=True,

    background='#16181c',
    surface='#1e2126',
    surface_secondary='#282c32',
    surface_hover='#2c3138',
    surface_active='#343a42',

    border='#343941',
    border_strong='#464d57',
    separator='#262a30',

    text_primary='#f2f3f5',
    text_secondary='#a7adb5',
    text_disabled='#656b73',
    text_on_accent='#0e1013',
    link='#6fa8f5',

    accent='#4caf50',
    accent_hover='#5cc061',
    accent_pressed='#3d9440',
    accent_soft='#22321f',
    focus='#4caf50',

    success='#4caf50',
    warning='#e8a33d',
    error='#ef5350',
    info='#6fa8f5',

    progress_track='#2e333a',
    scrollbar='#3a4048',
    scrollbar_hover='#4e5560',
    tooltip_background='#343a42',
    tooltip_text='#f2f3f5',
    menu_background='#22262c',
    log_background='#131519',
    placeholder_background='#2b3037',
    overlay_scrim='rgba(0, 0, 0, 175)',
    overlay_text='#ffffff',
)

#: Steel: cool blue-tinted greys, stronger borders than Dark and a
#: steel-blue accent, so it reads as a distinct theme rather than a variant.
STEEL = Theme(
    key='steel',
    name='Steel',
    is_dark=True,

    background='#20262b',
    surface='#293137',
    surface_secondary='#333d44',
    surface_hover='#3a464e',
    surface_active='#43525b',

    border='#4a5963',
    border_strong='#5d6e79',
    separator='#37424a',

    text_primary='#e7edf1',
    text_secondary='#aebac2',
    text_disabled='#717d85',
    text_on_accent='#0f1a20',
    link='#8fc0da',

    accent='#5f8fa8',
    accent_hover='#73a6c0',
    accent_pressed='#4e7a90',
    accent_soft='#2f4653',
    focus='#73a6c0',

    success='#5fa987',
    warning='#c8933f',
    error='#c9635e',
    info='#5f8fa8',

    progress_track='#37424a',
    scrollbar='#4a5963',
    scrollbar_hover='#5d6e79',
    tooltip_background='#3a464f',
    tooltip_text='#e7edf1',
    menu_background='#2c353b',
    log_background='#1b2126',
    placeholder_background='#39444c',
    overlay_scrim='rgba(0, 0, 0, 170)',
    overlay_text='#ffffff',
)

#: Order used by the theme selector in preferences.
THEMES: tuple[Theme, ...] = (LIGHT, DARK, STEEL)

THEMES_BY_KEY: dict[str, Theme] = {theme.key: theme for theme in THEMES}

DEFAULT_THEME_KEY = 'dark'


def get_theme(key: str) -> Theme:
    """Theme for the given key, falling back to the default."""
    return THEMES_BY_KEY.get(key, THEMES_BY_KEY[DEFAULT_THEME_KEY])
