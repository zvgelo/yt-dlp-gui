"""Tests for download-result semantics and lazy playlist reading.

The key rule: a worker finishing is not the same as a success.
"""

from __future__ import annotations

import pytest

from app.core.download_controller import _STATE_FOR_RESULT
from app.core.errors import ErrorLog, is_enumeration_error, normalize_error
from app.core.models import (
    DownloadRequest,
    DownloadResult,
    DownloadResultStatus,
    MediaKind,
)
from app.core.ytdlp_service import YtDlpService, build_playlist_info, build_result
from app.settings import AppSettings
from app.state import TaskState

S = DownloadResultStatus


@pytest.fixture(scope='module')
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

#: The real yt-dlp message this work started from
PAGINATION_ERROR = ('RDLkCFJjB64pY page 3: Unable to download API page: '
                    'HTTP Error 403: Forbidden (caused by <HTTPError 403: Forbidden>)')


# ------------------------------------------------------- klasyfikacja statusu


def test_a_full_success(qapp):
    from app.gui import labels

    result = DownloadResult.classify(completed=3, total=3)
    assert result.status is S.SUCCESS
    assert result.total_is_known is True
    assert labels.result_count_label(result) == '3 / 3'


def test_b_partial_success_when_some_items_failed():
    result = DownloadResult.classify(completed=8, failed=2, total=10)
    assert result.status is S.PARTIAL_SUCCESS
    assert result.completed_items == 8
    assert result.failed_items == 2


def test_c_an_enumeration_error_is_never_a_success(qapp):
    result = DownloadResult.classify(
        completed=37, enumeration_complete=False,
        enumeration_errors=(normalize_error(PAGINATION_ERROR),))

    assert result.status is S.PARTIAL_SUCCESS
    assert result.status is not S.SUCCESS
    assert result.playlist_enumeration_complete is False
    # The full item count is unknown, so "37 of 37" must not be shown
    assert result.total_items is None
    assert result.total_is_known is False


def test_d_total_failure():
    result = DownloadResult.classify(completed=0, fatal=True, errors=('Video unavailable',))
    assert result.status is S.ERROR


def test_d_no_downloads_without_an_exception_is_also_an_error():
    assert DownloadResult.classify(completed=0).status is S.ERROR


def test_e_cancellation_takes_precedence():
    result = DownloadResult.classify(cancelled=True, completed=5, errors=('cokolwiek',))
    assert result.status is S.CANCELLED


def test_enumeration_error_before_the_first_item():
    result = DownloadResult.classify(
        completed=0, enumeration_complete=False, enumeration_errors=('page 1: 403',))
    assert result.status is S.ERROR
    assert result.completed_items == 0


def test_an_error_does_not_erase_earlier_successes():
    result = DownloadResult.classify(completed=37, enumeration_complete=False)
    assert result.completed_items == 37


def test_success_requires_no_errors():
    # Even with no exception raised, a logger error blocks SUCCESS
    assert DownloadResult.classify(completed=1, total=1, errors=('something went wrong',)).status \
        is S.PARTIAL_SUCCESS


# --------------------------------------------------------- mapping to GUI state


@pytest.mark.parametrize(('status', 'expected'), [
    (S.SUCCESS, TaskState.FINISHED),
    (S.PARTIAL_SUCCESS, TaskState.COMPLETED_WITH_ERRORS),
    (S.ERROR, TaskState.ERROR),
    (S.CANCELLED, TaskState.CANCELLED),
])
def test_status_maps_onto_the_task_state(status, expected):
    assert _STATE_FOR_RESULT[status] is expected
    assert expected.is_ok is (status is S.SUCCESS)


def test_the_user_description_mentions_an_incomplete_playlist(qapp):
    """The GUI layer composes the text; core returns data only."""
    from app.gui import labels

    result = DownloadResult.classify(
        completed=37, enumeration_complete=False,
        enumeration_errors=(normalize_error(PAGINATION_ERROR),))
    opis = labels.describe_result(result)
    assert 'playlist' in opis.lower()
    assert 'missing' in opis.lower()


# ------------------------------------------------------ error deduplication


def test_the_same_error_from_several_layers_counts_once():
    log = ErrorLog()
    log.add(f'ERROR: {PAGINATION_ERROR}')
    log.add(PAGINATION_ERROR)
    log.add('RDLkCFJjB64pY page 3: Unable to download API page: HTTP Error 403: Forbidden')

    assert len(log.enumeration) == 1
    assert log.items == []
    assert log.enumeration_failed is True


def test_different_pages_are_different_errors():
    log = ErrorLog()
    log.add('X page 3: Unable to download API page: HTTP Error 403: Forbidden')
    log.add('X page 5: Unable to download API page: HTTP Error 403: Forbidden')
    assert len(log.enumeration) == 2


def test_item_errors_are_told_apart_from_enumeration_errors():
    assert is_enumeration_error(PAGINATION_ERROR) is True
    assert is_enumeration_error('ERROR: [youtube] abc: Video unavailable') is False

    log = ErrorLog()
    log.add(PAGINATION_ERROR)
    log.add('ERROR: [youtube] abc: Video unavailable')
    assert len(log.enumeration) == 1  # an incomplete list
    assert len(log.items) == 1  # one specific video failed


# ----------------------------------------------- budowanie wyniku z info_dict


def test_result_for_a_single_video():
    info = {'requested_downloads': [{'filepath': '/tmp/a.mp4'}]}
    result = build_result(info, ErrorLog(), {'abc'})

    assert result.status is S.SUCCESS
    assert result.completed_items == 1
    assert result.primary_file == '/tmp/a.mp4'


def test_result_for_a_playlist_with_item_errors():
    info = {
        '_type': 'playlist',
        'playlist_count': 3,
        'entries': [
            {'requested_downloads': [{'filepath': '/tmp/1.mp4'}]},
            None,
            {'requested_downloads': [{'filepath': '/tmp/3.mp4'}]},
        ],
    }
    result = build_result(info, ErrorLog(), {'1', '3'})

    assert result.status is S.PARTIAL_SUCCESS
    assert result.completed_items == 2
    assert result.failed_items == 1
    assert result.output_files == ('/tmp/1.mp4', '/tmp/3.mp4')


def test_result_when_an_exception_stopped_the_download_after_a_few_items():
    """No `info`, but the hooks already reported finished media."""
    errors = ErrorLog()
    errors.add(PAGINATION_ERROR)
    result = build_result(None, errors, {'a', 'b', 'c'}, fatal=True)

    assert result.status is S.PARTIAL_SUCCESS
    assert result.completed_items == 3
    assert result.playlist_enumeration_complete is False
    assert result.total_items is None


def test_result_when_nothing_was_downloaded():
    errors = ErrorLog()
    errors.add('ERROR: Video unavailable')
    result = build_result(None, errors, set(), fatal=True)

    assert result.status is S.ERROR
    assert result.completed_items == 0


# ------------------------------------------------------------ lazy playlist


class PaginationFailure(Exception):
    """Stands in for an extractor error while reading a further page."""


def _entry(index: int) -> dict:
    return {'url': f'https://example.com/v{index}', 'title': f'Film {index}', 'duration': 60}


def test_an_interrupted_generator_keeps_the_earlier_entries():
    """entry1..3 are processed despite the page error; enumeration is incomplete."""
    def entries():
        yield _entry(1)
        yield _entry(2)
        yield _entry(3)
        raise PaginationFailure(PAGINATION_ERROR)

    info = build_playlist_info('https://example.com/list',
                               {'_type': 'playlist', 'title': 'Lista', 'entries': entries()})

    assert info.entry_count == 3
    assert [e.title for e in info.entries] == ['Film 1', 'Film 2', 'Film 3']
    assert info.entries_complete is False
    assert '403' in info.entries_error


def test_a_full_playlist_is_complete():
    """The generator ends normally: 10 items, enumeration complete."""
    def entries():
        yield from (_entry(i) for i in range(1, 11))

    info = build_playlist_info('https://example.com/list',
                               {'_type': 'playlist', 'title': 'Lista', 'entries': entries()})

    assert info.entry_count == 10
    assert info.entries_complete is True
    assert info.entries_error == ''


def test_an_error_before_the_first_item():
    """Nothing was collected and the enumeration is incomplete."""
    def entries():
        raise PaginationFailure('page 1: Unable to download API page: HTTP Error 403: Forbidden')
        yield  # pragma: no cover

    info = build_playlist_info('https://example.com/list',
                               {'_type': 'playlist', 'title': 'Lista', 'entries': entries()})

    assert info.entry_count == 0
    assert info.entries_complete is False
    assert DownloadResult.classify(
        completed=0, enumeration_complete=False,
        enumeration_errors=(info.entries_error,)).status is S.ERROR


def test_the_generator_is_not_materialised_up_front():
    """Entries must be consumed lazily, with no `list(entries)` on our side."""
    requested = []

    def entries():
        for i in range(1, 6):
            requested.append(i)
            yield _entry(i)

    raw = {'_type': 'playlist', 'title': 'Lista', 'entries': entries()}
    assert requested == []  # nothing has been asked for yet
    build_playlist_info('https://example.com/list', raw)
    assert requested == [1, 2, 3, 4, 5]


def test_nested_playlists_are_flattened_as_a_stream():
    def inner():
        yield _entry(1)
        yield _entry(2)

    raw = {
        '_type': 'playlist', 'title': 'Channel',
        'entries': iter([{'_type': 'playlist', 'title': 'Tab', 'entries': inner()}]),
    }
    info = build_playlist_info('https://example.com/c', raw)
    assert info.entry_count == 2
    assert info.entries_complete is True


# ----------------------------------------------------------- opcje yt-dlp


def test_downloading_uses_lazy_playlist():
    service = YtDlpService(AppSettings())
    options = service.download_options(DownloadRequest(url='u', output_dir='/tmp'))
    assert options['lazy_playlist'] is True


def test_analysis_uses_lazy_playlist():
    service = YtDlpService(AppSettings())
    options = service.probe_options()
    assert options['lazy_playlist'] is True
    # The limit is applied while iterating, not through playlist_items
    assert 'playlist_items' not in options


def test_ignoreerrors_stays_disabled():
    """The job covers one media item (`noplaylist`), so an error must stop it."""
    service = YtDlpService(AppSettings())
    options = service.download_options(
        DownloadRequest(url='u', output_dir='/tmp', kind=MediaKind.AUDIO))
    assert options['ignoreerrors'] is False
    assert options['noplaylist'] is True
