"""Persistent download history in an SQLite database.

The layer deliberately knows nothing about Qt; the caller supplies the file
path (`app/paths.py`). History is part of the application logic rather than
mere serialisation of GUI cards: it also drives duplicate detection and
restores the playlist-to-item relation.

Threads: every thread gets its own connection (`threading.local`) and the
database runs in WAL mode, so a download worker can write in parallel with
the GUI thread.

Writes are true upserts (`INSERT ... ON CONFLICT DO UPDATE`), never
`INSERT OR REPLACE`. REPLACE is destructive: on a primary-key conflict SQLite
deletes the existing row before inserting the new one, which runs the
`ON DELETE CASCADE` from `attempts.record_id` and silently wipes the attempt
history, and re-checks `records.playlist_id` as if the row were new.
"""

from __future__ import annotations

import dataclasses
import functools
import re
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path

#: Wersja schematu trzymana w `PRAGMA user_version`
SCHEMA_VERSION = 3

#: How many records are loaded at start-up (newest first)
DEFAULT_LIMIT = 1000


def now_iso() -> str:
    """A UTC timestamp: comparable and independent of the user time zone."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@dataclasses.dataclass
class MediaIdentity:
    """Media identity at the provider; the basis of duplicate detection."""

    extractor: str = ''
    media_id: str = ''

    @property
    def is_valid(self) -> bool:
        return bool(self.media_id)

    @property
    def key(self) -> str:
        return f'{self.extractor.lower()}:{self.media_id}' if self.is_valid else ''


@dataclasses.dataclass
class HistoryRecord:
    """A single history entry: one downloaded or attempted media item."""

    id: str
    source_url: str
    status: str

    extractor: str = ''
    media_id: str = ''
    media_kind: str = 'video'
    output_format: str = ''
    quality: int = 0

    title: str = ''
    uploader: str = ''
    duration: float | None = None
    thumbnail_url: str = ''
    canonical_url: str = ''

    output_directory: str = ''
    final_path: str = ''

    playlist_id: str | None = None
    playlist_title: str = ''
    playlist_index: int | None = None

    created_at: str = dataclasses.field(default_factory=now_iso)
    started_at: str = ''
    completed_at: str = ''
    attempt_count: int = 0

    error_code: str = ''
    error_message: str = ''
    duplicate_of_record_id: str = ''
    duplicate_kind: str = ''

    @property
    def identity(self) -> MediaIdentity:
        return MediaIdentity(self.extractor, self.media_id)

    @property
    def final_name(self) -> str:
        return Path(self.final_path).name if self.final_path else ''

    def file_exists(self) -> bool:
        """A history record does not prove the file is still on disk."""
        return bool(self.final_path) and Path(self.final_path).exists()


@dataclasses.dataclass
class PlaylistRecord:
    """A playlist as a parent job."""

    id: str
    title: str
    source_url: str

    status: str = ''
    uploader: str = ''
    thumbnail_url: str = ''
    total_items: int | None = None
    enumeration_complete: bool = True
    enumeration_error: str = ''
    created_at: str = dataclasses.field(default_factory=now_iso)
    completed_at: str = ''


_SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id                   TEXT PRIMARY KEY,
    title                TEXT NOT NULL DEFAULT '',
    source_url           TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT '',
    uploader             TEXT NOT NULL DEFAULT '',
    thumbnail_url        TEXT NOT NULL DEFAULT '',
    total_items          INTEGER,
    enumeration_complete INTEGER NOT NULL DEFAULT 1,
    enumeration_error    TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    completed_at         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS records (
    id                     TEXT PRIMARY KEY,
    source_url             TEXT NOT NULL,
    status                 TEXT NOT NULL,
    extractor              TEXT NOT NULL DEFAULT '',
    media_id               TEXT NOT NULL DEFAULT '',
    media_kind             TEXT NOT NULL DEFAULT 'video',
    output_format          TEXT NOT NULL DEFAULT '',
    quality                INTEGER NOT NULL DEFAULT 0,
    title                  TEXT NOT NULL DEFAULT '',
    uploader               TEXT NOT NULL DEFAULT '',
    duration               REAL,
    thumbnail_url          TEXT NOT NULL DEFAULT '',
    canonical_url          TEXT NOT NULL DEFAULT '',
    output_directory       TEXT NOT NULL DEFAULT '',
    final_path             TEXT NOT NULL DEFAULT '',
    playlist_id            TEXT REFERENCES playlists(id) ON DELETE CASCADE,
    playlist_title         TEXT NOT NULL DEFAULT '',
    playlist_index         INTEGER,
    created_at             TEXT NOT NULL,
    started_at             TEXT NOT NULL DEFAULT '',
    completed_at           TEXT NOT NULL DEFAULT '',
    attempt_count          INTEGER NOT NULL DEFAULT 0,
    error_code             TEXT NOT NULL DEFAULT '',
    error_message          TEXT NOT NULL DEFAULT '',
    duplicate_of_record_id TEXT NOT NULL DEFAULT '',
    duplicate_kind         TEXT NOT NULL DEFAULT ''
);

-- Indexes for the queries actually issued: tab filters, duplicate detection
-- and sorting the history newest first.
CREATE INDEX IF NOT EXISTS idx_records_status   ON records(status);
CREATE INDEX IF NOT EXISTS idx_records_identity ON records(extractor, media_id);
CREATE INDEX IF NOT EXISTS idx_records_artifact ON records(extractor, media_id, media_kind, output_format);
CREATE INDEX IF NOT EXISTS idx_records_playlist ON records(playlist_id);
CREATE INDEX IF NOT EXISTS idx_records_recent   ON records(created_at DESC);

-- Attempt history: how often and with what outcome a record was tried.
-- No full tracebacks are kept; the number, time and a short error suffice.
CREATE TABLE IF NOT EXISTS attempts (
    record_id     TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    number        INTEGER NOT NULL,
    started_at    TEXT NOT NULL DEFAULT '',
    finished_at   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT '',
    error_code    TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    manual        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (record_id, number)
);
CREATE INDEX IF NOT EXISTS idx_attempts_record ON attempts(record_id);
"""

_RECORD_FIELDS = tuple(field.name for field in dataclasses.fields(HistoryRecord))
_PLAYLIST_FIELDS = tuple(field.name for field in dataclasses.fields(PlaylistRecord))

_CREATE_TABLE_RE = re.compile(
    r'CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);', re.DOTALL)


@functools.cache
def _upsert_sql(table: str, fields: tuple[str, ...], key: str) -> str:
    """`INSERT ... ON CONFLICT(key) DO UPDATE SET ...` for the given columns.

    Deliberately not `INSERT OR REPLACE`: REPLACE deletes the conflicting row
    first, which cascades to child tables and re-checks foreign keys.
    """
    columns = ', '.join(fields)
    placeholders = ', '.join(f':{name}' for name in fields)
    assignments = ', '.join(f'{name} = excluded.{name}' for name in fields if name != key)
    return (f'INSERT INTO {table} ({columns}) VALUES ({placeholders}) '
            f'ON CONFLICT({key}) DO UPDATE SET {assignments}')


def _exists(connection: sqlite3.Connection, table: str, row_id: str) -> bool:
    return connection.execute(
        f'SELECT 1 FROM {table} WHERE id = ? LIMIT 1', (row_id,)).fetchone() is not None


@functools.cache
def _declared_columns() -> dict[str, dict[str, str]]:
    """Map every table in the schema to its column declarations.

    Parsed from the schema itself so a new column only has to be written once.
    """
    tables: dict[str, dict[str, str]] = {}
    for table, body in _CREATE_TABLE_RE.findall(_SCHEMA):
        columns: dict[str, str] = {}
        for raw in body.split('\n'):
            line = raw.strip().rstrip(',')
            if not line or line.startswith(('PRIMARY KEY', '--')):
                continue
            name = line.split()[0]
            # Foreign key clauses cannot be added with ALTER TABLE
            columns[name] = line.split(' REFERENCES ')[0]
        tables[table] = columns
    return tables


class HistoryStore:
    """Reading and writing the history. Safe to use from several threads."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        with self._init_lock:
            self._migrate(self._connection())

    # ------------------------------------------------------------ connection

    def _connection(self) -> sqlite3.Connection:
        """One connection per thread; SQLite dislikes sharing them."""
        connection = getattr(self._local, 'connection', None)
        if connection is None:
            connection = sqlite3.connect(self.path, timeout=10)
            connection.row_factory = sqlite3.Row
            # WAL allows reading while another thread writes
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=NORMAL')
            self._local.connection = connection
        return connection

    def _migrate(self, connection: sqlite3.Connection) -> None:
        """Bring an existing database up to the current schema.

        `CREATE TABLE IF NOT EXISTS` only covers tables that are missing
        entirely; a table that already exists keeps its old column set. Newly
        declared columns are therefore added explicitly, otherwise upgrading
        from an older release fails on the first insert.
        """
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            return

        with connection:
            connection.executescript(_SCHEMA)
            for table, columns in _declared_columns().items():
                existing = {row['name'] for row in
                            connection.execute(f'PRAGMA table_info({table})')}
                for name, declaration in columns.items():
                    if name not in existing:
                        connection.execute(f'ALTER TABLE {table} ADD COLUMN {declaration}')
            connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def close(self) -> None:
        connection = getattr(self._local, 'connection', None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    # -------------------------------------------------------------- writing

    def add(self, record: HistoryRecord) -> None:
        self.add_many([record])

    def add_many(self, records: Sequence[HistoryRecord]) -> None:
        """Write records in one transaction, so there is no half-written state."""
        if not records:
            return
        connection = self._connection()
        with connection:
            self._write_records(connection, records)

    def update(self, record: HistoryRecord) -> None:
        """Update an existing record, inserting it when it is not there yet.

        A real upsert: the existing row is modified in place, so rows that
        reference it (its attempts) survive and its playlist reference is not
        re-validated as if the row were new.
        """
        self.add_many([record])

    def add_playlist(self, playlist: PlaylistRecord) -> None:
        connection = self._connection()
        with connection:
            self._write_playlist(connection, playlist)

    def save_playlist_with_items(self, playlist: PlaylistRecord,
                                 records: Sequence[HistoryRecord]) -> None:
        """Store a playlist and its items together, atomically.

        The parent goes first: a child carrying `playlist_id` cannot be written
        before the playlist it points at exists.
        """
        connection = self._connection()
        with connection:
            self._write_playlist(connection, playlist)
            self._write_records(connection, records)

    # The upsert statements are generated from the dataclass fields, so a new
    # column never has to be spelled out twice. The primary key is excluded
    # from the update clause: it is what identifies the row.

    def _write_records(self, connection: sqlite3.Connection,
                       records: Sequence[HistoryRecord]) -> None:
        if not records:
            return
        rows = [self._record_row(connection, record) for record in records]
        connection.executemany(_upsert_sql('records', _RECORD_FIELDS, 'id'), rows)

    def _write_playlist(self, connection: sqlite3.Connection,
                        playlist: PlaylistRecord) -> None:
        data = dataclasses.asdict(playlist)
        data['enumeration_complete'] = int(playlist.enumeration_complete)
        connection.execute(_upsert_sql('playlists', _PLAYLIST_FIELDS, 'id'), data)

    def _record_row(self, connection: sqlite3.Connection,
                    record: HistoryRecord) -> dict:
        """Row data with references that no longer exist dropped.

        A user can clear the history or delete single entries while queue items
        still point at them - a playlist parent or the record a duplicate was
        found against. Writing such a reference would break the foreign key and
        take the whole GUI action down with it, so the reference is dropped
        instead: the download itself is what matters, not the bookkeeping.
        """
        data = dataclasses.asdict(record)
        if data.get('playlist_id') and not _exists(connection, 'playlists', data['playlist_id']):
            data['playlist_id'] = None
        if data.get('duplicate_of_record_id') \
                and data['duplicate_of_record_id'] != record.id \
                and not _exists(connection, 'records', data['duplicate_of_record_id']):
            data['duplicate_of_record_id'] = ''
            data['duplicate_kind'] = ''
        return data

    def save_attempts(self, record_id: str, attempts: Sequence) -> None:
        """Overwrite the attempt history of a given record."""
        connection = self._connection()
        with connection:
            connection.execute('DELETE FROM attempts WHERE record_id = ?', (record_id,))
            if attempts:
                connection.executemany(
                    'INSERT INTO attempts (record_id, number, started_at, finished_at, '
                    'status, error_code, error_message, manual) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    [(record_id, a.number, a.started_at, a.finished_at, a.status,
                      a.error_code, a.error_message, int(a.manual)) for a in attempts])

    def load_attempts(self, record_id: str) -> list[dict]:
        rows = self._connection().execute(
            'SELECT number, started_at, finished_at, status, error_code, error_message, manual '
            'FROM attempts WHERE record_id = ? ORDER BY number', (record_id,))
        return [{**dict(row), 'manual': bool(row['manual'])} for row in rows]

    # --------------------------------------------------------------- reading

    def get(self, record_id: str) -> HistoryRecord | None:
        row = self._connection().execute(
            'SELECT * FROM records WHERE id = ?', (record_id,)).fetchone()
        return _to_record(row) if row else None

    def list(self, *, limit: int = DEFAULT_LIMIT, statuses: Iterable[str] | None = None,
             ) -> list[HistoryRecord]:
        """Records newest first, optionally narrowed to selected statuses."""
        query = 'SELECT * FROM records'
        params: list = []
        statuses = list(statuses or [])
        if statuses:
            query += f' WHERE status IN ({", ".join("?" * len(statuses))})'
            params.extend(statuses)
        query += ' ORDER BY created_at DESC, rowid DESC LIMIT ?'
        params.append(limit)
        return [_to_record(row) for row in self._connection().execute(query, params)]

    def list_playlists(self, *, limit: int = DEFAULT_LIMIT) -> list[PlaylistRecord]:
        rows = self._connection().execute(
            'SELECT * FROM playlists ORDER BY created_at DESC, rowid DESC LIMIT ?', (limit,))
        return [_to_playlist(row) for row in rows]

    def find_by_identity(self, identity: MediaIdentity) -> list[HistoryRecord]:
        """Every download of a given media item; input for duplicate detection."""
        if not identity.is_valid:
            return []
        rows = self._connection().execute(
            'SELECT * FROM records WHERE media_id = ? AND extractor = ? '
            'ORDER BY created_at DESC', (identity.media_id, identity.extractor))
        return [_to_record(row) for row in rows]

    def count(self) -> int:
        return self._connection().execute('SELECT COUNT(*) FROM records').fetchone()[0]

    # -------------------------------------------------------------- removal

    def delete(self, record_ids: Sequence[str]) -> int:
        """Delete history records. Files on disk are never touched."""
        if not record_ids:
            return 0
        connection = self._connection()
        with connection:
            cursor = connection.execute(
                f'DELETE FROM records WHERE id IN ({", ".join("?" * len(record_ids))})',
                list(record_ids))
            # A playlist without items no longer makes sense as a record
            connection.execute(
                'DELETE FROM playlists WHERE id NOT IN (SELECT DISTINCT playlist_id '
                'FROM records WHERE playlist_id IS NOT NULL)')
        return cursor.rowcount

    def delete_by_status(self, statuses: Sequence[str]) -> int:
        if not statuses:
            return 0
        connection = self._connection()
        with connection:
            cursor = connection.execute(
                f'DELETE FROM records WHERE status IN ({", ".join("?" * len(statuses))})',
                list(statuses))
            connection.execute(
                'DELETE FROM playlists WHERE id NOT IN (SELECT DISTINCT playlist_id '
                'FROM records WHERE playlist_id IS NOT NULL)')
        return cursor.rowcount

    def clear(self) -> None:
        """Clear the whole history. Downloaded files are left untouched."""
        connection = self._connection()
        with connection:
            connection.execute('DELETE FROM records')
            connection.execute('DELETE FROM playlists')

    # ------------------------------------------------------------ recovery

    def recover_interrupted(self, active_statuses: Sequence[str], interrupted: str) -> int:
        """In-progress records from a previous session must not look active.

        The application has not been running since the last start-up, so
        everything stored as downloading or post-processing is marked as
        interrupted; the user can retry or remove it.
        """
        if not active_statuses:
            return 0
        connection = self._connection()
        with connection:
            cursor = connection.execute(
                f'UPDATE records SET status = ? '
                f'WHERE status IN ({", ".join("?" * len(active_statuses))})',
                [interrupted, *active_statuses])
        return cursor.rowcount


def _to_record(row: sqlite3.Row) -> HistoryRecord:
    return HistoryRecord(**{name: row[name] for name in _RECORD_FIELDS})


def _to_playlist(row: sqlite3.Row) -> PlaylistRecord:
    data = {name: row[name] for name in _PLAYLIST_FIELDS}
    data['enumeration_complete'] = bool(data['enumeration_complete'])
    return PlaylistRecord(**data)
