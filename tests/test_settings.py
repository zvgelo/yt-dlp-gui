"""Tests for settings persistence (QSettings)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from app.settings import AppSettings, SettingsStore


@pytest.fixture
def store(tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         'yt-dlp-gui-test', 'yt-dlp-gui-test')
    settings.clear()
    return SettingsStore(settings)


def test_defaults_when_empty(store):
    settings = store.load()
    assert settings.kind == 'video'
    assert settings.video_container == 'mp4'
    assert settings.embed_metadata is True


def test_save_and_load(store):
    original = AppSettings(
        output_dir='/tmp/moje',
        kind='audio',
        quality=1080,
        audio_format='flac',
        embed_thumbnail=False,
        concurrent_fragments=8,
        subtitle_languages='pl,de',
        sponsorblock_remove='sponsor,intro',
    )
    store.save(original)
    loaded = store.load()

    assert loaded.output_dir == '/tmp/moje'
    assert loaded.kind == 'audio'
    assert loaded.quality == 1080
    assert loaded.audio_format == 'flac'
    assert loaded.concurrent_fragments == 8
    assert loaded.subtitle_languages == 'pl,de'


def test_boolean_values_come_back_as_bool(store):
    """QSettings in INI format returns everything as text, so we must coerce."""
    store.save(AppSettings(embed_thumbnail=False, write_subtitles=True, autostart=False))
    loaded = store.load()

    assert loaded.embed_thumbnail is False
    assert loaded.write_subtitles is True
    assert loaded.autostart is False


def test_corrupt_value_does_not_crash(store):
    store.save(AppSettings())
    store._settings.setValue('app/concurrent_fragments', 'nie-liczba')
    # Instead of raising we fall back to the default value
    assert store.load().concurrent_fragments == AppSettings().concurrent_fragments


def test_helper_properties():
    settings = AppSettings(subtitle_languages=' pl , en ,', sponsorblock_remove='sponsor, intro')
    assert settings.subtitle_language_list == ('pl', 'en')
    assert settings.sponsorblock_categories == frozenset({'sponsor', 'intro'})
    assert AppSettings(subtitle_languages='').subtitle_language_list == ('en',)


def test_replace_does_not_mutate_the_original():
    original = AppSettings()
    changed = original.replace(kind='audio')
    assert original.kind == 'video'
    assert changed.kind == 'audio'
