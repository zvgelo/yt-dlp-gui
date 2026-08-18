"""User interface internationalisation.

Source strings in the code are English and wrapped in `tr()` / `translate()`.
Polish translations live in `translations/yt_dlp_gui_pl.ts`, compiled to `.qm`
by `scripts/build_translations.py`.

The `app/core` layer is language agnostic: it works with enums and error codes,
and only the GUI turns them into text (see `app/gui/labels.py`).
"""

from .languages import DEFAULT_LANGUAGE_CODE, ENGLISH, LANGUAGES, POLISH, Language, get_language
from .translation_manager import TranslationManager, active_language

__all__ = [
    'DEFAULT_LANGUAGE_CODE',
    'ENGLISH',
    'LANGUAGES',
    'POLISH',
    'Language',
    'TranslationManager',
    'active_language',
    'get_language',
]
