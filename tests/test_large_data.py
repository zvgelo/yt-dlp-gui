"""Stress tests: a thousand history records, queue items and playlist entries.

Nothing here touches the network. The point is not raw speed but shape: an
operation that is fine with a hundred items must not become unusable with a
thousand, and the database must stay referentially intact under load.

The timing assertions are deliberately loose. They exist to catch a change of
complexity, not to measure this machine.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QApplication

from app.core.download_controller import DownloadController
from app.core.duplicates import DuplicatePolicy
from app.core.history import HistoryRecord, HistoryStore, MediaIdentity, PlaylistRecord
from app.core.models import DownloadRequest, DownloadTask, MediaKind, PlaylistJob
from app.core.ytdlp_service import YtDlpService, build_playlist_info
from app.gui.queue_model import QueueFilter, QueueFilterProxy, QueueModel
from app.settings import AppSettings
from app.state import ACTIVE_TASK_STATES, TaskState

#: The size every "large" scenario uses
LARGE = 1000

#: A realistic mixture: most downloads succeed, the rest spread over the states
#: the interface has to render
STATUS_MIX = (
    [TaskState.FINISHED] * 10
    + [TaskState.COMPLETED_WITH_ERRORS] * 3
    + [TaskState.ERROR] * 3
    + [TaskState.INTERRUPTED] * 2
    + [TaskState.SKIPPED_DUPLICATE] * 2
    + [TaskState.SKIPPED_BY_USER] * 2
    + [TaskState.NEEDS_REVIEW] * 2
    + [TaskState.CANCELLED]
)


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / 'history.db')


@pytest.fixture
def controller(qapp, tmp_path):
    settings = AppSettings(output_dir=str(tmp_path), job_retries=0, job_retry_delay=0)
    controller = DownloadController(YtDlpService(settings),
                                    history=HistoryStore(tmp_path / 'history.db'))
    # Paused, so nothing starts running and every item stays inspectable
    controller.pause()
    yield controller
    controller.shutdown()


class Timer:
    """Wall-clock timing without a benchmark framework."""

    def __init__(self, label: str):
        self.label = label
        self.seconds = 0.0

    def __enter__(self):
        self._started = time.monotonic()
        return self

    def __exit__(self, *_exc):
        self.seconds = time.monotonic() - self._started
        print(f'    {self.label}: {self.seconds * 1000:.0f} ms')
        return False


def _history_records(count: int = LARGE) -> tuple[list[PlaylistRecord], list[HistoryRecord]]:
    """A realistic history: loose downloads plus a few playlists with children."""
    playlists = [PlaylistRecord(id=f'pl-{index}', title=f'Playlist {index}',
                                source_url=f'https://example.com/list/{index}',
                                total_items=25, created_at='2026-01-01T00:00:00+00:00')
                 for index in range(count // 25)]
    records = []
    for index in range(count):
        status = STATUS_MIX[index % len(STATUS_MIX)]
        audio = index % 3 == 0
        # Every fourth item belongs to a playlist, so both shapes are covered
        playlist = playlists[index // 25] if index % 4 == 0 and playlists else None
        records.append(HistoryRecord(
            id=f'rec-{index:05}',
            source_url=f'https://example.com/watch?v=vid{index:05}',
            canonical_url=f'https://example.com/watch?v=vid{index:05}',
            status=status.value,
            extractor='Youtube',
            media_id=f'vid{index:05}',
            media_kind=MediaKind.AUDIO.value if audio else MediaKind.VIDEO.value,
            output_format='mp3' if audio else 'mp4',
            quality=0 if audio else 1080,
            title=f'Item {index}',
            uploader=f'Uploader {index % 40}',
            duration=float(60 + index % 600),
            output_directory='/tmp/out',
            final_path=f'/tmp/out/Item {index}.{"mp3" if audio else "mp4"}',
            playlist_id=playlist.id if playlist else None,
            playlist_title=playlist.title if playlist else '',
            playlist_index=(index % 25) + 1 if playlist else None,
            created_at=f'2026-01-01T00:{index // 60 % 60:02}:{index % 60:02}+00:00',
            attempt_count=1 if status is TaskState.FINISHED else 2,
        ))
    return playlists, records


def _fill(store: HistoryStore, count: int = LARGE) -> tuple[list[PlaylistRecord],
                                                            list[HistoryRecord]]:
    playlists, records = _history_records(count)
    by_playlist: dict[str, list[HistoryRecord]] = {}
    loose: list[HistoryRecord] = []
    for record in records:
        if record.playlist_id:
            by_playlist.setdefault(record.playlist_id, []).append(record)
        else:
            loose.append(record)
    store.add_many(loose)
    for playlist in playlists:
        store.save_playlist_with_items(playlist, by_playlist.get(playlist.id, []))
    return playlists, records


def _integrity(store: HistoryStore) -> list:
    return store._connection().execute('PRAGMA foreign_key_check').fetchall()


# ------------------------------------------------------------ 1000 history records


def test_writing_a_thousand_records(store):
    with Timer('write 1000 history records') as timer:
        playlists, _records = _fill(store)
    assert store.count() == LARGE
    assert len(playlists) == LARGE // 25
    assert timer.seconds < 5.0


def test_reading_sorting_and_filtering_a_thousand_records(store):
    _fill(store)

    with Timer('read 1000 records, newest first') as read:
        rows = store.list(limit=LARGE)
    assert len(rows) == LARGE
    # `list()` sorts newest first; the generator counts minutes upwards
    assert [row.id for row in rows] == sorted((row.id for row in rows), reverse=True)
    assert read.seconds < 2.0

    with Timer('filter by status') as filtered:
        finished = store.list(limit=LARGE, statuses=[TaskState.FINISHED.value])
    assert finished
    assert all(row.status == TaskState.FINISHED.value for row in finished)
    assert filtered.seconds < 2.0

    with Timer('duplicate lookup by identity') as lookup:
        for index in range(0, LARGE, 50):
            found = store.find_by_identity(MediaIdentity('Youtube', f'vid{index:05}'))
            assert len(found) == 1
    assert lookup.seconds < 2.0


def test_playlist_parents_and_children_survive_a_thousand_records(store):
    playlists, _ = _fill(store)

    stored = store.list_playlists(limit=LARGE)
    assert len(stored) == len(playlists)

    for playlist in stored:
        children = [row for row in store.list(limit=LARGE) if row.playlist_id == playlist.id]
        assert children, f'{playlist.id} lost its items'
        assert all(child.playlist_title == playlist.title for child in children)


def test_the_database_stays_intact_under_load(store):
    _fill(store)
    connection = store._connection()

    assert _integrity(store) == []
    orphan_children = connection.execute(
        'SELECT COUNT(*) FROM records WHERE playlist_id IS NOT NULL AND playlist_id NOT IN '
        '(SELECT id FROM playlists)').fetchone()[0]
    assert orphan_children == 0
    orphan_attempts = connection.execute(
        'SELECT COUNT(*) FROM attempts WHERE record_id NOT IN (SELECT id FROM records)'
    ).fetchone()[0]
    assert orphan_attempts == 0
    dangling_duplicates = connection.execute(
        "SELECT COUNT(*) FROM records WHERE duplicate_of_record_id <> '' "
        'AND duplicate_of_record_id NOT IN (SELECT id FROM records)').fetchone()[0]
    assert dangling_duplicates == 0


def test_startup_restores_a_thousand_records(controller):
    _fill(controller._history)

    with Timer('restore 1000 records into the queue') as timer:
        restored = controller.restore_history(limit=LARGE)

    assert restored == LARGE
    assert len(controller.tasks) == LARGE
    assert len(controller.playlists) == LARGE // 25
    # In-progress rows from a previous session must not look runnable
    assert not [task for task in controller.tasks if task.state in ACTIVE_TASK_STATES]
    assert timer.seconds < 10.0


# --------------------------------------------------------------- 1000 queue items


def _queue(controller, count: int, *, prefix: str = 'q') -> list[DownloadTask]:
    tasks = [
        DownloadTask(
            request=DownloadRequest(url=f'https://example.com/watch?v={prefix}{index:05}',
                                    output_dir=controller._service.settings.output_dir,
                                    kind=MediaKind.AUDIO if index % 3 == 0 else MediaKind.VIDEO),
            title=f'{prefix} {index}', media_id=f'{prefix}{index:05}', extractor='Youtube')
        for index in range(count)
    ]
    controller.enqueue(tasks, autostart=False)
    return tasks


def test_building_a_thousand_queue_items(controller):
    with Timer('enqueue 1000 items') as timer:
        tasks = _queue(controller, LARGE)

    assert len(controller.tasks) == LARGE
    # Insertion order is preserved: the queue is a queue
    assert [task.id for task in controller.tasks] == [task.id for task in tasks]
    assert controller.index_of(tasks[-1].id) == LARGE - 1
    assert timer.seconds < 15.0


def test_the_queue_does_not_degrade_from_a_hundred_to_a_thousand(qapp, tmp_path):
    """A ten times larger queue may not cost far more than ten times as much."""
    def measure(count: int) -> float:
        settings = AppSettings(output_dir=str(tmp_path), job_retries=0)
        controller = DownloadController(
            YtDlpService(settings), history=HistoryStore(tmp_path / f'h{count}.db'))
        try:
            controller.pause()
            started = time.monotonic()
            _queue(controller, count, prefix=f's{count}')
            return time.monotonic() - started
        finally:
            controller.shutdown()

    small = measure(100)
    large = measure(LARGE)
    print(f'    100 items: {small * 1000:.0f} ms, 1000 items: {large * 1000:.0f} ms, '
          f'ratio {large / max(small, 1e-6):.1f}x')
    # Linear would be 10x; allow generous headroom but catch quadratic growth
    assert large < small * 40


def test_filtering_a_thousand_items(qapp, controller):
    tasks = _queue(controller, LARGE)
    for index, task in enumerate(tasks):
        task.state = STATUS_MIX[index % len(STATUS_MIX)]

    model = QueueModel(controller)
    proxy = QueueFilterProxy()
    proxy.setSourceModel(model)

    with Timer('filter 1000 items across every tab') as timer:
        counts = {}
        for queue_filter in (QueueFilter.ALL, QueueFilter.IN_PROGRESS,
                             QueueFilter.NEEDS_REVIEW, QueueFilter.FAILED,
                             QueueFilter.VIDEO, QueueFilter.AUDIO, QueueFilter.COMPLETED):
            proxy.set_filter(queue_filter)
            counts[queue_filter] = proxy.rowCount()

    assert counts[QueueFilter.ALL] == LARGE
    assert counts[QueueFilter.FAILED] == sum(1 for task in tasks if task.state.is_failed)
    assert counts[QueueFilter.NEEDS_REVIEW] == len(controller.pending_review())
    assert counts[QueueFilter.VIDEO] + counts[QueueFilter.AUDIO] == LARGE
    assert timer.seconds < 5.0

    with Timer('search 1000 items') as search:
        proxy.set_filter(QueueFilter.ALL)
        proxy.set_search('q 999')
    assert proxy.rowCount() == 1
    assert search.seconds < 2.0


def test_batch_decisions_on_a_thousand_items(controller):
    tasks = _queue(controller, LARGE)
    for task in tasks:
        task.state = TaskState.NEEDS_REVIEW
    assert len(controller.pending_review()) == LARGE

    with Timer('skip 1000 reviews') as timer:
        controller.skip_all()

    assert controller.pending_review() == []
    assert all(task.state is TaskState.SKIPPED_BY_USER for task in tasks)
    assert _integrity(controller._history) == []
    assert timer.seconds < 20.0


def test_a_batch_policy_covers_a_thousand_items(controller):
    tasks = _queue(controller, LARGE)
    for task in tasks:
        task.state = TaskState.NEEDS_REVIEW

    with Timer('apply a batch policy to 1000 items') as timer:
        controller.apply_batch_policy(DuplicatePolicy.SKIP_ALL_FOR_QUEUE)

    assert all(task.state is TaskState.SKIPPED_BY_USER for task in tasks)
    assert timer.seconds < 20.0


def test_retrying_a_thousand_failures(controller):
    tasks = _queue(controller, LARGE)
    for task in tasks:
        task.state = TaskState.ERROR
    assert len(controller.failed_tasks()) == LARGE

    with Timer('retry 1000 failures') as timer:
        controller.retry_all_failed()

    assert controller.failed_tasks() == []
    assert timer.seconds < 20.0


def test_reservations_scale_to_a_thousand_items(controller):
    tasks = _queue(controller, LARGE)
    reserved = controller.duplicates._reserved
    # Every item holds exactly one artifact while it waits in the queue
    assert len(reserved) == LARGE

    controller.remove([task.id for task in tasks[:500]])
    assert len(controller.duplicates._reserved) == LARGE - 500


def test_removing_five_hundred_items(controller):
    tasks = _queue(controller, LARGE)

    with Timer('remove 500 of 1000 items') as timer:
        controller.remove([task.id for task in tasks[:500]])

    assert len(controller.tasks) == LARGE - 500
    assert controller.tasks[0].id == tasks[500].id
    assert controller._history.count() == LARGE - 500
    assert timer.seconds < 15.0


# ------------------------------------------------------------------ large playlist


def _entries(count: int, *, fail_at: int | None = None):
    """A generator, so the caller decides how much of the playlist is read."""
    def generate():
        for index in range(1, count + 1):
            if fail_at is not None and index == fail_at:
                raise RuntimeError(f'page {index // 100}: Unable to download API page')
            yield {'_type': 'url', 'id': f'pv{index:05}', 'title': f'Track {index}',
                   'url': f'https://www.youtube.com/watch?v=pv{index:05}&list=PL1',
                   'ie_key': 'Youtube', 'duration': 200}
    return generate()


def test_a_thousand_entry_playlist_is_read_lazily():
    with Timer('read a 1000 entry playlist') as timer:
        info = build_playlist_info('https://www.youtube.com/playlist?list=PL1', {
            '_type': 'playlist', 'title': 'Big list', 'entries': _entries(LARGE)})

    assert info.is_playlist
    assert len(info.entries) == LARGE
    assert info.entries_complete
    # Children are canonical, so none of them re-enumerates the parent
    assert all('list=' not in entry.download_url for entry in info.entries)
    assert timer.seconds < 5.0


def test_a_partially_read_playlist_keeps_what_it_found():
    info = build_playlist_info('https://www.youtube.com/playlist?list=PL1', {
        '_type': 'playlist', 'title': 'Big list',
        'entries': _entries(LARGE, fail_at=640)})

    assert len(info.entries) == 639
    assert info.entries_complete is False
    assert info.entries_error


def test_the_generator_is_not_materialised_up_front():
    consumed = []

    def watched():
        for index in range(1, LARGE + 1):
            consumed.append(index)
            yield {'_type': 'url', 'id': f'pv{index:05}', 'title': f'Track {index}',
                   'url': f'https://www.youtube.com/watch?v=pv{index:05}', 'ie_key': 'Youtube'}

    raw = {'_type': 'playlist', 'title': 'Big list', 'entries': watched()}
    assert consumed == []
    build_playlist_info('https://www.youtube.com/playlist?list=PL1', raw)
    assert len(consumed) == LARGE


def test_a_large_playlist_stays_one_parent_record(controller):
    entries = list(_entries(LARGE))
    job = PlaylistJob(title='Big list', source_url='https://www.youtube.com/playlist?list=PL1',
                      discovered_items=LARGE)
    tasks = [
        DownloadTask(
            request=DownloadRequest(url=entry['url'],
                                    output_dir=controller._service.settings.output_dir,
                                    playlist_title=job.title, playlist_index=index + 1),
            title=entry['title'], media_id=entry['id'], extractor='Youtube')
        for index, entry in enumerate(entries)
    ]

    with Timer('enqueue a 1000 item playlist') as timer:
        controller.enqueue(tasks, autostart=False, playlist=job)

    assert len(controller.playlists) == 1
    assert len(job.tasks) == LARGE
    assert controller._history.count() == LARGE
    assert len(controller._history.list_playlists(limit=10)) == 1
    assert timer.seconds < 20.0

    for index, task in enumerate(tasks):
        task.state = STATUS_MIX[index % len(STATUS_MIX)]

    with Timer('recompute the parent counters') as counters:
        completed, failed, total = job.completed_items, job.failed_items, job.total_items

    assert completed == sum(1 for task in tasks if task.state.is_ok)
    assert failed == sum(1 for task in tasks if task.state.is_failed)
    assert total == LARGE
    assert counters.seconds < 1.0

    job.enumeration_complete = False
    assert job.total_items is None, 'a partial enumeration must not claim a total'
    assert _integrity(controller._history) == []
