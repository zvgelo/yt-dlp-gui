"""Interface language management: translators, switching and persistence.

All `QTranslator` handling lives here; widgets never install translators
themselves, they only react to `QEvent.LanguageChange`.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QLibraryInfo, QLocale, QObject, QSettings, QTranslator, Signal
from PySide6.QtWidgets import QApplication

from ..resources import translations_dir
from .languages import DEFAULT_LANGUAGE_CODE, LANGUAGES, Language, get_language

#: QSettings key; sits next to appearance/theme but is fully independent of it
SETTINGS_KEY = 'appearance/language'

#: Compiled .qm catalogues
TRANSLATIONS_DIR = translations_dir()
CATALOG_PREFIX = 'yt_dlp_gui'

log = logging.getLogger(__name__)

#: Language currently installed in the application
_active: Language = get_language(DEFAULT_LANGUAGE_CODE)


def active_language() -> Language:
    return _active


class TranslationManager(QObject):
    """Available languages, current choice, translator installation and storage."""

    languageChanged = Signal(object)  # Language

    def __init__(self, settings: QSettings | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._settings = settings
        self._app_translator: QTranslator | None = None
        self._qt_translator: QTranslator | None = None
        self._language = get_language(self._stored_code() or self.detect_language_code())

    # ------------------------------------------------------------- access

    @property
    def languages(self) -> tuple[Language, ...]:
        return LANGUAGES

    @property
    def language(self) -> Language:
        return self._language

    @property
    def code(self) -> str:
        return self._language.code

    @staticmethod
    def detect_language_code() -> str:
        """System language, used until the user picks one."""
        system = QLocale.system().name()
        code = system.split('_')[0].lower()
        return code if code in {language.code for language in LANGUAGES} else DEFAULT_LANGUAGE_CODE

    # ------------------------------------------------------------ actions

    def set_language(self, code: str, *, persist: bool = True) -> bool:
        """Switch language at runtime. Returns False when nothing changed."""
        language = get_language(code)
        if language.code == self._language.code:
            return False

        self._language = language
        if persist:
            self._store_code(language.code)
        self.apply()
        return True

    def apply(self, app: QApplication | None = None) -> None:
        """Install the translators and notify every top-level window."""
        global _active
        _active = self._language

        app = app or QApplication.instance()
        if app is None:
            self.languageChanged.emit(self._language)
            return

        for translator in (self._app_translator, self._qt_translator):
            if translator is not None:
                app.removeTranslator(translator)
        self._app_translator = self._qt_translator = None

        # English gets a catalogue too: it carries the plural forms. Without
        # the file the source strings remain, which are English anyway.
        self._app_translator = self._install_app_catalog(app)
        self._qt_translator = self._install_qt_catalog(app)

        QLocale.setDefault(QLocale(self._language.locale))
        # Qt forwards the event to child widgets, which reload their texts
        app.sendEvent(app, QEvent(QEvent.Type.LanguageChange))
        for widget in app.topLevelWidgets():
            app.sendEvent(widget, QEvent(QEvent.Type.LanguageChange))
        self.languageChanged.emit(self._language)

    def _install_app_catalog(self, app: QApplication) -> QTranslator | None:
        path = TRANSLATIONS_DIR / f'{CATALOG_PREFIX}_{self._language.code}.qm'
        translator = QTranslator(app)
        if not path.exists():
            # A missing catalogue must not break the application; the
            # interface simply stays in the source language
            if self._language.code != DEFAULT_LANGUAGE_CODE:
                log.warning('Missing translation file %s; interface stays in English', path)
            return None
        if not translator.load(str(path)):
            log.warning('Could not load translations from %s', path)
            return None
        app.installTranslator(translator)
        return translator

    def _install_qt_catalog(self, app: QApplication) -> QTranslator | None:
        """Qt built-in translations for standard dialog buttons and file dialogs."""
        translator = QTranslator(app)
        directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(QLocale(self._language.locale), 'qtbase', '_', directory):
            app.installTranslator(translator)
            return translator
        return None

    # ------------------------------------------------------------ storage

    def persist(self) -> None:
        self._store_code(self._language.code)

    def _stored_code(self) -> str:
        if self._settings is None:
            return ''
        value = self._settings.value(SETTINGS_KEY, '')
        return str(value) if value else ''

    def _store_code(self, code: str) -> None:
        if self._settings is not None:
            self._settings.setValue(SETTINGS_KEY, code)
            self._settings.sync()
