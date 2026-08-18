"""Regression tests for URL intent classification and normalisation.

A link copied while a video plays inside a playlist or a YouTube Mix carries
the playlist context. The user asked for that one video, so the address means
SINGLE_MEDIA and yt-dlp must never be sent to the playlist extractor - neither
during analysis nor during the download.
"""

from __future__ import annotations

import pytest

from app.core.models import DownloadRequest, MediaKind
from app.core.urls import (
    UrlIntent,
    classify_url,
    normalize_url,
    playlist_url_for,
    youtube_video_id,
)
from app.core.ytdlp_service import YtDlpService
from app.settings import AppSettings

VIDEO_A = 'NPmRmfodJmk'
VIDEO_B = 'LkCFJjB64pY'
MIX_ID = 'RDLkCFJjB64pY'

WATCH_A = f'https://www.youtube.com/watch?v={VIDEO_A}'
WATCH_B = f'https://www.youtube.com/watch?v={VIDEO_B}'
PLAYLIST_URL = f'https://www.youtube.com/playlist?list={MIX_ID}'


@pytest.fixture
def service():
    return YtDlpService(AppSettings(output_dir='/tmp'))


# --------------------------------------------------------------- classification


@pytest.mark.parametrize('url', [
    f'https://youtu.be/{VIDEO_A}?list={MIX_ID}',
    f'https://youtu.be/{VIDEO_B}?list={MIX_ID}',
    f'https://www.youtube.com/watch?v={VIDEO_B}&list={MIX_ID}&start_radio=1',
    f'https://www.youtube.com/watch?v={VIDEO_A}&list={MIX_ID}&index=4',
    f'https://m.youtube.com/watch?v={VIDEO_A}&list={MIX_ID}',
    f'https://music.youtube.com/watch?v={VIDEO_A}&list={MIX_ID}',
    f'https://youtu.be/{VIDEO_A}',
    WATCH_A,
    f'https://www.youtube.com/shorts/{VIDEO_A}',
    f'https://www.youtube.com/live/{VIDEO_A}',
    f'https://www.youtube.com/embed/{VIDEO_A}',
])
def test_single_media_intent(url):
    """The presence of `list=` never turns a watch link into a playlist."""
    assert classify_url(url) is UrlIntent.SINGLE_MEDIA


@pytest.mark.parametrize('url', [
    PLAYLIST_URL,
    'https://www.youtube.com/playlist?list=PL2qgrgXsNUG5ig9cat4ohreBjYLAPC0J5',
    'https://www.youtube.com/@someChannel',
    'https://www.youtube.com/channel/UCEfMCQ9bs3tjvjy1s451zaw',
    'https://www.youtube.com/user/someone',
    'https://www.youtube.com/feed/subscriptions',
])
def test_playlist_intent(url):
    assert classify_url(url) is UrlIntent.PLAYLIST


@pytest.mark.parametrize('url', [
    '',
    'https://vimeo.com/12345',
    'https://soundcloud.com/artist/sets/album',
    'https://example.com/watch?v=abc',
])
def test_unknown_intent_is_left_to_yt_dlp(url):
    assert classify_url(url) is UrlIntent.UNKNOWN


def test_video_id_extraction():
    assert youtube_video_id(f'https://youtu.be/{VIDEO_A}?list={MIX_ID}') == VIDEO_A
    assert youtube_video_id(f'https://www.youtube.com/watch?v={VIDEO_A}&t=90') == VIDEO_A
    assert youtube_video_id(f'https://www.youtube.com/shorts/{VIDEO_A}') == VIDEO_A
    assert youtube_video_id(PLAYLIST_URL) == ''
    assert youtube_video_id('https://vimeo.com/12345') == ''
    # An id of the wrong length is not a video id
    assert youtube_video_id('https://youtu.be/tooshort') == ''


# ---------------------------------------------------------------- normalisation


@pytest.mark.parametrize(('given', 'expected'), [
    (f'https://youtu.be/{VIDEO_A}?list={MIX_ID}', WATCH_A),
    (f'https://youtu.be/{VIDEO_B}?list={MIX_ID}', WATCH_B),
    (f'https://www.youtube.com/watch?v={VIDEO_B}&list={MIX_ID}&start_radio=1', WATCH_B),
    (f'https://www.youtube.com/watch?v={VIDEO_A}&list={MIX_ID}&index=9&pp=abc', WATCH_A),
    (f'https://m.youtube.com/watch?v={VIDEO_A}&list={MIX_ID}', WATCH_A),
    (f'https://www.youtube.com/shorts/{VIDEO_A}', WATCH_A),
    (WATCH_A, WATCH_A),
])
def test_single_media_url_is_canonicalised(given, expected):
    assert normalize_url(given) == expected


def test_playlist_url_is_untouched():
    assert normalize_url(PLAYLIST_URL) == PLAYLIST_URL
    assert normalize_url('https://www.youtube.com/@someChannel') \
        == 'https://www.youtube.com/@someChannel'


def test_other_services_are_untouched():
    """Normalisation is YouTube specific; nothing else may be rewritten."""
    for url in ('https://vimeo.com/12345?list=abc',
                'https://soundcloud.com/artist/track?in=set',
                'https://example.com/watch?v=abc&list=x'):
        assert normalize_url(url) == url


def test_playlist_offered_alongside_a_single_video():
    assert playlist_url_for(f'https://youtu.be/{VIDEO_A}?list={MIX_ID}') == PLAYLIST_URL
    assert playlist_url_for(WATCH_A) == ''
    assert playlist_url_for('https://vimeo.com/1?list=x') == ''


# ------------------------------------------------------------------- yt-dlp options


def test_analysis_of_a_single_video_forbids_the_playlist(service):
    """Analyse and download must agree; the intent applies from the start."""
    options = service.probe_options(UrlIntent.SINGLE_MEDIA)
    assert options['noplaylist'] is True


def test_analysis_of_a_playlist_still_enumerates(service):
    for intent in (UrlIntent.PLAYLIST, UrlIntent.UNKNOWN):
        assert service.probe_options(intent)['noplaylist'] is False


def test_downloads_always_run_in_single_media_mode(service):
    request = DownloadRequest(url=f'https://youtu.be/{VIDEO_A}?list={MIX_ID}',
                              output_dir='/tmp', kind=MediaKind.VIDEO)
    assert service.download_options(request)['noplaylist'] is True


def test_no_global_noplaylist(service):
    """`noplaylist` is a per-job decision, never an application-wide setting."""
    assert 'noplaylist' not in service.base_options()


# ------------------------------------------------------------------- requests


def test_request_stores_the_canonical_url():
    request = DownloadRequest(url=f'https://youtu.be/{VIDEO_A}?list={MIX_ID}',
                              output_dir='/tmp')
    assert request.url == WATCH_A
    assert request.source_url == f'https://youtu.be/{VIDEO_A}?list={MIX_ID}'


def test_request_keeps_an_explicit_source_url():
    request = DownloadRequest(url=f'https://youtu.be/{VIDEO_A}?list={MIX_ID}',
                              output_dir='/tmp', source_url=PLAYLIST_URL)
    assert request.url == WATCH_A
    assert request.source_url == PLAYLIST_URL


def test_normalisation_is_idempotent():
    """A retry or a record restored from history must not reintroduce `list=`."""
    once = DownloadRequest(url=f'https://youtu.be/{VIDEO_A}?list={MIX_ID}', output_dir='/tmp')
    twice = DownloadRequest(url=once.url, output_dir='/tmp', source_url=once.source_url)
    assert twice.url == WATCH_A
    assert twice.source_url == f'https://youtu.be/{VIDEO_A}?list={MIX_ID}'
    assert 'list=' not in twice.url


@pytest.mark.parametrize('url', [
    f'https://youtu.be/{VIDEO_A}',
    f'https://youtu.be/{VIDEO_A}?list={MIX_ID}',
    WATCH_A,
    f'https://www.youtube.com/watch?v={VIDEO_A}&list=XYZ',
    f'https://m.youtube.com/watch?v={VIDEO_A}',
])
def test_every_form_of_one_video_is_one_url(url):
    """All spellings of the same video must collapse onto one identity."""
    assert DownloadRequest(url=url, output_dir='/tmp').url == WATCH_A


# ------------------------------------------------------------------- analysis


class _FakeYdl:
    """Stands in for `YoutubeDL`, recording the URL it was asked to extract."""

    def __init__(self, options):
        self.options = options
        self.seen: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def extract_info(self, url, download=False, process=True, ie_key=None):
        self.seen.append(url)
        return {'_type': 'video', 'id': VIDEO_A, 'title': 'One song',
                'extractor': 'youtube', 'webpage_url': WATCH_A, 'formats': []}

    def process_ie_result(self, raw, download=False):
        return raw

    def sanitize_info(self, info):
        return info


def test_analysis_never_sees_the_playlist_context(monkeypatch, service):
    """The mix link is analysed as one video, and yt-dlp is told so twice."""
    import yt_dlp

    created: list[_FakeYdl] = []

    def factory(options):
        ydl = _FakeYdl(options)
        created.append(ydl)
        return ydl

    monkeypatch.setattr(yt_dlp, 'YoutubeDL', factory)
    info = service.extract(f'https://youtu.be/{VIDEO_A}?list={MIX_ID}')

    assert created[0].seen == [WATCH_A]
    assert created[0].options['noplaylist'] is True
    assert info.is_playlist is False
    assert info.entries == ()
