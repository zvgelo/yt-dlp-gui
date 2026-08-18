"""Tests for the models and for value formatting."""

from __future__ import annotations

import pytest

from app.core.models import DownloadProgress, DownloadRequest, DownloadTask, MediaKind
from app.state import TaskState
from app.utils import formatting as fmt


def test_progress_from_hook():
    progress = DownloadProgress.from_hook({
        'status': 'downloading',
        'downloaded_bytes': 26_000_000,
        'total_bytes_estimate': 38_000_000,
        'speed': 8_800_000,
        'eta': 2,
        'fragment_index': 3,
        'fragment_count': 10,
    })
    assert progress.total_bytes == 38_000_000
    assert progress.percent == pytest.approx(68.4, abs=0.1)


def test_progress_from_fragments_when_size_unknown():
    progress = DownloadProgress.from_hook({'status': 'downloading',
                                           'fragment_index': 5, 'fragment_count': 10})
    assert progress.percent == 50.0


def test_progress_unknown():
    assert DownloadProgress().percent is None


def test_task_summary():
    task = DownloadTask(
        request=DownloadRequest(url='https://example.com/v', output_dir='/tmp', container='mp4'),
        title='Example', uploader='Author', duration=1328, quality_label='1080p',
        expected_size=119 * 1024 * 1024,
    )
    summary = task.summary
    assert '22:08' in summary
    assert 'MP4' in summary
    assert '1080p' in summary
    assert 'Author' in summary


def test_reset_clears_state():
    task = DownloadTask(request=DownloadRequest(url='u', output_dir='/tmp'))
    task.state = TaskState.ERROR
    task.error = 'something'
    task.percent = 42.0
    task.reset()

    assert task.state is TaskState.QUEUED
    assert task.error == ''
    assert task.percent == 0.0


def test_target_extension():
    video = DownloadRequest(url='u', output_dir='/tmp', container='mkv')
    audio = DownloadRequest(url='u', output_dir='/tmp', kind=MediaKind.AUDIO, audio_format='flac')
    assert video.target_ext == 'mkv'
    assert audio.target_ext == 'flac'


@pytest.mark.parametrize(('value', 'expected'), [
    (None, '—'), (0, '—'), (512, '512 B'), (4_600_000, '4.4 MB'), (2_500_000_000, '2.3 GB'),
])
def test_filesize_formatting(value, expected):
    assert fmt.size(value) == expected


@pytest.mark.parametrize(('value', 'expected'), [
    (None, '—'), (65, '01:05'), (1328, '22:08'), (3725, '1:02:05'),
])
def test_duration_formatting(value, expected):
    assert fmt.duration(value) == expected


def test_extracting_urls():
    text = 'zobacz https://example.com/a oraz https://example.com/b, i znowu https://example.com/a'
    assert fmt.extract_urls(text) == ['https://example.com/a', 'https://example.com/b']


def test_no_urls():
    assert fmt.extract_urls('no links here') == []


@pytest.mark.parametrize(('count', 'expected'), [
    (0, 'pozycji'), (1, 'pozycja'), (3, 'pozycje'), (5, 'pozycji'), (12, 'pozycji'), (22, 'pozycje'),
])
def test_counter_plural_form(count, expected):
    assert fmt.plural_items(count) == expected
