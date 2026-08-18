"""Regression tests for referential integrity of the download history.

The history used `INSERT OR REPLACE`, which is destructive: on a primary-key
conflict SQLite deletes the existing row and inserts a new one. That ran the
`ON DELETE CASCADE` from `attempts.record_id` (silently wiping the attempt
history) and re-validated `records.playlist_id` as if the row were new, so
persisting a queue item whose playlist row had been cleared raised

    sqlite3.IntegrityError: FOREIGN KEY constraint failed

straight out of a Qt slot, taking the interface down with it.
"""

from __future__ import annotations

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication

from app.core.download_controller import DownloadController
from app.core.duplicates import DuplicatePolicy
from app.core.history import HistoryRecord, HistoryStore, PlaylistRecord
from app.core.models import DownloadAttempt, DownloadRequest, DownloadTask, PlaylistJob
from app.core.ytdlp_service import YtDlpService
from app.settings import AppSettings
from app.state import TaskState


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / 'history.db')


@pytest.fixture
def controller(qapp, tmp_path):
    settings = AppSettings(output_dir=str(tmp_path), job_retries=0, job_retry_delay=0)
    store = HistoryStore(tmp_path / 'history.db')
    controller = DownloadController(YtDlpService(settings), history=store)
    yield controller
    controller.shutdown()


def _record(record_id: str, **kwargs) -> HistoryRecord:
    data = {
        'id': record_id,
        'source_url': f'https://example.com/{record_id}',
        'status': TaskState.FINISHED.value,
        'extractor': 'Youtube',
        'media_id': record_id,
    }
    data.update(kwargs)
    return HistoryRecord(**data)


def _attempt(number: int = 1) -> DownloadAttempt:
    return DownloadAttempt(number=number, started_at='2026-01-01T00:00:00+00:00',
                           finished_at='2026-01-01T00:00:05+00:00',
                           status=TaskState.ERROR.value, error_code='network_error',
                           error_message='timeout')


def _task(controller, title='Film', **kwargs) -> DownloadTask:
    request = DownloadRequest(url=f'https://example.com/{title}',
                              output_dir=controller._service.settings.output_dir)
    task = DownloadTask(request=request, title=title, media_id=title, extractor='Youtube',
                        **kwargs)
    return task


def _integrity(store: HistoryStore) -> list:
    """`PRAGMA foreign_key_check` must always come back empty."""
    return store._connection().execute('PRAGMA foreign_key_check').fetchall()


# --------------------------------------------------------------- upsert, not replace


def test_updating_a_parent_keeps_its_children(store):
    """The exact difference between REPLACE and a real upsert."""
    playlist = PlaylistRecord(id='pl1', title='Mix', source_url='https://example.com/list')
    child = _record('c1', playlist_id='pl1')
    store.save_playlist_with_items(playlist, [child])

    playlist.title = 'Mix (renamed)'
    store.add_playlist(playlist)

    assert store.get('c1').playlist_id == 'pl1'
    assert _integrity(store) == []


def test_updating_a_record_keeps_its_attempts(store):
    """REPLACE deleted the row, and `ON DELETE CASCADE` took the attempts with it."""
    record = _record('r1', status=TaskState.ERROR.value)
    store.add(record)
    store.save_attempts('r1', [_attempt(1), _attempt(2)])

    record.status = TaskState.SKIPPED_BY_USER.value
    store.update(record)

    assert len(store.load_attempts('r1')) == 2
    assert store.get('r1').status == TaskState.SKIPPED_BY_USER.value
    assert _integrity(store) == []


def test_updating_a_child_of_a_playlist(store):
    playlist = PlaylistRecord(id='pl1', title='Mix', source_url='https://example.com/list')
    child = _record('c1', playlist_id='pl1', status=TaskState.NEEDS_REVIEW.value)
    store.save_playlist_with_items(playlist, [child])

    child.status = TaskState.SKIPPED_BY_USER.value
    store.update(child)

    stored = store.get('c1')
    assert stored.status == TaskState.SKIPPED_BY_USER.value
    assert stored.playlist_id == 'pl1'
    assert _integrity(store) == []


def test_a_duplicate_reference_survives_an_update_of_its_target(store):
    store.add(_record('a'))
    store.add(_record('b', duplicate_of_record_id='a',
                      status=TaskState.NEEDS_REVIEW.value))

    original = _record('a', title='Renamed')
    store.update(original)

    assert store.get('a').title == 'Renamed'
    assert store.get('b').duplicate_of_record_id == 'a'
    assert _integrity(store) == []


def test_no_destructive_replace_in_the_sql(store):
    """Guards the fix itself: REPLACE must not creep back in."""
    import app.core.history as history

    assert 'INSERT OR REPLACE' not in history._SCHEMA
    assert 'ON CONFLICT(id) DO UPDATE' in history._upsert_sql(
        'records', history._RECORD_FIELDS, 'id')
    assert 'OR REPLACE' not in history._upsert_sql(
        'records', history._RECORD_FIELDS, 'id')


def test_the_primary_key_is_not_updated(store):
    statement = __import__('app.core.history', fromlist=['x'])._upsert_sql(
        'records', ('id', 'status'), 'id')
    assert 'id = excluded.id' not in statement
    assert 'status = excluded.status' in statement


# ------------------------------------------------------------- dangling references


def test_a_cleared_playlist_does_not_break_the_write(store):
    """The reported crash: clear the history, then persist a queue item."""
    playlist = PlaylistRecord(id='pl1', title='Mix', source_url='https://example.com/list')
    child = _record('c1', playlist_id='pl1', status=TaskState.NEEDS_REVIEW.value)
    store.save_playlist_with_items(playlist, [child])
    store.clear()

    child.status = TaskState.SKIPPED_BY_USER.value
    store.update(child)

    stored = store.get('c1')
    assert stored.status == TaskState.SKIPPED_BY_USER.value
    # The parent is gone, so the reference is dropped rather than written dangling
    assert stored.playlist_id is None
    assert _integrity(store) == []


def test_a_deleted_duplicate_target_is_forgotten(store):
    store.add(_record('a', final_path='/tmp/a.mp4'))
    store.add(_record('b', duplicate_of_record_id='a', duplicate_kind='other_target',
                      status=TaskState.NEEDS_REVIEW.value))
    store.delete(['a'])

    store.update(_record('b', duplicate_of_record_id='a', duplicate_kind='other_target',
                         status=TaskState.SKIPPED_BY_USER.value))

    stored = store.get('b')
    assert stored.duplicate_of_record_id == ''
    assert stored.duplicate_kind == ''
    assert _integrity(store) == []


# ----------------------------------------------------------- skip through the queue


def _pending(controller, count: int, tmp_path) -> list[DownloadTask]:
    """`count` items waiting for a duplicate decision, as the queue produces them."""
    existing = tmp_path / 'elsewhere'
    existing.mkdir(exist_ok=True)
    tasks = []
    for index in range(count):
        media = f'v{index}'
        target = existing / f'{media}.mp4'
        target.write_text('x')
        controller._history.add(HistoryRecord(
            id=f'old-{media}', source_url=f'https://example.com/{media}',
            status=TaskState.FINISHED.value, extractor='Youtube', media_id=media,
            media_kind='video', output_format='mp4', quality=0,
            output_directory=str(existing), final_path=str(target)))
        task = _task(controller, title=media)
        task.media_id = media
        tasks.append(task)
    controller.enqueue(tasks, autostart=False)
    return tasks


def test_skip_persists_a_single_review(controller, tmp_path):
    tasks = _pending(controller, 1, tmp_path)
    assert tasks[0].state is TaskState.NEEDS_REVIEW

    controller.skip([tasks[0].id])

    assert tasks[0].state is TaskState.SKIPPED_BY_USER
    assert controller._history.get(tasks[0].id).status == TaskState.SKIPPED_BY_USER.value
    assert _integrity(controller._history) == []


def test_skip_all_persists_every_review(controller, tmp_path):
    tasks = _pending(controller, 10, tmp_path)
    assert all(task.state is TaskState.NEEDS_REVIEW for task in tasks)

    controller.skip_all()

    assert all(task.state is TaskState.SKIPPED_BY_USER for task in tasks)
    stored = {controller._history.get(task.id).status for task in tasks}
    assert stored == {TaskState.SKIPPED_BY_USER.value}
    assert _integrity(controller._history) == []


def test_skip_all_for_the_current_queue(controller, tmp_path):
    tasks = _pending(controller, 5, tmp_path)

    controller.apply_batch_policy(DuplicatePolicy.SKIP_ALL_FOR_QUEUE)

    assert all(task.state is TaskState.SKIPPED_BY_USER for task in tasks)
    assert controller.pending_review() == []
    assert _integrity(controller._history) == []


def test_skip_after_clearing_the_history(controller, tmp_path):
    """Exactly the reported sequence: review, clear history, skip."""
    tasks = _pending(controller, 3, tmp_path)
    controller.clear_history()

    controller.skip_all()

    assert all(task.state is TaskState.SKIPPED_BY_USER for task in tasks)
    assert _integrity(controller._history) == []


def test_skip_of_playlist_children_keeps_the_parent_consistent(controller, tmp_path):
    job = PlaylistJob(title='Mix', source_url='https://example.com/list')
    children = []
    for index in range(4):
        task = _task(controller, title=f'p{index}')
        task.request.playlist_title = 'Mix'
        task.request.playlist_index = index + 1
        children.append(task)
    controller.enqueue(children, autostart=False, playlist=job)

    children[0].state = TaskState.FINISHED
    children[1].state = TaskState.ERROR
    for task in children[2:]:
        task.state = TaskState.NEEDS_REVIEW
    for task in children:
        controller._persist(task.id)

    controller.skip([task.id for task in children[2:]])

    assert [task.state for task in children[2:]] \
        == [TaskState.SKIPPED_BY_USER, TaskState.SKIPPED_BY_USER]
    assert job.completed_items == 1
    assert job.failed_items == 1
    for task in children:
        assert controller._history.get(task.id).playlist_id == job.id
    assert _integrity(controller._history) == []


def test_a_storage_failure_is_reported_instead_of_raising(controller, tmp_path, monkeypatch):
    """A broken database must not take the GUI action down with it."""
    task = _task(controller, title='One')
    controller.enqueue([task], autostart=False)

    reported: list[str] = []
    controller.persistenceFailed.connect(reported.append)

    def boom(_record):
        raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(controller._history, 'update', boom)
    task.state = TaskState.SKIPPED_BY_USER
    controller._persist(task.id)

    assert reported, 'the failure must reach the interface'
    assert task.state is TaskState.SKIPPED_BY_USER


def test_batch_actions_touch_each_item_once(controller, tmp_path):
    """One click, one decision: no overlapping skip paths."""
    tasks = _pending(controller, 3, tmp_path)
    seen: list[str] = []
    controller.taskChanged.connect(seen.append)

    controller.apply_batch_policy(DuplicatePolicy.SKIP_ALL_FOR_QUEUE)

    assert sorted(seen) == sorted(task.id for task in tasks)


# ------------------------------------------------------------------- shutdown


def test_the_download_thread_is_never_terminated():
    """`QThread.terminate()` on a thread running Python kills the process later.

    That is the second half of the report: a stream of IntegrityErrors while a
    download was running, then `Bus error (core dumped)` on the way out.
    """
    import inspect

    from app.core import download_controller

    source = inspect.getsource(download_controller.DownloadController.shutdown)
    assert 'self._thread.terminate' not in source
    assert 'wait(SHUTDOWN_TIMEOUT_MS)' in source


def test_a_cancel_request_can_actually_be_noticed(qapp, tmp_path):
    """Without a socket timeout an unresponsive host pins the thread forever."""
    from app.core.ytdlp_service import SOCKET_TIMEOUT

    service = YtDlpService(AppSettings(output_dir=str(tmp_path)))
    assert service.base_options()['socket_timeout'] == SOCKET_TIMEOUT
    assert 0 < SOCKET_TIMEOUT <= 60


def test_shutdown_returns_while_a_worker_is_busy(qapp, tmp_path):
    """A cooperative cancel is honoured, so shutdown never has to force anything."""
    import time

    from yt_dlp.utils import DownloadCancelled

    settings = AppSettings(output_dir=str(tmp_path))
    service = YtDlpService(settings)

    def slow_download(_request, callbacks, _logger=None):
        for _ in range(400):
            if callbacks.is_cancelled and callbacks.is_cancelled():
                raise DownloadCancelled('cancelled')
            time.sleep(0.01)
        raise AssertionError('the cancel request was ignored')

    service.download = slow_download
    controller = DownloadController(service, history=HistoryStore(tmp_path / 'h.db'))
    controller.enqueue([_task(controller, title='Busy')])
    qapp.processEvents()
    time.sleep(0.1)

    started = time.monotonic()
    controller.shutdown()
    assert time.monotonic() - started < 10
