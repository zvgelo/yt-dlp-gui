"""The controller tying the GUI to the yt-dlp service.

It owns the task queue, one download thread and a thread pool for URL
analysis. The GUI never calls `YoutubeDL` directly; it only talks to this
class.
"""

from __future__ import annotations

import itertools
import logging
import os
import sqlite3
import sys

from PySide6.QtCore import QObject, QThread, QThreadPool, QTimer, Signal, Slot

from ..settings import AppSettings
from ..state import ACTIVE_TASK_STATES, AppState, TaskState
from ..workers.download_worker import DownloadWorker
from ..workers.extract_worker import ExtractWorker
from .duplicates import ArtifactIdentity, DuplicateKind, DuplicatePolicy, DuplicateService
from .errors import FriendlyError, is_retryable
from .history import HistoryStore, MediaIdentity, now_iso
from .history_mapper import (
    job_from_playlist_record,
    playlist_record_from_job,
    record_from_task,
    task_from_record,
)
from .models import (
    DownloadProgress,
    DownloadResult,
    DownloadResultStatus,
    DownloadTask,
    PlaylistJob,
    _new_id,
)
from .ytdlp_service import YtDlpService

log = logging.getLogger(__name__)

#: How long a cooperative cancel is given before the process leaves outright
SHUTDOWN_TIMEOUT_MS = 15_000

_analysis_ids = itertools.count(1)

#: Mapping from a result onto the state of a queue item
_STATE_FOR_RESULT = {
    DownloadResultStatus.SUCCESS: TaskState.FINISHED,
    DownloadResultStatus.PARTIAL_SUCCESS: TaskState.COMPLETED_WITH_ERRORS,
    DownloadResultStatus.ERROR: TaskState.ERROR,
    DownloadResultStatus.CANCELLED: TaskState.CANCELLED,
}


class DownloadController(QObject):
    """The layer between the view and `YtDlpService`."""

    # --- URL analysis ---
    analysisStarted = Signal(str)  # request_id
    analysisFinished = Signal(str, object)  # request_id, MediaInfo
    analysisFailed = Signal(str, object)  # request_id, FriendlyError

    # --- queue ---
    tasksAdded = Signal(list)  # list[DownloadTask]
    taskChanged = Signal(str)  # task_id
    tasksRemoved = Signal(list)  # list[task_id]
    playlistsChanged = Signal()  # a playlist was added or changed
    queueChanged = Signal()

    #: The first item landed in "Needs review"; the GUI shows a quiet notice
    reviewRequested = Signal(object)  # DownloadTask
    #: The job failed for good (after the automatic attempts ran out)
    taskFailed = Signal(object)  # DownloadTask
    #: The history could not be written; the queue itself carries on
    persistenceFailed = Signal(str)  # technical detail for the log

    # --- state and logs ---
    appStateChanged = Signal(object)  # AppState
    logMessage = Signal(str, str)  # level, message

    _runRequested = Signal(str, object)  # to the worker: task_id, DownloadRequest

    def __init__(self, service: YtDlpService, parent: QObject | None = None,
                 history: HistoryStore | None = None,
                 duplicates: DuplicateService | None = None):
        super().__init__(parent)
        self._service = service
        #: Persistent history; without it the controller runs in memory only (tests)
        self._history = history
        self._duplicates = duplicates if duplicates is not None else DuplicateService(history)
        self._tasks: list[DownloadTask] = []
        self._by_id: dict[str, DownloadTask] = {}
        #: Playlists as parent jobs: one entity per playlist
        self._playlists: list[PlaylistJob] = []
        self._active_id: str | None = None
        self._running = True
        self._pending_analyses = 0
        self._state = AppState.IDLE

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(3)

        self._closed = False
        self._thread = QThread(self)
        self._worker = DownloadWorker(service)
        self._worker.moveToThread(self._thread)
        self._connect_worker()
        self._thread.start()

    def _worker_connections(self) -> tuple[tuple[object, object], ...]:
        """Every connection that crosses into the download thread.

        Listed once so that teardown can undo exactly what construction made.
        """
        worker = self._worker
        return (
            (self._runRequested, worker.run_task),
            (worker.started, self._on_started),
            (worker.progress, self._on_progress),
            (worker.postprocessing, self._on_postprocessing),
            (worker.completed, self._on_completed),
            (worker.failed, self._on_failed),
            (worker.cancelled, self._on_cancelled),
            (worker.log, self.logMessage),
        )

    def _connect_worker(self) -> None:
        for signal, slot in self._worker_connections():
            signal.connect(slot)

    def _disconnect_worker(self) -> None:
        for signal, slot in self._worker_connections():
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):  # already gone
                pass

    # ------------------------------------------------------------- access

    @property
    def tasks(self) -> list[DownloadTask]:
        return self._tasks

    @property
    def playlists(self) -> list[PlaylistJob]:
        return self._playlists

    def playlist(self, playlist_id: str) -> PlaylistJob | None:
        return next((job for job in self._playlists if job.id == playlist_id), None)

    def active_items(self) -> list[DownloadTask]:
        """The "in progress" queue: downloading items first, then waiting ones."""
        return [task for task in self._tasks if not task.state.is_final]

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def pending_analyses(self) -> int:
        return self._pending_analyses

    @property
    def active_task(self) -> DownloadTask | None:
        return self._by_id.get(self._active_id) if self._active_id else None

    def task(self, task_id: str) -> DownloadTask | None:
        return self._by_id.get(task_id)

    def index_of(self, task_id: str) -> int:
        task = self._by_id.get(task_id)
        return self._tasks.index(task) if task is not None else -1

    def count_in_state(self, *states: TaskState) -> int:
        return sum(1 for task in self._tasks if task.state in states)

    def update_settings(self, settings: AppSettings) -> None:
        self._service.update_settings(settings)

    # ----------------------------------------------------------- analysis

    def analyze(self, url: str) -> str:
        """Schedule background analysis of a URL. Returns the request identifier."""
        request_id = f'analysis-{next(_analysis_ids)}'
        worker = ExtractWorker(request_id, url, self._service, owner=self)
        worker.signals.finished.connect(self._on_analysis_finished)
        worker.signals.failed.connect(self._on_analysis_failed)
        worker.signals.log.connect(self.logMessage)

        self._pending_analyses += 1
        self._set_state(AppState.ANALYZING)
        self.analysisStarted.emit(request_id)
        self._pool.start(worker)
        return request_id

    @Slot(str, object)
    def _on_analysis_finished(self, request_id: str, info) -> None:
        self._pending_analyses = max(0, self._pending_analyses - 1)
        self.analysisFinished.emit(request_id, info)
        self._refresh_state()

    @Slot(str, object)
    def _on_analysis_failed(self, request_id: str, error: FriendlyError) -> None:
        self._pending_analyses = max(0, self._pending_analyses - 1)
        self.analysisFailed.emit(request_id, error)
        self._refresh_state()

    # -------------------------------------------------------------- queue

    def enqueue(self, tasks: list[DownloadTask], *, autostart: bool = True,
                playlist: PlaylistJob | None = None) -> None:
        tasks = [task for task in tasks if task.request.url]
        if not tasks:
            return

        stamp = now_iso()
        batch_id = _new_id('batch')
        for task in tasks:
            task.created_at = task.created_at or stamp
            task.batch_id = batch_id

        first_review = self._resolve_duplicates(tasks)

        if playlist is not None:
            playlist.created_at = playlist.created_at or stamp
            # The playlist gets its own record and the items merely point at it,
            # so its data is not duplicated into every file
            playlist.tasks = list(tasks)
            for task in tasks:
                task.playlist_id = playlist.id
            self._playlists.append(playlist)

        for task in tasks:
            self._tasks.append(task)
            self._by_id[task.id] = task
        self._store_new(tasks, playlist)
        self.tasksAdded.emit(tasks)
        if playlist is not None:
            self.playlistsChanged.emit()
        if first_review is not None:
            self.reviewRequested.emit(first_review)
        if autostart:
            self._running = True
        self._pump()

    def start(self) -> None:
        self._running = True
        self._pump()

    def pause(self) -> None:
        """Pause the queue; the current download is allowed to finish."""
        self._running = False
        self._refresh_state()

    def cancel(self, task_ids: list[str]) -> None:
        for task_id in task_ids:
            task = self._by_id.get(task_id)
            if task is None:
                continue
            if task_id == self._active_id:
                self._worker.request_cancel()
            elif task.state is TaskState.QUEUED:
                task.state = TaskState.CANCELLED
                task.completed_at = now_iso()
                self._persist(task_id)
                self.taskChanged.emit(task_id)
        self._refresh_state()

    def cancel_active(self) -> None:
        if self._active_id:
            self._worker.request_cancel()

    def remove(self, task_ids: list[str], *, forget: bool = True) -> None:
        """Remove items from the queue and, by default, from history. Files stay."""
        removed = []
        for task_id in task_ids:
            task = self._by_id.get(task_id)
            if task is None:
                continue
            if task_id == self._active_id:
                # An active item is not removed on the fly; cancel it first
                self._worker.request_cancel()
                continue
            self._duplicates.release(self._artifact(task), task.id)
            self._tasks.remove(task)
            del self._by_id[task_id]
            removed.append(task_id)
        if removed:
            if forget and self._history is not None:
                try:
                    self._history.delete(removed)
                except sqlite3.Error as exc:
                    self._report_persistence_error(exc)
            removed_set = set(removed)
            for job in self._playlists:
                job.tasks = [task for task in job.tasks if task.id not in removed_set]
            # A playlist without items no longer makes sense as a record
            self._playlists = [job for job in self._playlists if job.tasks]
            self.tasksRemoved.emit(removed)
            self.playlistsChanged.emit()
        self._refresh_state()

    def remove_finished(self) -> None:
        self.remove([task.id for task in self._tasks if task.state.is_final])

    def retry(self, task_ids: list[str]) -> None:
        """A manual retry: a deliberate decision by the user.

        Available even for errors that are never retried automatically: the
        user may have logged in, fixed the network or installed FFmpeg in the
        meantime. The automatic policy starts over, but the history of earlier
        attempts is left intact.
        """
        changed = False
        for task_id in task_ids:
            task = self._by_id.get(task_id)
            if task is None or not task.state.is_final:
                continue
            task.reset()
            task.auto_retries = 0
            task.manual_retry_pending = True
            self._persist(task_id)
            self.taskChanged.emit(task_id)
            changed = True
        if changed:
            self.start()

    def failed_tasks(self) -> list[DownloadTask]:
        return [task for task in self._tasks if task.state.is_failed]

    def retry_all_failed(self) -> None:
        self.retry([task.id for task in self.failed_tasks()])

    def remove_failed(self) -> None:
        self.remove([task.id for task in self.failed_tasks()])

    # ---------------------------------------------------------- duplicates

    @property
    def duplicates(self) -> DuplicateService:
        return self._duplicates

    def _identity(self, task: DownloadTask) -> MediaIdentity:
        return MediaIdentity(task.extractor, task.media_id)

    def _artifact(self, task: DownloadTask) -> ArtifactIdentity:
        return ArtifactIdentity.from_request(task.request, self._identity(task))

    def _resolve_duplicates(self, tasks: list[DownloadTask]) -> DownloadTask | None:
        """Resolve conflicts before letting items into the queue.

        An item awaiting a decision does not block the others: it gets the
        NEEDS_REVIEW state and waits in "Needs review" while the queue moves on.
        """
        first_review = None
        for task in tasks:
            result = self._duplicates.check_and_reserve(
                task.request, self._identity(task), task.id)
            if not result.is_duplicate:
                continue

            task.duplicate_kind = result.kind.value
            if result.existing_record is not None:
                task.duplicate_of_record_id = result.existing_record.id
                task.duplicate_of_path = result.existing_record.final_path

            if result.kind is DuplicateKind.SAME_TARGET:
                # The same file in the same place; skip without asking
                task.state = TaskState.SKIPPED_DUPLICATE
                task.completed_at = now_iso()
                continue

            policy = self._duplicates.policy(task.batch_id)
            if policy is DuplicatePolicy.DOWNLOAD_ALL_FOR_QUEUE:
                self._duplicates.reserve(self._artifact(task), task.id)
                continue
            if policy is DuplicatePolicy.SKIP_ALL_FOR_QUEUE:
                task.state = TaskState.SKIPPED_BY_USER
                task.completed_at = now_iso()
                continue

            task.state = TaskState.NEEDS_REVIEW
            first_review = first_review or task
        return first_review

    def pending_review(self) -> list[DownloadTask]:
        return [task for task in self._tasks if task.state.needs_decision]

    def approve(self, task_ids: list[str]) -> None:
        """The user wants to download despite the duplicate."""
        changed = False
        for task_id in task_ids:
            task = self._by_id.get(task_id)
            if task is None or not task.state.needs_decision:
                continue
            self._duplicates.reserve(self._artifact(task), task.id)
            task.state = TaskState.QUEUED
            task.duplicate_kind = ''
            self._persist(task_id)
            self.taskChanged.emit(task_id)
            changed = True
        if changed:
            self._pump()
        self._refresh_state()

    def skip(self, task_ids: list[str]) -> None:
        """A deliberate skip; this is not a failure."""
        for task_id in task_ids:
            task = self._by_id.get(task_id)
            if task is None or not task.state.needs_decision:
                continue
            task.state = TaskState.SKIPPED_BY_USER
            task.completed_at = now_iso()
            self._duplicates.release(self._artifact(task), task.id)
            self._persist(task_id)
            self.taskChanged.emit(task_id)
        self._refresh_state()

    def approve_all(self) -> None:
        self.approve([task.id for task in self.pending_review()])

    def skip_all(self) -> None:
        self.skip([task.id for task in self.pending_review()])

    def apply_batch_policy(self, policy: DuplicatePolicy,
                           batch_ids: list[str] | None = None) -> None:
        """Set the policy for the current batches and resolve what already waits.

        The policy applies to those batches only; a new batch asks again.
        """
        pending = self.pending_review()
        batches = batch_ids if batch_ids is not None else [task.batch_id for task in pending]
        for batch_id in set(filter(None, batches)):
            self._duplicates.set_policy(batch_id, policy)

        affected = [task.id for task in pending if task.batch_id in set(batches)]
        if policy is DuplicatePolicy.DOWNLOAD_ALL_FOR_QUEUE:
            self.approve(affected)
        elif policy is DuplicatePolicy.SKIP_ALL_FOR_QUEUE:
            self.skip(affected)

    def _release(self, task_id: str) -> None:
        task = self._by_id.get(task_id)
        if task is not None:
            self._duplicates.release(self._artifact(task), task.id)

    # ------------------------------------------------------------ history

    def _store_new(self, tasks: list[DownloadTask], playlist: PlaylistJob | None) -> None:
        if self._history is None:
            return
        records = [record_from_task(task) for task in tasks]
        try:
            if playlist is not None:
                # One transaction, parent first: children reference the playlist
                self._history.save_playlist_with_items(
                    playlist_record_from_job(playlist), records)
            else:
                self._history.add_many(records)
        except sqlite3.Error as exc:
            self._report_persistence_error(exc)

    def _persist(self, task_id: str) -> None:
        """Persist the task state. Called on state changes, not on progress.

        The playlist parent is written first: a record carrying `playlist_id`
        cannot reference a playlist that is not in the database yet, and after
        the user clears the history the queue still holds items whose parent
        row is gone.

        Failing to write the history must never take down the action that
        triggered it. The download itself is the product; the bookkeeping is
        reported and the interface keeps working.
        """
        if self._history is None:
            return
        task = self._by_id.get(task_id)
        if task is None:
            return
        try:
            if task.playlist_id:
                job = self.playlist(task.playlist_id)
                if job is not None:
                    self._history.add_playlist(playlist_record_from_job(job))
            self._history.update(record_from_task(task))
            if task.attempts:
                self._history.save_attempts(task.id, task.attempts)
        except sqlite3.Error as exc:
            self._report_persistence_error(exc)

    def _report_persistence_error(self, exc: BaseException) -> None:
        """One place turns a storage failure into a message instead of a crash."""
        detail = f'{exc.__class__.__name__}: {exc}'
        log.exception('Could not write the download history')
        self.logMessage.emit('ERROR', f'Could not save download history - {detail}')
        self.persistenceFailed.emit(detail)

    def restore_history(self, limit: int = 1000) -> int:
        """Restore history from the database into the model. Returns the item count."""
        if self._history is None:
            return 0

        # In-progress records from a previous session must not look active
        self._history.recover_interrupted(
            [state.value for state in ACTIVE_TASK_STATES], TaskState.INTERRUPTED.value)

        # Chronological order: oldest first, new items append at the end
        records = list(reversed(self._history.list(limit=limit)))
        restored = [task_from_record(record, self._history.load_attempts(record.id))
                    for record in records]
        if not restored:
            return 0

        added: list[DownloadTask] = []
        for task in restored:
            if task.id in self._by_id:
                continue
            self._restore_duplicate_context(task)
            self._tasks.append(task)
            self._by_id[task.id] = task
            added.append(task)
        if not added:
            return 0

        by_playlist: dict[str, list[DownloadTask]] = {}
        for task in added:
            if task.playlist_id:
                by_playlist.setdefault(task.playlist_id, []).append(task)

        for record in self._history.list_playlists(limit=limit):
            tasks = by_playlist.get(record.id)
            if tasks and not self.playlist(record.id):
                self._playlists.append(job_from_playlist_record(record, tasks))

        self.tasksAdded.emit(added)
        self.playlistsChanged.emit()
        self._refresh_state()
        return len(added)

    def _restore_duplicate_context(self, task: DownloadTask) -> None:
        """Re-attach the conflicting file path so a pending decision stays actionable.

        Only the record id is stored; without resolving it the review card would
        say "already downloaded" without telling the user where.
        """
        if not task.duplicate_of_record_id or self._history is None:
            return
        existing = self._history.get(task.duplicate_of_record_id)
        if existing is not None:
            task.duplicate_of_path = existing.final_path

    def history_count(self) -> int:
        return self._history.count() if self._history else 0

    def clear_history(self) -> None:
        """Clear the history and drop finished items from the view.

        Downloaded files stay on disk; only the records are deleted.

        Items still in the queue keep running. Their history references now
        point at rows that are gone, so they are dropped here rather than left
        to break the next write.
        """
        if self._history is not None:
            try:
                self._history.clear()
            except sqlite3.Error as exc:
                self._report_persistence_error(exc)
                return
        finished = [task.id for task in self._tasks if task.state.is_final]
        self.remove(finished, forget=False)
        for task in self._tasks:
            task.duplicate_of_record_id = ''

    def _pump(self) -> None:
        """Release the next job when the download thread is free."""
        if self._active_id is not None or not self._running:
            self._refresh_state()
            return
        task = next((t for t in self._tasks if t.state is TaskState.QUEUED), None)
        if task is None:
            self._refresh_state()
            return

        self._active_id = task.id
        task.state = TaskState.DOWNLOADING
        stamp = now_iso()
        task.started_at = stamp
        task.begin_attempt(stamp)
        self._persist(task.id)
        self.taskChanged.emit(task.id)
        self._runRequested.emit(task.id, task.request)
        self._refresh_state()

    # ---------------------------------------------------- worker signals

    @Slot(str)
    def _on_started(self, task_id: str) -> None:
        task = self._by_id.get(task_id)
        if task is not None:
            task.state = TaskState.DOWNLOADING
            self._persist(task_id)
            self.taskChanged.emit(task_id)
        self._refresh_state()

    @Slot(str, object)
    def _on_progress(self, task_id: str, progress: DownloadProgress) -> None:
        task = self._by_id.get(task_id)
        if task is None:
            return
        task.progress = progress
        percent = progress.percent
        if percent is not None:
            task.percent = percent
        if progress.status == 'finished':
            task.percent = 100.0
            task.state = TaskState.POSTPROCESSING
        self.taskChanged.emit(task_id)
        self._refresh_state()

    @Slot(str, object)
    def _on_postprocessing(self, task_id: str, stage) -> None:
        task = self._by_id.get(task_id)
        if task is None:
            return
        task.state = TaskState.POSTPROCESSING
        task.stage = stage
        self._persist(task_id)
        self.taskChanged.emit(task_id)
        self._refresh_state()

    @Slot(str, object)
    def _on_completed(self, task_id: str, result: DownloadResult) -> None:
        """A worker finishing is not yet success; `result.status` decides."""
        task = self._by_id.get(task_id)
        if task is not None:
            task.result = result
            task.stage = None
            task.filepath = result.primary_file
            task.progress = DownloadProgress(status='finished', total_bytes=task.progress.total_bytes)
            task.state = _STATE_FOR_RESULT[result.status]
            task.percent = 100.0 if result.completed_items else task.percent
            task.completed_at = now_iso()
            task.finish_attempt(task.completed_at, result.status.value)
            self._persist(task_id)
            self.taskChanged.emit(task_id)
            self._notify_playlist(task_id)
        self._release(task_id)
        self._active_id = None
        self._pump()

    @Slot(str, object)
    def _on_failed(self, task_id: str, error: FriendlyError) -> None:
        """A single attempt failed. Only running out of attempts means FAILED."""
        task = self._by_id.get(task_id)
        self._release(task_id)
        self._active_id = None
        if task is None:
            self._pump()
            return

        stamp = now_iso()
        task.error_code = error.code
        task.error = error.details
        task.stage = None
        task.progress = DownloadProgress()
        task.finish_attempt(stamp, TaskState.ERROR.value,
                            error_code=error.code.value, error_message=error.details)

        if self._can_retry_automatically(task, error):
            task.auto_retries += 1
            task.state = TaskState.RETRYING
            self._persist(task_id)
            self.taskChanged.emit(task_id)
            self._schedule_retry(task_id)
            self._refresh_state()
            return

        task.state = TaskState.ERROR
        task.completed_at = stamp
        self._persist(task_id)
        self.taskChanged.emit(task_id)
        self.taskFailed.emit(task)
        self._pump()

    def _can_retry_automatically(self, task: DownloadTask, error: FriendlyError) -> bool:
        """Only transient errors are retried, and only until the limit runs out.

        A private video or a missing FFmpeg will not fix itself, so no attempts
        are wasted on them; the user can retry manually after changing settings.
        """
        if not is_retryable(error.code):
            return False
        return task.auto_retries < max(0, self._service.settings.job_retries)

    def _schedule_retry(self, task_id: str) -> None:
        """Defer the next attempt; meanwhile the queue works on other items."""
        delay_ms = max(0, self._service.settings.job_retry_delay) * 1000
        QTimer.singleShot(delay_ms, lambda: self._requeue_after_retry(task_id))
        self._pump()

    def _requeue_after_retry(self, task_id: str) -> None:
        task = self._by_id.get(task_id)
        if task is None or task.state is not TaskState.RETRYING:
            return
        task.state = TaskState.QUEUED
        self._persist(task_id)
        self.taskChanged.emit(task_id)
        self._pump()

    @Slot(str)
    def _on_cancelled(self, task_id: str) -> None:
        task = self._by_id.get(task_id)
        if task is not None:
            task.state = TaskState.CANCELLED
            task.stage = None
            task.progress = DownloadProgress()
            task.completed_at = now_iso()
            self._persist(task_id)
            self.taskChanged.emit(task_id)
            self._notify_playlist(task_id)
        self._release(task_id)
        self._active_id = None
        self._pump()

    # ------------------------------------------------------------- state

    def _notify_playlist(self, task_id: str) -> None:
        task = self._by_id.get(task_id)
        if task is not None and task.playlist_id:
            # Playlist counters are computed from the items; refreshing the view is enough
            self.playlistsChanged.emit()

    def _refresh_state(self) -> None:
        active = self.active_task
        if self._pending_analyses:
            state = AppState.ANALYZING
        elif active is not None and active.state is TaskState.POSTPROCESSING:
            state = AppState.POSTPROCESSING
        elif active is not None:
            state = AppState.DOWNLOADING
        elif self.count_in_state(TaskState.QUEUED, TaskState.RETRYING):
            state = AppState.READY
        elif self.count_in_state(TaskState.ERROR, TaskState.COMPLETED_WITH_ERRORS):
            state = AppState.ERROR
        elif self.count_in_state(TaskState.CANCELLED) and not self.count_in_state(TaskState.FINISHED):
            state = AppState.CANCELLED
        elif self.count_in_state(TaskState.FINISHED):
            state = AppState.FINISHED
        else:
            state = AppState.IDLE
        self._set_state(state)
        self.queueChanged.emit()

    def _set_state(self, state: AppState) -> None:
        if state is not self._state:
            self._state = state
            self.appStateChanged.emit(state)

    # ------------------------------------------------------- shutting down

    def close_history(self) -> None:
        if self._history is not None:
            self._history.close()

    def shutdown(self) -> None:
        """Orderly shutdown: cancel cooperatively and wait for the thread.

        `QThread.terminate()` is never called. Terminating a thread that is
        executing Python leaves the interpreter in an undefined state and the
        process then dies during teardown with SIGBUS or SIGSEGV - long after
        the user asked to close the window. If the worker really refuses to
        stop, leaving the process immediately is the honest option: every
        history transaction is already committed.

        Safe to call twice, because a window close and `aboutToQuit` both
        arrive on the way out.
        """
        if self._closed:
            return
        self._closed = True

        self._running = False
        self._worker.request_cancel()
        self._pool.clear()
        self._pool.waitForDone(2000)

        # Cut the worker loose before the thread stops. Its signals cross a
        # thread boundary into slots on this controller, and a queued
        # invocation arriving while the object graph is being taken apart has
        # nothing valid to run against: the process then dies inside the
        # teardown rather than at the point of the mistake.
        #
        # Deliberately not `deleteLater()`: that posts a deferred-delete event
        # to a loop that is about to quit, and the object would be freed twice.
        # Python owns the worker and frees it once the thread has stopped.
        self._disconnect_worker()

        self._thread.quit()
        if self._thread.wait(SHUTDOWN_TIMEOUT_MS):
            return

        log.error('The download thread ignored the cancel request; leaving without teardown')
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)

    def __del__(self) -> None:
        """Last line of defence: never let a running QThread be destroyed.

        Qt aborts the process with "QThread: Destroyed while thread is still
        running" if it happens, and the abort lands wherever the garbage
        collector happened to run - typically inside unrelated code, minutes
        after the controller that was never shut down. The application always
        calls `shutdown()`; this is for the paths that do not, such as a test
        whose set-up failed half way through.
        """
        try:
            self.shutdown()
        except Exception:  # noqa: BLE001 - nothing can be reported from here
            pass
