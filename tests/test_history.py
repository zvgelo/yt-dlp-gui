"""Tests for the persistent download history (SQLite) and restart recovery."""

from __future__ import annotations

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication

from app.core.history import (
    SCHEMA_VERSION,
    HistoryRecord,
    HistoryStore,
    MediaIdentity,
    PlaylistRecord,
)
from app.core.history_mapper import record_from_task, task_from_record
from app.core.models import DownloadRequest, DownloadTask, MediaKind, PlaylistJob
from app.core.ytdlp_service import YtDlpService
from app.settings import AppSettings
from app.state import ACTIVE_TASK_STATES, TaskState


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    return tmp_path / 'history.db'


@pytest.fixture
def store(db):
    return HistoryStore(db)


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


def _task(**kwargs) -> DownloadTask:
    request_keys = {'output_dir', 'kind', 'audio_format', 'container', 'quality',
                    'playlist_title', 'playlist_index'}
    request_args = {k: kwargs.pop(k) for k in list(kwargs) if k in request_keys}
    request_args.setdefault('output_dir', '/tmp/out')
    return DownloadTask(request=DownloadRequest(url='https://example.com/v', **request_args),
                        **kwargs)


# ------------------------------------------------------------------- schemat


def test_the_database_is_created_with_a_schema_version(db):
    HistoryStore(db)
    with sqlite3.connect(db) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION


def test_reopening_does_not_erase_the_data(db):
    HistoryStore(db).add(_record('a'))
    assert HistoryStore(db).count() == 1


def test_indexes_for_duplicate_lookups_exist(db):
    HistoryStore(db)
    with sqlite3.connect(db) as connection:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
    assert 'idx_records_identity' in names
    assert 'idx_records_status' in names


# ------------------------------------------------------------- podstawy CRUD


def test_write_and_read(store):
    store.add(_record('a', title='Title', final_path='/tmp/a.mp4'))
    record = store.get('a')
    assert record.title == 'Title'
    assert record.final_name == 'a.mp4'


def test_listing_starts_with_the_newest(store):
    store.add(_record('stary', created_at='2026-01-01T10:00:00+00:00'))
    store.add(_record('nowy', created_at='2026-06-01T10:00:00+00:00'))
    assert [r.id for r in store.list()] == ['nowy', 'stary']


def test_filtering_by_status(store):
    store.add(_record('ok'))
    store.add(_record('zly', status=TaskState.ERROR.value))
    assert [r.id for r in store.list(statuses=[TaskState.ERROR.value])] == ['zly']


def test_an_update_overwrites_the_record(store):
    store.add(_record('a', status=TaskState.QUEUED.value))
    store.update(_record('a', status=TaskState.FINISHED.value, final_path='/tmp/a.mp4'))
    assert store.count() == 1
    assert store.get('a').status == TaskState.FINISHED.value


# --------------------------------------------------------------- duplikaty


def test_lookup_by_media_identity(store):
    store.add(_record('a', media_id='abc123', final_path='/tmp/a.mp4'))
    store.add(_record('b', media_id='inne'))
    found = store.find_by_identity(MediaIdentity('Youtube', 'abc123'))
    assert [r.id for r in found] == ['a']


def test_an_identity_without_an_id_finds_nothing(store):
    store.add(_record('a', media_id=''))
    assert store.find_by_identity(MediaIdentity('Youtube', '')) == []


def test_a_history_record_does_not_prove_the_file_exists(store, tmp_path):
    istniejacy = tmp_path / 'jest.mp4'
    istniejacy.write_text('x')
    store.add(_record('a', final_path=str(istniejacy)))
    store.add(_record('b', final_path=str(tmp_path / 'nie-ma.mp4')))

    assert store.get('a').file_exists() is True
    assert store.get('b').file_exists() is False


# ---------------------------------------------------------------- playlisty


def test_a_playlist_is_stored_with_its_items(store):
    playlist = PlaylistRecord(id='p1', title='Lista', source_url='https://example.com/l')
    items = [_record(f'v{i}', playlist_id='p1', playlist_index=i) for i in range(1, 4)]
    store.save_playlist_with_items(playlist, items)

    assert [p.title for p in store.list_playlists()] == ['Lista']
    assert len([r for r in store.list() if r.playlist_id == 'p1']) == 3


def test_removing_the_items_deletes_the_empty_playlist(store):
    playlist = PlaylistRecord(id='p1', title='Lista', source_url='u')
    store.save_playlist_with_items(playlist, [_record('v1', playlist_id='p1')])
    store.delete(['v1'])
    assert store.list_playlists() == []


# --------------------------------------------------------------- czyszczenie


def test_clear_does_not_touch_the_files(store, tmp_path):
    downloaded = tmp_path / 'movie.mp4'
    downloaded.write_text('data')
    store.add(_record('a', final_path=str(downloaded)))

    store.clear()
    assert store.count() == 0
    assert downloaded.exists(), 'clearing history must never delete downloaded files'


def test_removing_a_single_entry_does_not_touch_the_file(store, tmp_path):
    downloaded = tmp_path / 'movie.mp4'
    downloaded.write_text('data')
    store.add(_record('a', final_path=str(downloaded)))
    store.add(_record('b'))

    assert store.delete(['a']) == 1
    assert store.count() == 1
    assert downloaded.exists()


def test_clearing_by_status(store):
    store.add(_record('ok'))
    store.add(_record('zly', status=TaskState.ERROR.value))
    store.delete_by_status([TaskState.ERROR.value])
    assert [r.id for r in store.list()] == ['ok']


# ------------------------------------------------------- restart recovery


def test_an_interrupted_download_does_not_pose_as_active(store):
    """Nothing may hang around as active after a restart, queued items included,

    because otherwise the application would start downloading right away.
    """
    store.add(_record('a', status=TaskState.DOWNLOADING.value))
    store.add(_record('b', status=TaskState.POSTPROCESSING.value))
    store.add(_record('c', status=TaskState.QUEUED.value))
    store.add(_record('d', status=TaskState.FINISHED.value))

    changed = store.recover_interrupted(
        [state.value for state in ACTIVE_TASK_STATES], TaskState.INTERRUPTED.value)

    assert changed == 3
    for record_id in ('a', 'b', 'c'):
        assert store.get(record_id).status == TaskState.INTERRUPTED.value
    assert store.get('d').status == TaskState.FINISHED.value


def test_the_interrupted_state_is_final():
    assert TaskState.INTERRUPTED.is_final is True
    assert TaskState.INTERRUPTED.is_active is False
    assert TaskState.INTERRUPTED.is_ok is False


# ------------------------------------------------------------- konwersja


def test_full_round_trip_task_record_task():
    task = _task(kind=MediaKind.AUDIO, audio_format='mp3', quality=192,
                 playlist_title='Lista', playlist_index=3,
                 title='Track', uploader='Author', media_id='abc', extractor='Youtube',
                 state=TaskState.FINISHED, filepath='/tmp/out/List/003 - Track.mp3')
    restored = task_from_record(record_from_task(task))

    assert restored.id == task.id
    assert restored.state is TaskState.FINISHED
    assert restored.request.kind is MediaKind.AUDIO
    assert restored.request.audio_format == 'mp3'
    assert restored.request.playlist_index == 3
    assert restored.filepath == task.filepath


def test_history_remembers_the_real_filename():
    """The name is not rebuilt from settings; the one produced is stored."""
    task = _task(playlist_title='Lista', filepath='/out/Lista/007 - Song.mp4',
                 state=TaskState.FINISHED)
    record = record_from_task(task)
    assert record.final_path == '/out/Lista/007 - Song.mp4'
    assert record.final_name == '007 - Song.mp4'


# --------------------------------------------------- integracja z kontrolerem


@pytest.fixture
def controller(qapp, db):
    from app.core.download_controller import DownloadController

    ctl = DownloadController(YtDlpService(AppSettings()), history=HistoryStore(db))
    yield ctl
    ctl.shutdown()


def test_the_queue_lands_in_history(controller, db):
    controller.pause()
    controller.enqueue([_task(title='A'), _task(title='B')], autostart=False)
    assert HistoryStore(db).count() == 2


def test_history_comes_back_after_a_restart(qapp, db):
    from app.core.download_controller import DownloadController

    first = DownloadController(YtDlpService(AppSettings()), history=HistoryStore(db))
    first.pause()
    finished = _task(title='Completed', state=TaskState.FINISHED)
    failed = _task(title='Failed', state=TaskState.ERROR)
    first.enqueue([finished, failed], autostart=False)
    first.shutdown()

    # Druga sesja aplikacji
    second = DownloadController(YtDlpService(AppSettings()), history=HistoryStore(db))
    try:
        assert second.restore_history() == 2
        titles = {task.title for task in second.tasks}
        assert titles == {'Completed', 'Failed'}
    finally:
        second.shutdown()


def test_a_playlist_is_one_entry_after_a_restart(qapp, db):
    from app.core.download_controller import DownloadController

    first = DownloadController(YtDlpService(AppSettings()), history=HistoryStore(db))
    first.pause()
    tasks = [_task(title=f'Track {i}', state=TaskState.FINISHED) for i in range(5)]
    job = PlaylistJob(title='Moja playlista', source_url='https://example.com/l')
    first.enqueue(tasks, autostart=False, playlist=job)
    first.shutdown()

    second = DownloadController(YtDlpService(AppSettings()), history=HistoryStore(db))
    try:
        second.restore_history()
        assert len(second.playlists) == 1, 'a playlist must not fall apart into single files'
        assert second.playlists[0].title == 'Moja playlista'
        assert len(second.playlists[0].tasks) == 5
        assert len(second.tasks) == 5
    finally:
        second.shutdown()


def test_a_duplicate_is_visible_in_the_next_session(qapp, db):
    from app.core.download_controller import DownloadController

    first = DownloadController(YtDlpService(AppSettings()), history=HistoryStore(db))
    first.pause()
    task = _task(title='Film', media_id='abc123', extractor='Youtube',
                 state=TaskState.FINISHED, filepath='/tmp/abc123.mp4')
    first.enqueue([task], autostart=False)
    first.shutdown()

    # A new session: history still knows this media was downloaded
    store = HistoryStore(db)
    found = store.find_by_identity(MediaIdentity('Youtube', 'abc123'))
    assert len(found) == 1
    assert found[0].final_path == '/tmp/abc123.mp4'


def test_an_interrupted_job_after_a_restart(qapp, db):
    from app.core.download_controller import DownloadController

    store = HistoryStore(db)
    store.add(_record('a', status=TaskState.DOWNLOADING.value))

    controller = DownloadController(YtDlpService(AppSettings()), history=HistoryStore(db))
    try:
        controller.restore_history()
        assert controller.tasks[0].state is TaskState.INTERRUPTED
    finally:
        controller.shutdown()


def test_clear_history_from_the_controller(controller, db):
    controller.pause()
    controller.enqueue([_task(title='A', state=TaskState.FINISHED)], autostart=False)
    controller.clear_history()

    assert HistoryStore(db).count() == 0
    assert controller.tasks == []


def test_removing_an_item_deletes_its_record(controller, db):
    controller.pause()
    task = _task(title='A', state=TaskState.FINISHED)
    controller.enqueue([task], autostart=False)
    controller.remove([task.id])
    assert HistoryStore(db).count() == 0


# ------------------------------------------------------------- lokalizacja


def test_the_database_lives_in_the_application_data_folder(qapp, tmp_path, monkeypatch):
    """`~/.local/share/yt-dlp-gui/history.db`, not the project directory."""
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    from app.paths import app_data_dir, history_path

    directory = app_data_dir()
    assert directory.name == 'yt-dlp-gui'
    # The name must not be doubled (AppDataLocation appends org and app)
    assert directory.parent.name != 'yt-dlp-gui'
    assert history_path().name == 'history.db'


# --------------------------------------------------------------- migracje


_LEGACY_RECORDS_TABLE = """
CREATE TABLE records (
    id TEXT PRIMARY KEY, source_url TEXT NOT NULL, status TEXT NOT NULL,
    extractor TEXT NOT NULL DEFAULT '', media_id TEXT NOT NULL DEFAULT '',
    media_kind TEXT NOT NULL DEFAULT 'video', output_format TEXT NOT NULL DEFAULT '',
    quality INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL DEFAULT '',
    uploader TEXT NOT NULL DEFAULT '', duration REAL,
    thumbnail_url TEXT NOT NULL DEFAULT '', canonical_url TEXT NOT NULL DEFAULT '',
    output_directory TEXT NOT NULL DEFAULT '', final_path TEXT NOT NULL DEFAULT '',
    playlist_id TEXT, playlist_title TEXT NOT NULL DEFAULT '', playlist_index INTEGER,
    created_at TEXT NOT NULL, started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '', attempt_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '', error_message TEXT NOT NULL DEFAULT '',
    duplicate_of_record_id TEXT NOT NULL DEFAULT '')
"""


def _legacy_database(path):
    """Database as written by an earlier release: no attempts table, fewer columns."""
    with sqlite3.connect(path) as connection:
        connection.executescript(_LEGACY_RECORDS_TABLE)
        connection.execute(
            "INSERT INTO records (id, source_url, status, created_at) "
            "VALUES ('legacy', 'https://example.com/v', 'finished', '2026-01-01T00:00:00+00:00')")
        connection.execute('PRAGMA user_version=1')


def test_migration_adds_missing_columns(db):
    """CREATE TABLE IF NOT EXISTS leaves an existing table alone; columns must be added."""
    _legacy_database(db)
    store = HistoryStore(db)

    store.add(_record('nowy', status='needs_review', duplicate_kind='other_target'))
    assert store.get('nowy').duplicate_kind == 'other_target'


def test_migration_preserves_the_data(db):
    _legacy_database(db)
    store = HistoryStore(db)

    assert store.get('legacy') is not None
    assert store.get('legacy').status == TaskState.FINISHED.value


def test_migration_creates_a_missing_table(db):
    _legacy_database(db)
    store = HistoryStore(db)

    store.save_attempts('legacy', [])
    assert store.load_attempts('legacy') == []


def test_migration_bumps_the_version(db):
    _legacy_database(db)
    HistoryStore(db)
    with sqlite3.connect(db) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION


def test_a_database_from_a_newer_version_is_left_alone(db):
    HistoryStore(db)
    with sqlite3.connect(db) as connection:
        connection.execute('PRAGMA user_version=99')

    HistoryStore(db)
    with sqlite3.connect(db) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 99


# ------------------------------------------------- kontekst decyzji po restarcie


def test_a_pending_decision_keeps_the_file_reference(qapp, db):
    """After a restart a "Needs review" card must still know what it conflicts with."""
    from app.core.download_controller import DownloadController

    store = HistoryStore(db)
    store.add(_record('istniejacy', final_path='/media/A/film.mp4'))
    store.add(_record('konflikt', status=TaskState.NEEDS_REVIEW.value,
                      duplicate_kind='other_target', duplicate_of_record_id='istniejacy'))

    controller = DownloadController(YtDlpService(AppSettings()), history=HistoryStore(db))
    try:
        controller.restore_history()
        pending = controller.pending_review()
        assert len(pending) == 1
        assert pending[0].duplicate_of_path == '/media/A/film.mp4'
        assert pending[0].duplicate_kind == 'other_target'
    finally:
        controller.shutdown()


def test_reloading_history_does_not_duplicate_entries(qapp, db):
    from app.core.download_controller import DownloadController

    store = HistoryStore(db)
    store.add(_record('a'))
    controller = DownloadController(YtDlpService(AppSettings()), history=HistoryStore(db))
    try:
        assert controller.restore_history() == 1
        # The second call must add nothing and report no false count
        assert controller.restore_history() == 0
        assert len(controller.tasks) == 1
    finally:
        controller.shutdown()
