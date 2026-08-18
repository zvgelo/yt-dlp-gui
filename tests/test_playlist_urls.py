"""Regression tests for playlist child URLs and pagination failures.

A playlist entry must be downloaded as a single media item. Downloading it
through the URL it was discovered with sends yt-dlp back to the playlist
extractor, which re-enumerates the whole playlist once per entry.
"""

from __future__ import annotations

import pytest

from app.core.errors import AppErrorCode, ErrorCategory, describe, is_retryable
from app.core.history import HistoryStore, MediaIdentity
from app.core.history_mapper import record_from_task, task_from_record
from app.core.models import DownloadRequest, DownloadTask, MediaKind
from app.core.urls import canonical_media_url, has_playlist_context, strip_playlist_params
from app.core.ytdlp_service import YtDlpService, build_playlist_info
from app.settings import AppSettings
from app.state import TaskState

MIX_URL = 'https://www.youtube.com/watch?v=LkCFJjB64pY&list=RDLkCFJjB64pY'
CHILD_ID = 'NPmRmfodJmk'
CHILD_DISCOVERED = f'https://youtu.be/{CHILD_ID}?list=RDLkCFJjB64pY'
CHILD_CANONICAL = f'https://www.youtube.com/watch?v={CHILD_ID}'


# ------------------------------------------------------------ canonical URLs


@pytest.mark.parametrize('discovered', [
    CHILD_DISCOVERED,
    f'https://www.youtube.com/watch?v={CHILD_ID}&list=RDLkCFJjB64pY',
    f'https://www.youtube.com/watch?v={CHILD_ID}&list=RD&index=7&start_radio=1',
    f'https://youtu.be/{CHILD_ID}?list=RD&feature=youtu.be',
])
def test_child_url_loses_playlist_context(discovered):
    assert canonical_media_url(discovered, extractor='Youtube', media_id=CHILD_ID) \
        == CHILD_CANONICAL


def test_plain_video_url_is_left_alone():
    assert canonical_media_url(CHILD_CANONICAL, extractor='Youtube', media_id=CHILD_ID) \
        == CHILD_CANONICAL


def test_other_services_only_lose_playlist_params():
    assert canonical_media_url('https://vimeo.com/12345?list=abc', extractor='Vimeo',
                               media_id='12345') == 'https://vimeo.com/12345'
    # Unrelated query parameters must survive
    assert strip_playlist_params('https://example.com/v?quality=hd&list=x') \
        == 'https://example.com/v?quality=hd'


def test_unknown_extractor_without_id_still_cleaned():
    assert canonical_media_url('https://example.com/v/1?list=x', extractor='', media_id='') \
        == 'https://example.com/v/1'


def test_playlist_context_detection():
    assert has_playlist_context(CHILD_DISCOVERED) is True
    assert has_playlist_context(CHILD_CANONICAL) is False


# ------------------------------------------------------- entries carry both URLs


def _playlist(entries):
    return build_playlist_info(MIX_URL, {
        '_type': 'playlist', 'title': 'Mix', 'webpage_url': MIX_URL, 'entries': entries})


def test_entry_keeps_source_and_canonical_url():
    info = _playlist(iter([{'url': CHILD_DISCOVERED, 'title': 'Track', 'id': CHILD_ID,
                            'ie_key': 'Youtube'}]))
    entry = info.entries[0]

    assert entry.url == CHILD_DISCOVERED
    assert entry.canonical_url == CHILD_CANONICAL
    assert entry.download_url == CHILD_CANONICAL
    assert entry.playlist_url == MIX_URL


def test_download_url_falls_back_when_id_missing():
    info = _playlist(iter([{'url': 'https://example.com/v/9', 'title': 'X'}]))
    assert info.entries[0].download_url == 'https://example.com/v/9'


# --------------------------------------------------------------- yt-dlp options


def test_child_download_forces_single_media_mode():
    """`noplaylist` is the second line of defence if a URL still has context."""
    options = YtDlpService(AppSettings()).download_options(
        DownloadRequest(url=CHILD_CANONICAL, output_dir='/tmp', playlist_title='Mix'))
    assert options['noplaylist'] is True


def test_analysis_still_allows_playlists():
    options = YtDlpService(AppSettings()).probe_options()
    assert options['noplaylist'] is False


# ------------------------------------------------------- pagination failures


PAGINATION_ERROR = ('RDLkCFJjB64pY page 2: Unable to download API page: '
                    'HTTP Error 403: Forbidden')


def test_pagination_failure_has_its_own_code():
    error = describe(Exception(f'ERROR: {PAGINATION_ERROR}'))
    assert error.code is AppErrorCode.PLAYLIST_INCOMPLETE
    assert error.category is ErrorCategory.PLAYLIST_ENUMERATION


def test_pagination_failure_is_not_retried_as_whole_job():
    """Retrying would restart enumeration and drop the entries already found."""
    assert is_retryable(AppErrorCode.PLAYLIST_INCOMPLETE) is False
    assert is_retryable(AppErrorCode.NETWORK_ERROR) is True


def test_discovered_entries_survive_pagination_failure():
    class PaginationFailure(Exception):
        pass

    def entries():
        for index in range(1, 50):
            yield {'url': f'https://youtu.be/id{index:08d}?list=RD',
                   'title': f'Track {index}', 'id': f'id{index:08d}', 'ie_key': 'Youtube'}
        raise PaginationFailure(PAGINATION_ERROR)

    info = _playlist(entries())

    assert info.entry_count == 49
    assert info.entries_complete is False
    assert '403' in info.entries_error
    # Every discovered entry is downloadable as a single item
    assert all(not has_playlist_context(entry.download_url) for entry in info.entries)


def test_enumeration_runs_once(monkeypatch):
    """The playlist generator must be consumed exactly one time."""
    starts = []

    def entries():
        starts.append(1)
        yield {'url': CHILD_DISCOVERED, 'title': 'Track', 'id': CHILD_ID, 'ie_key': 'Youtube'}
        raise RuntimeError(PAGINATION_ERROR)

    _playlist(entries())
    assert len(starts) == 1


def test_unknown_total_is_not_an_error():
    """A dynamic mix has no known total; that is normal, not a failure."""
    info = _playlist(iter([{'url': CHILD_DISCOVERED, 'title': 'T', 'id': CHILD_ID,
                            'ie_key': 'Youtube'}]))
    assert info.is_playlist is True
    assert info.entries_complete is True


# ------------------------------------------------------------ media identity


def test_same_video_through_different_urls_is_one_identity():
    identities = {
        MediaIdentity('Youtube', CHILD_ID).key,
        MediaIdentity('Youtube', CHILD_ID).key,
        MediaIdentity('Youtube', CHILD_ID).key,
    }
    assert len(identities) == 1

    # Identity comes from extractor + id, never from the URL
    for url in (CHILD_CANONICAL, CHILD_DISCOVERED,
                f'https://www.youtube.com/watch?v={CHILD_ID}&list=XYZ'):
        info = _playlist(iter([{'url': url, 'title': 'T', 'id': CHILD_ID, 'ie_key': 'Youtube'}]))
        assert info.entries[0].media_id == CHILD_ID


# ------------------------------------------------------------- persistence


def test_retry_after_restart_uses_canonical_url(tmp_path):
    store = HistoryStore(tmp_path / 'history.db')
    task = DownloadTask(
        request=DownloadRequest(url=CHILD_CANONICAL, source_url=CHILD_DISCOVERED,
                                output_dir='/tmp', playlist_title='Mix', playlist_index=7),
        title='Track', media_id=CHILD_ID, extractor='Youtube', state=TaskState.ERROR)
    store.add(record_from_task(task))

    restored = task_from_record(store.get(task.id))

    assert restored.request.url == CHILD_CANONICAL
    assert restored.request.source_url == CHILD_DISCOVERED
    assert has_playlist_context(restored.request.url) is False


def test_history_keeps_both_urls(tmp_path):
    task = DownloadTask(
        request=DownloadRequest(url=CHILD_CANONICAL, source_url=CHILD_DISCOVERED,
                                output_dir='/tmp'),
        media_id=CHILD_ID, extractor='Youtube')
    record = record_from_task(task)

    assert record.canonical_url == CHILD_CANONICAL
    assert record.source_url == CHILD_DISCOVERED


def test_audio_child_also_uses_canonical_url():
    info = _playlist(iter([{'url': CHILD_DISCOVERED, 'title': 'T', 'id': CHILD_ID,
                            'ie_key': 'Youtube'}]))
    request = DownloadRequest(url=info.entries[0].download_url, output_dir='/tmp',
                              kind=MediaKind.AUDIO, audio_format='mp3')
    options = YtDlpService(AppSettings()).download_options(request)

    assert options['noplaylist'] is True
    assert has_playlist_context(request.url) is False


# ------------------------------------------------------- lazy redirect handling


class _FakeYdl:
    """Minimal stand-in recording how extraction was requested."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def extract_info(self, url, download=False, process=True, ie_key=None):
        self.calls.append({'url': url, 'process': process, 'ie_key': ie_key})
        return self._responses.pop(0)


def test_redirects_are_followed_without_processing():
    """`youtu.be/<id>?list=` only redirects; resolving it eagerly would enumerate."""
    from app.core.ytdlp_service import _resolve_redirects

    ydl = _FakeYdl([
        {'_type': 'url', 'url': MIX_URL, 'ie_key': 'YoutubeTab'},
        {'_type': 'playlist', 'title': 'Mix', 'entries': iter([])},
    ])
    result = _resolve_redirects(ydl, CHILD_DISCOVERED)

    assert result['_type'] == 'playlist'
    assert [call['process'] for call in ydl.calls] == [False, False]
    assert ydl.calls[1]['ie_key'] == 'YoutubeTab'


def test_redirect_chain_is_bounded():
    from app.core.ytdlp_service import _resolve_redirects

    ydl = _FakeYdl([{'_type': 'url', 'url': f'https://example.com/{i}'} for i in range(20)])
    _resolve_redirects(ydl, 'https://example.com/start', max_depth=3)

    assert len(ydl.calls) == 4


def test_plain_video_needs_no_redirect():
    from app.core.ytdlp_service import _resolve_redirects

    ydl = _FakeYdl([{'_type': 'video', 'id': CHILD_ID, 'formats': []}])
    result = _resolve_redirects(ydl, CHILD_CANONICAL)

    assert result['id'] == CHILD_ID
    assert len(ydl.calls) == 1
