"""Tests for duplicate detection and the "Needs review" tab."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from app.core.download_controller import DownloadController
from app.core.duplicates import (
    ArtifactIdentity,
    DuplicateKind,
    DuplicatePolicy,
    DuplicateService,
    target_directory,
)
from app.core.history import HistoryRecord, HistoryStore, MediaIdentity
from app.core.models import DownloadRequest, DownloadTask, MediaKind
from app.core.ytdlp_service import YtDlpService
from app.settings import AppSettings
from app.state import TaskState

YOUTUBE = MediaIdentity('Youtube', 'abc123')


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / 'history.db')


@pytest.fixture
def service(store):
    return DuplicateService(store)


def _request(output_dir: str, **kwargs) -> DownloadRequest:
    kwargs.setdefault('container', 'mp4')
    return DownloadRequest(url='https://example.com/v', output_dir=output_dir, **kwargs)


def _existing(store, path, *, media_kind='video', output_format='mp4', quality=0,
              record_id='old') -> HistoryRecord:
    """Record a download in history together with a file that really exists."""
    file_path = _touch(path)
    record = HistoryRecord(
        id=record_id, source_url='https://example.com/v', status=TaskState.FINISHED.value,
        extractor=YOUTUBE.extractor, media_id=YOUTUBE.media_id, media_kind=media_kind,
        output_format=output_format, quality=quality, final_path=str(file_path),
        output_directory=str(file_path.parent))
    store.add(record)
    return record


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('dane')
    return path


def _task(**kwargs) -> DownloadTask:
    request = kwargs.pop('request', None) or _request('/tmp/out')
    kwargs.setdefault('media_id', YOUTUBE.media_id)
    kwargs.setdefault('extractor', YOUTUBE.extractor)
    return DownloadTask(request=request, **kwargs)


# ----------------------------------------------------------------- identity


def test_the_artifact_tells_video_from_audio():
    video = ArtifactIdentity.from_request(_request('/o', kind=MediaKind.VIDEO), YOUTUBE)
    audio = ArtifactIdentity.from_request(
        _request('/o', kind=MediaKind.AUDIO, audio_format='mp3'), YOUTUBE)
    assert video != audio
    assert video.media == audio.media  # same media, different artifact


def test_the_artifact_distinguishes_quality():
    low = ArtifactIdentity.from_request(_request('/o', quality=720), YOUTUBE)
    high = ArtifactIdentity.from_request(_request('/o', quality=2160), YOUTUBE)
    assert low != high


def test_without_a_media_id_we_do_not_guess():
    artifact = ArtifactIdentity.from_request(_request('/o'), MediaIdentity('Youtube', ''))
    assert artifact.is_valid is False


def test_the_target_folder_includes_the_playlist_subfolder():
    request = _request('/base', playlist_title='Moja lista', create_playlist_folder=True)
    assert target_directory(request).endswith('/base/Moja lista')

    request.create_playlist_folder = False
    assert target_directory(request) == '/base'


# ------------------------------------------------- case 1: the same folder


def test_the_same_folder_means_an_automatic_skip(service, store, tmp_path):
    _existing(store, tmp_path / 'A' / 'film.mp4')
    result = service.check(_request(str(tmp_path / 'A')), YOUTUBE)

    assert result.kind is DuplicateKind.SAME_TARGET
    assert result.needs_decision is False


def test_a_missing_file_on_disk_allows_downloading_again(service, store, tmp_path):
    """A history record is no proof that the file still exists."""
    store.add(HistoryRecord(
        id='old', source_url='u', status=TaskState.FINISHED.value,
        extractor=YOUTUBE.extractor, media_id=YOUTUBE.media_id, media_kind='video',
        output_format='mp4', final_path=str(tmp_path / 'A' / 'znikniety.mp4')))

    assert service.check(_request(str(tmp_path / 'A')), YOUTUBE).kind is DuplicateKind.NONE


# ------------------------------------------------- case 2: a different folder


def test_a_different_folder_needs_a_decision(service, store, tmp_path):
    record = _existing(store, tmp_path / 'A' / 'film.mp4')
    result = service.check(_request(str(tmp_path / 'B')), YOUTUBE)

    assert result.kind is DuplicateKind.OTHER_TARGET
    assert result.needs_decision is True
    assert result.existing_record.id == record.id


def test_audio_does_not_collide_with_video(service, store, tmp_path):
    _existing(store, tmp_path / 'A' / 'film.mp4', media_kind='video', output_format='mp4')
    request = _request(str(tmp_path / 'A'), kind=MediaKind.AUDIO, audio_format='mp3')

    assert service.check(request, YOUTUBE).kind is DuplicateKind.NONE


def test_a_different_quality_is_not_the_same_file(service, store, tmp_path):
    _existing(store, tmp_path / 'A' / 'film.mp4', quality=720)
    assert service.check(_request(str(tmp_path / 'A'), quality=2160), YOUTUBE).kind \
        is DuplicateKind.NONE


# ------------------------------------------------------------- rezerwacje


def test_two_jobs_do_not_download_the_same_thing(service):
    request = _request('/out')
    first = service.check_and_reserve(request, YOUTUBE, 'task-1')
    second = service.check_and_reserve(request, YOUTUBE, 'task-2')

    assert first.kind is DuplicateKind.NONE
    assert second.kind is DuplicateKind.ALREADY_QUEUED


def test_releasing_a_reservation_unblocks_it(service):
    request = _request('/out')
    service.check_and_reserve(request, YOUTUBE, 'task-1')
    service.release(ArtifactIdentity.from_request(request, YOUTUBE), 'task-1')

    assert service.check_and_reserve(request, YOUTUBE, 'task-2').kind is DuplicateKind.NONE


def test_releasing_by_owner(service):
    service.check_and_reserve(_request('/out'), YOUTUBE, 'task-1')
    assert service.reserved_count() == 1
    service.release_owner('task-1')
    assert service.reserved_count() == 0


def test_reservation_is_thread_safe(service):
    """Two concurrent checks must not both hear "not a duplicate"."""
    import threading

    request = _request('/out')
    results = []
    barrier = threading.Barrier(8)

    def worker(index):
        barrier.wait()
        results.append(service.check_and_reserve(request, YOUTUBE, f'task-{index}').kind)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(DuplicateKind.NONE) == 1
    assert results.count(DuplicateKind.ALREADY_QUEUED) == 7


# --------------------------------------------------------------- polityki


def test_by_default_we_ask(service):
    assert service.policy('batch-1') is DuplicatePolicy.ASK


def test_a_policy_applies_only_to_its_own_batch(service):
    service.set_policy('batch-1', DuplicatePolicy.DOWNLOAD_ALL_FOR_QUEUE)
    assert service.policy('batch-1') is DuplicatePolicy.DOWNLOAD_ALL_FOR_QUEUE
    assert service.policy('batch-2') is DuplicatePolicy.ASK


# ------------------------------------------------- integracja z kontrolerem


@pytest.fixture
def controller(qapp, tmp_path):
    store = HistoryStore(tmp_path / 'history.db')
    ctl = DownloadController(YtDlpService(AppSettings()), history=store,
                             duplicates=DuplicateService(store))
    ctl.pause()
    yield ctl
    ctl.shutdown()


def test_the_same_folder_is_skipped_without_asking(controller, tmp_path):
    _existing(controller._history, tmp_path / 'A' / 'film.mp4')
    task = _task(request=_request(str(tmp_path / 'A')))
    controller.enqueue([task], autostart=False)

    assert task.state is TaskState.SKIPPED_DUPLICATE
    assert task.state.is_skipped is True
    assert controller.pending_review() == []


def test_a_different_folder_goes_to_needs_review(controller, tmp_path):
    _existing(controller._history, tmp_path / 'A' / 'film.mp4')
    task = _task(request=_request(str(tmp_path / 'B')))
    controller.enqueue([task], autostart=False)

    assert task.state is TaskState.NEEDS_REVIEW
    assert task.duplicate_of_path.endswith('film.mp4')
    assert [t.id for t in controller.pending_review()] == [task.id]


def test_a_conflict_does_not_stop_the_queue(controller, tmp_path):
    """Crucially, an item awaiting a decision does not block the others."""
    _existing(controller._history, tmp_path / 'A' / 'C.mp4', record_id='c')
    konflikt = _task(request=_request(str(tmp_path / 'B')), title='C')
    inne = [_task(request=_request(str(tmp_path / 'B')), title=name, media_id=name)
            for name in ('D', 'E')]
    controller.enqueue([konflikt, *inne], autostart=False)

    assert konflikt.state is TaskState.NEEDS_REVIEW
    assert [t.state for t in inne] == [TaskState.QUEUED, TaskState.QUEUED]


def test_approve_returns_the_item_to_the_queue(controller, tmp_path):
    _existing(controller._history, tmp_path / 'A' / 'film.mp4')
    task = _task(request=_request(str(tmp_path / 'B')))
    controller.enqueue([task], autostart=False)

    controller.approve([task.id])
    assert task.state is TaskState.QUEUED
    assert controller.pending_review() == []


def test_skipping_is_not_a_failure(controller, tmp_path):
    _existing(controller._history, tmp_path / 'A' / 'film.mp4')
    task = _task(request=_request(str(tmp_path / 'B')))
    controller.enqueue([task], autostart=False)

    controller.skip([task.id])
    assert task.state is TaskState.SKIPPED_BY_USER
    assert task.state.is_skipped is True
    assert task.state is not TaskState.ERROR


def test_approve_all(controller, tmp_path):
    for index in range(5):
        _existing(controller._history, tmp_path / 'A' / f'{index}.mp4',
                  record_id=f'r{index}')
    # Every item is a different media, but each has a match in another folder
    tasks = []
    for index in range(5):
        controller._history.add(HistoryRecord(
            id=f'h{index}', source_url='u', status=TaskState.FINISHED.value,
            extractor='Youtube', media_id=f'm{index}', media_kind='video',
            output_format='mp4', final_path=str(_touch(tmp_path / 'A' / f'm{index}.mp4'))))
        tasks.append(_task(request=_request(str(tmp_path / 'B')), media_id=f'm{index}'))
    controller.enqueue(tasks, autostart=False)
    assert len(controller.pending_review()) == 5

    controller.approve_all()
    assert controller.pending_review() == []
    assert all(task.state is TaskState.QUEUED for task in tasks)


def test_the_batch_policy_covers_later_conflicts(controller, tmp_path):
    """"Download all in this batch" also covers conflicts found later."""
    controller._history.add(HistoryRecord(
        id='h1', source_url='u', status=TaskState.FINISHED.value, extractor='Youtube',
        media_id='m1', media_kind='video', output_format='mp4',
        final_path=str(_touch(tmp_path / 'A' / 'm1.mp4'))))
    first = _task(request=_request(str(tmp_path / 'B')), media_id='m1')
    controller.enqueue([first], autostart=False)
    assert first.state is TaskState.NEEDS_REVIEW

    controller.apply_batch_policy(DuplicatePolicy.DOWNLOAD_ALL_FOR_QUEUE, [first.batch_id])
    assert first.state is TaskState.QUEUED

    # Another conflict in the same batch does not ask again
    controller._history.add(HistoryRecord(
        id='h2', source_url='u', status=TaskState.FINISHED.value, extractor='Youtube',
        media_id='m2', media_kind='video', output_format='mp4',
        final_path=str(_touch(tmp_path / 'A' / 'm2.mp4'))))
    second = _task(request=_request(str(tmp_path / 'B')), media_id='m2')
    second.batch_id = first.batch_id
    controller._resolve_duplicates([second])
    assert second.state is TaskState.QUEUED


def test_a_new_batch_asks_again(controller, tmp_path):
    controller._history.add(HistoryRecord(
        id='h1', source_url='u', status=TaskState.FINISHED.value, extractor='Youtube',
        media_id='m1', media_kind='video', output_format='mp4',
        final_path=str(_touch(tmp_path / 'A' / 'm1.mp4'))))
    first = _task(request=_request(str(tmp_path / 'B')), media_id='m1')
    controller.enqueue([first], autostart=False)
    controller.apply_batch_policy(DuplicatePolicy.DOWNLOAD_ALL_FOR_QUEUE, [first.batch_id])

    controller._history.add(HistoryRecord(
        id='h2', source_url='u', status=TaskState.FINISHED.value, extractor='Youtube',
        media_id='m2', media_kind='video', output_format='mp4',
        final_path=str(_touch(tmp_path / 'A' / 'm2.mp4'))))
    second = _task(request=_request(str(tmp_path / 'B')), media_id='m2')
    controller.enqueue([second], autostart=False)

    assert second.state is TaskState.NEEDS_REVIEW, 'a new batch must ask again'


def test_a_duplicate_is_neither_active_nor_final():
    assert TaskState.NEEDS_REVIEW.is_active is False
    assert TaskState.NEEDS_REVIEW.is_final is False
    assert TaskState.NEEDS_REVIEW.needs_decision is True


def test_the_reservation_is_released_in_every_final_state(controller, tmp_path):
    """A stuck reservation would block this media forever."""
    from app.core.models import DownloadResult

    for finish in (
        lambda t: controller._on_completed(t.id, DownloadResult.classify(completed=1, total=1)),
        lambda t: controller._on_failed(t.id, __import__(
            'app.core.errors', fromlist=['x']).FriendlyError()),
        lambda t: controller._on_cancelled(t.id),
    ):
        task = _task(request=_request(str(tmp_path / 'B')), media_id=f'm{id(finish)}')
        controller.enqueue([task], autostart=False)
        assert controller.duplicates.reserved_count() >= 1
        finish(task)
        assert controller.duplicates.reserved_count() == 0, task.state


def test_the_reservation_is_released_after_removal(controller, tmp_path):
    task = _task(request=_request(str(tmp_path / 'B')))
    controller.enqueue([task], autostart=False)
    assert controller.duplicates.reserved_count() == 1

    controller.remove([task.id])
    assert controller.duplicates.reserved_count() == 0


def test_the_reservation_is_released_after_a_skip(controller, tmp_path):
    _existing(controller._history, tmp_path / 'A' / 'film.mp4')
    task = _task(request=_request(str(tmp_path / 'B')))
    controller.enqueue([task], autostart=False)

    controller.skip([task.id])
    assert controller.duplicates.reserved_count() == 0
