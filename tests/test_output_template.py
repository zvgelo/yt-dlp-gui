"""Tests for building output filenames, especially for playlists."""

from __future__ import annotations

import pytest

from app.core.models import DownloadRequest, MediaKind
from app.core.output_template import build_output_template
from app.core.ytdlp_service import YtDlpService
from app.settings import DEFAULT_OUTTMPL, AppSettings


@pytest.fixture
def service():
    return YtDlpService(AppSettings())


def _template(service, **kwargs) -> str:
    request = DownloadRequest(url='u', output_dir='/tmp', **kwargs)
    return service.download_options(request)['outtmpl']['default']


# ------------------------------------------------- sam builder szablonu


@pytest.mark.parametrize(('folder', 'numbered', 'expected'), [
    (True, True, '%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s'),
    (True, False, '%(playlist_title)s/%(title)s.%(ext)s'),
    (False, True, '%(playlist_index)03d - %(title)s.%(ext)s'),
    (False, False, '%(title)s.%(ext)s'),
])
def test_playlist_option_combinations(folder, numbered, expected):
    assert build_output_template(DEFAULT_OUTTMPL, is_playlist=True,
                                 create_folder=folder, numbered=numbered) == expected


def test_playlist_name_never_enters_the_filename():
    """The key rule: %(playlist_title)s only appears before a slash."""
    for folder in (True, False):
        for numbered in (True, False):
            template = build_output_template(DEFAULT_OUTTMPL, is_playlist=True,
                                             create_folder=folder, numbered=numbered)
            filename = template.rsplit('/', 1)[-1]
            assert '%(playlist_title)s' not in filename


def test_single_media_without_extras():
    assert build_output_template(DEFAULT_OUTTMPL, is_playlist=False) == DEFAULT_OUTTMPL
    # Playlist options must not affect single media items
    assert build_output_template(DEFAULT_OUTTMPL, is_playlist=False,
                                 create_folder=True, numbered=True) == DEFAULT_OUTTMPL


def test_custom_user_template_is_preserved():
    template = build_output_template('%(uploader)s - %(title)s.%(ext)s', is_playlist=True,
                                     create_folder=True, numbered=True)
    assert template == '%(playlist_title)s/%(playlist_index)03d - %(uploader)s - %(title)s.%(ext)s'


# --------------------------------------------------- integracja z serwisem


def test_numbering_enabled(service):
    template = _template(service, playlist_title='Best Songs 2026', playlist_index=1,
                         create_playlist_folder=True, number_playlist_files=True)
    assert template == '%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s'


def test_numbering_disabled(service):
    template = _template(service, playlist_title='Best Songs 2026', playlist_index=1,
                         create_playlist_folder=True, number_playlist_files=False)
    assert template == '%(playlist_title)s/%(title)s.%(ext)s'
    assert '%(playlist_index)' not in template


def test_numbering_works_the_same_for_audio(service):
    for numbered in (True, False):
        template = _template(service, kind=MediaKind.AUDIO, audio_format='mp3',
                             playlist_title='Lista', playlist_index=2,
                             create_playlist_folder=True, number_playlist_files=numbered)
        assert ('%(playlist_index)03d - ' in template) is numbered
        assert '%(playlist_title)s' not in template.rsplit('/', 1)[-1]


def test_the_option_is_a_snapshot_of_the_task(service):
    """Changing a global setting does not alter tasks that already exist."""
    request = DownloadRequest(url='u', output_dir='/tmp', playlist_title='Lista',
                              number_playlist_files=False)
    service.update_settings(service.settings.replace(number_playlist_files=True))
    assert '%(playlist_index)' not in service.download_options(request)['outtmpl']['default']


def test_numbering_is_enabled_by_default():
    assert AppSettings().number_playlist_files is True
    assert AppSettings().create_playlist_folder is True
    assert DownloadRequest(url='u', output_dir='/tmp').number_playlist_files is True
