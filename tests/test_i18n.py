"""Internationalisation tests: catalogues, switching and theme independence."""

from __future__ import annotations

import ast
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.i18n import DEFAULT_LANGUAGE_CODE, LANGUAGES, TranslationManager, get_language
from app.i18n.translation_manager import SETTINGS_KEY, TRANSLATIONS_DIR
from app.theme import ThemeManager

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def manager(tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         'yt-dlp-gui-test', 'i18n')
    settings.clear()
    return TranslationManager(settings)


# --------------------------------------------------------------- languages


def test_available_languages():
    assert [language.code for language in LANGUAGES] == ['en', 'pl']


def test_language_names_are_native():
    """A user must recognise their language whatever the interface speaks."""
    assert get_language('pl').native_name == 'Polski'
    assert get_language('en').native_name == 'English'


def test_an_unknown_code_yields_the_fallback():
    assert get_language('de').code == DEFAULT_LANGUAGE_CODE
    assert get_language('').code == DEFAULT_LANGUAGE_CODE
    # A full locale must work too
    assert get_language('pl_PL').code == 'pl'


# ------------------------------------------------------------- katalogi


@pytest.mark.parametrize('code', ['pl', 'en'])
def test_the_catalogues_are_compiled(code):
    assert (TRANSLATIONS_DIR / f'yt_dlp_gui_{code}.qm').exists(), \
        'uruchom scripts/build_translations.py'


def test_the_polish_catalogue_is_complete():
    """Every source string needs a translation, or the UI ends up mixed."""
    tree = ET.parse(TRANSLATIONS_DIR / 'yt_dlp_gui_pl.ts')
    unfinished = []
    for context in tree.getroot().findall('context'):
        for message in context.findall('message'):
            node = message.find('translation')
            if node.get('type') == 'unfinished':
                unfinished.append((context.findtext('name'), message.findtext('source')))
    assert unfinished == []


def test_texts_have_named_contexts():
    """An unnamed context means lupdate did not recognise the call."""
    tree = ET.parse(TRANSLATIONS_DIR / 'yt_dlp_gui_pl.ts')
    names = [context.findtext('name') for context in tree.getroot().findall('context')]
    assert all(names)
    assert 'Labels' in names


def test_plurals_have_three_forms():
    """Polish needs three forms; two would inflect the word incorrectly."""
    tree = ET.parse(TRANSLATIONS_DIR / 'yt_dlp_gui_pl.ts')
    found = 0
    for context in tree.getroot().findall('context'):
        for message in context.findall('message'):
            if message.get('numerus') == 'yes':
                forms = message.find('translation').findall('numerusform')
                assert len(forms) == 3, message.findtext('source')
                found += 1
    assert found >= 3


# ------------------------------------------------------------ switching


def test_switching_without_a_restart(qapp, manager):
    from app.gui import labels

    manager.set_language('en')
    manager.apply(qapp)
    assert labels.task_state_label(_state()) == 'Downloading'

    manager.set_language('pl')
    assert labels.task_state_label(_state()) == 'Pobieranie'

    manager.set_language('en')
    assert labels.task_state_label(_state()) == 'Downloading'


def _state():
    from app.state import TaskState
    return TaskState.DOWNLOADING


def test_polish_plurals(qapp, manager):
    from app.gui import labels

    manager.set_language('pl')
    manager.apply(qapp)
    assert labels.items_count(1) == '1 pozycja'
    assert labels.items_count(3) == '3 pozycje'
    assert labels.items_count(5) == '5 pozycji'


def test_english_plurals(qapp, manager):
    from app.gui import labels

    manager.set_language('en')
    manager.apply(qapp)
    assert labels.items_count(1) == '1 item'
    assert labels.items_count(3) == '3 items'


def test_set_language_returns_false_without_a_change(manager):
    manager.set_language('pl')
    assert manager.set_language('pl') is False


def test_change_signal(qapp, manager):
    widziane = []
    manager.languageChanged.connect(lambda language: widziane.append(language.code))
    manager.set_language('pl')
    manager.set_language('en')
    assert widziane == ['pl', 'en']


# -------------------------------------------------------------- zapis


def test_the_language_survives_a_restart(tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    def new_settings():
        return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         'yt-dlp-gui-test', 'i18n-persist')

    first = TranslationManager(new_settings())
    first.set_language('pl')
    assert TranslationManager(new_settings()).code == 'pl'


def test_the_preview_does_not_persist(manager):
    manager.set_language('pl', persist=True)
    manager.set_language('en', persist=False)
    assert manager._settings.value(SETTINGS_KEY) == 'pl'


def test_we_store_the_code_not_the_name(manager):
    manager.set_language('pl')
    assert manager._settings.value(SETTINGS_KEY) == 'pl'
    assert manager._settings.value(SETTINGS_KEY) != 'Polski'


# ---------------------------------------------------- theme independence


def test_theme_and_language_are_independent(qapp, tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         'yt-dlp-gui-test', 'combo')
    settings.clear()

    themes = ThemeManager(settings)
    translations = TranslationManager(settings)
    themes.apply(qapp)
    translations.set_language('pl')
    themes.set_theme('steel')

    assert translations.code == 'pl'
    assert themes.key == 'steel'

    translations.set_language('en')
    assert themes.key == 'steel'  # changing the language left the theme alone

    themes.set_theme('light')
    assert translations.code == 'en'  # changing the theme left the language alone


# ------------------------------------------------- extraction completeness

def _sources_in_catalog() -> set[str]:
    tree = ET.parse(TRANSLATIONS_DIR / 'yt_dlp_gui_pl.ts')
    return {message.findtext('source')
            for context in tree.getroot().findall('context')
            for message in context.findall('message')}


def _literals_in_code() -> dict[str, str]:
    """The texts passed to tr()/translate() in the code, with their file.

    We parse the AST rather than use regular expressions: implicitly joined
    literals (`'a' 'b'`) are then one string, exactly as lupdate sees them.
    """
    found: dict[str, str] = {}
    for path in sorted((ROOT / 'app').rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            text = _translated_literal(node)
            if text:
                found.setdefault(text, str(path.relative_to(ROOT)))
    return found


def _translated_literal(node: ast.Call) -> str | None:
    """Return the source string when the call is tr()/translate()."""
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')
    if name == 'tr':
        index = 0  # self.tr('tekst')
    elif name == 'translate':
        index = 1  # translate('Kontekst', 'tekst')
    else:
        return None

    if len(node.args) <= index:
        return None
    argument = node.args[index]
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    return None


def test_every_text_in_the_code_is_in_the_catalogue():
    """Guards against a text lupdate missed, which would stay in English.

    A plural called inside another function argument was once lost that way.
    """
    catalog = _sources_in_catalog()
    missing = {text: path for text, path in _literals_in_code().items()
               if text not in catalog}
    assert missing == {}, f'texts missing from the translation catalogue: {missing}'


def test_plurals_work_in_both_languages(qapp, manager):
    from app.gui import labels

    manager.set_language('pl')
    manager.apply(qapp)
    assert labels.attempts_count(1) == 'Prób: 1'
    assert labels.attempts_count(2) == 'Próby: 2'

    manager.set_language('en')
    assert labels.attempts_count(1) == 'Attempt: 1'
    assert labels.attempts_count(2) == 'Attempts: 2'
