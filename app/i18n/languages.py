"""Available interface languages.

Language names are given in their own language ("Polski", "English") and are
never translated: a user must recognise their language even when the
application currently speaks a foreign one.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Language:
    code: str  # stable identifier stored in settings
    native_name: str  # name in that language; never translated
    locale: str  # Qt locale, used for plural forms and number formats


ENGLISH = Language(code='en', native_name='English', locale='en_US')
POLISH = Language(code='pl', native_name='Polski', locale='pl_PL')

#: Order matches the selector in preferences
LANGUAGES: tuple[Language, ...] = (ENGLISH, POLISH)

LANGUAGES_BY_CODE: dict[str, Language] = {language.code: language for language in LANGUAGES}

#: Source strings in the code are English, so this is the fallback language:
#: with no .qm catalogue the interface stays consistent.
DEFAULT_LANGUAGE_CODE = 'en'


def get_language(code: str) -> Language:
    """Language for the given code, falling back to the default."""
    return LANGUAGES_BY_CODE.get((code or '').split('_')[0].lower(),
                                 LANGUAGES_BY_CODE[DEFAULT_LANGUAGE_CODE])
