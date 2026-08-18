"""Tests for final failures, automatic retries and the "Failed" tab."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from app.core.download_controller import DownloadController
from app.core.errors import AppErrorCode, ErrorCategory, FriendlyError, is_retryable
from app.core.history import HistoryStore
from app.core.models import DownloadRequest, DownloadTask
from app.core.ytdlp_service import YtDlpService
from app.settings import AppSettings
from app.state import TaskState


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(qapp, tmp_path):
    settings = AppSettings(job_retries=2, job_retry_delay=0)
    ctl = DownloadController(YtDlpService(settings),
                             history=HistoryStore(tmp_path / 'history.db'))
    ctl.pause()
    yield ctl
    ctl.shutdown()


def _task(controller, title='Film') -> DownloadTask:
    task = DownloadTask(request=DownloadRequest(url=f'https://example.com/{title}',
                                                output_dir='/tmp/out'), title=title)
    controller.enqueue([task], autostart=False)
    return task


def _fail(controller, task, code=AppErrorCode.NETWORK_ERROR, message='timeout'):
    """Simulate a failed attempt the way the worker would."""
    controller._active_id = task.id
    task.begin_attempt('2026-08-17T10:00:00+00:00')
    controller._on_failed(task.id, FriendlyError(code, message))


def _pump_timers(qapp):
    """Flush the deferred retries (QTimer.singleShot with a zero delay)."""
    for _ in range(5):
        QCoreApplication.processEvents()


# ------------------------------------------------------ error classification


@pytest.mark.parametrize(('code', 'expected'), [
    (AppErrorCode.NETWORK_ERROR, True),
    (AppErrorCode.SSL_ERROR, True),
    (AppErrorCode.UNKNOWN, True),
    (AppErrorCode.PRIVATE_VIDEO, False),
    (AppErrorCode.FFMPEG_MISSING, False),
    (AppErrorCode.NO_DISK_SPACE, False),
    (AppErrorCode.UNSUPPORTED_URL, False),
])
def test_which_errors_are_retried_automatically(code, expected):
    assert is_retryable(code) is expected


def test_error_categories():
    assert FriendlyError(AppErrorCode.PRIVATE_VIDEO).category is ErrorCategory.AUTH
    assert FriendlyError(AppErrorCode.NETWORK_ERROR).category is ErrorCategory.NETWORK
    assert FriendlyError(AppErrorCode.FFMPEG_MISSING).category is ErrorCategory.FFMPEG


# ------------------------------------------------------- automatyczne retry


def test_a_failed_attempt_is_not_yet_a_failure(controller, qapp):
    """While attempts remain the item is "in progress", not "Failed"."""
    task = _task(controller)
    _fail(controller, task)

    assert task.state is TaskState.RETRYING
    assert task.state.is_active is True
    assert task.state.is_failed is False
    assert controller.failed_tasks() == []


def test_running_out_of_attempts_yields_a_failure(controller, qapp):
    task = _task(controller)
    for _ in range(3):  # the first attempt plus 2 automatic retries
        _fail(controller, task)
        _pump_timers(qapp)

    assert task.state is TaskState.ERROR
    assert task.auto_retries == 2
    assert [t.id for t in controller.failed_tasks()] == [task.id]


def test_a_non_retryable_error_ends_immediately(controller, qapp):
    """A private video will not fix itself, so no attempts are wasted on it."""
    task = _task(controller)
    _fail(controller, task, AppErrorCode.PRIVATE_VIDEO, 'Private video')

    assert task.state is TaskState.ERROR
    assert task.auto_retries == 0


def test_a_retry_returns_to_the_queue(controller, qapp):
    task = _task(controller)
    _fail(controller, task)
    _pump_timers(qapp)

    assert task.state is TaskState.QUEUED


def test_success_after_a_retry_does_not_land_in_failed(controller, qapp):
    from app.core.models import DownloadResult

    task = _task(controller)
    _fail(controller, task)
    _pump_timers(qapp)
    assert task.state is TaskState.QUEUED

    # The second attempt, as the worker would run it after taking the job
    controller._active_id = task.id
    task.begin_attempt('2026-08-17T10:01:00+00:00')
    controller._on_completed(task.id, DownloadResult.classify(completed=1, total=1))

    assert task.state is TaskState.FINISHED
    assert controller.failed_tasks() == []
    # The attempt history remembers that the first attempt failed
    assert len(task.attempts) == 2
    assert task.attempts[0].error_code == AppErrorCode.NETWORK_ERROR.value
    assert task.attempts[1].succeeded is True


# ------------------------------------------------------------- manual retry


def test_a_manual_retry_works_even_with_no_attempts_left(controller, qapp):
    task = _task(controller)
    for _ in range(3):
        _fail(controller, task)
        _pump_timers(qapp)
    assert task.state is TaskState.ERROR

    controller.retry([task.id])

    # A manual retry resumes the queue, so the item goes back to work at once
    assert task.state.is_active is True
    assert task.state.is_failed is False
    assert controller.failed_tasks() == []
    # The automatic policy starts over
    assert task.auto_retries == 0


def test_a_manual_retry_works_for_a_non_retryable_error(controller, qapp):
    """The user may have logged in or installed FFmpeg in the meantime."""
    task = _task(controller)
    _fail(controller, task, AppErrorCode.FFMPEG_MISSING, 'ffmpeg not found')
    assert task.state is TaskState.ERROR

    controller.retry([task.id])
    assert task.state.is_active is True
    assert task.state.is_failed is False


def test_a_manual_retry_does_not_clear_the_attempt_history(controller, qapp):
    task = _task(controller)
    for _ in range(3):
        _fail(controller, task)
        _pump_timers(qapp)
    before = len(task.attempts)

    controller.retry([task.id])
    # Earlier attempts stay; at most a new one started by the queue was added
    assert len(task.attempts) >= before
    assert [a.error_code for a in task.attempts[:before]] == \
        [AppErrorCode.NETWORK_ERROR.value] * before


def test_another_failure_returns_to_the_failed_tab(controller, qapp):
    task = _task(controller)
    for _ in range(3):
        _fail(controller, task)
        _pump_timers(qapp)
    controller.retry([task.id])

    for _ in range(3):
        _fail(controller, task)
        _pump_timers(qapp)

    assert task.state is TaskState.ERROR
    assert [t.id for t in controller.failed_tasks()] == [task.id]
    assert len(task.attempts) >= 6


def test_retry_all(controller, qapp):
    tasks = [_task(controller, f'Film {i}') for i in range(5)]
    for task in tasks:
        _fail(controller, task, AppErrorCode.PRIVATE_VIDEO)
    assert len(controller.failed_tasks()) == 5

    controller.retry_all_failed()
    assert controller.failed_tasks() == []
    assert all(task.state.is_active for task in tasks)


# ------------------------------------------------------------------ usuwanie


def test_removal_does_not_touch_the_files(controller, tmp_path, qapp):
    plik = tmp_path / 'film.mp4'
    plik.write_text('dane')
    task = _task(controller)
    task.filepath = str(plik)
    _fail(controller, task, AppErrorCode.PRIVATE_VIDEO)

    controller.remove_failed()
    assert controller.failed_tasks() == []
    assert plik.exists()


# --------------------------------------------------------- state separation


def test_the_tabs_do_not_mix_items_up(controller, qapp):
    """Cancelled, skipped and partially successful items are not "Failed"."""
    for state in (TaskState.CANCELLED, TaskState.SKIPPED_BY_USER,
                  TaskState.SKIPPED_DUPLICATE, TaskState.COMPLETED_WITH_ERRORS,
                  TaskState.NEEDS_REVIEW):
        assert state.is_failed is False, state
    assert TaskState.ERROR.is_failed is True


def test_retrying_counts_as_in_progress_not_as_failed():
    assert TaskState.RETRYING.is_active is True
    assert TaskState.RETRYING.is_failed is False
    assert TaskState.RETRYING.is_final is False


def test_the_attempt_history_survives_a_restart(qapp, tmp_path):
    store = HistoryStore(tmp_path / 'history.db')
    settings = AppSettings(job_retries=0, job_retry_delay=0)
    first = DownloadController(YtDlpService(settings), history=store)
    first.pause()
    task = _task(first)
    _fail(first, task, AppErrorCode.PRIVATE_VIDEO, 'Private video')
    first.shutdown()

    second = DownloadController(YtDlpService(settings), history=HistoryStore(tmp_path / 'history.db'))
    try:
        second.restore_history()
        restored = second.tasks[0]
        assert restored.state is TaskState.ERROR
        assert restored.attempt_count == 1
        assert restored.attempts[0].error_code == AppErrorCode.PRIVATE_VIDEO.value
    finally:
        second.shutdown()


def test_the_two_retry_layers_are_separate():
    """`retries` goes to yt-dlp, `job_retries` retries the whole job."""
    settings = AppSettings(retries=10, job_retries=2)
    options = YtDlpService(settings).download_options(
        DownloadRequest(url='u', output_dir='/tmp'))

    assert options['retries'] == 10
    assert options['fragment_retries'] == 10
    assert 'job_retries' not in options


def test_the_application_state_sees_a_pending_retry(controller, qapp):
    """During the retry delay the application must not pretend to be idle."""
    from app.state import AppState

    task = _task(controller)
    _fail(controller, task)

    assert task.state is TaskState.RETRYING
    assert controller.state is AppState.READY


# ------------------------------------------------------------------ teardown


def test_shutdown_can_be_called_twice(qapp, tmp_path):
    """A window close and `aboutToQuit` both arrive on the way out."""
    ctl = DownloadController(YtDlpService(AppSettings()),
                             history=HistoryStore(tmp_path / 'history.db'))
    ctl.shutdown()
    ctl.shutdown()


def test_shutdown_unhooks_the_download_thread(qapp, tmp_path):
    """Nothing may still be queued into a controller being taken apart."""
    ctl = DownloadController(YtDlpService(AppSettings()),
                             history=HistoryStore(tmp_path / 'history.db'))
    received = []
    ctl.logMessage.connect(lambda *args: received.append(args))
    ctl.shutdown()

    ctl._worker.log.emit('info', 'after shutdown')
    QCoreApplication.processEvents()
    assert received == []


def test_a_forgotten_controller_stops_its_thread(qapp, tmp_path, monkeypatch):
    """Qt aborts the process if a running QThread is destroyed.

    The abort lands wherever the garbage collector happens to run, which is
    the worst possible place to learn about it, so a controller nobody shut
    down closes itself.
    """
    import gc

    closed = []
    original = DownloadController.shutdown

    def recording_shutdown(self):
        closed.append(self._thread.isRunning())
        original(self)

    monkeypatch.setattr(DownloadController, 'shutdown', recording_shutdown)

    ctl = DownloadController(YtDlpService(AppSettings()),
                             history=HistoryStore(tmp_path / 'history.db'))
    assert ctl._thread.isRunning()

    del ctl
    gc.collect()
    QCoreApplication.processEvents()
    # Called on the way out, and the thread really was still running: without
    # this the process would abort somewhere else entirely
    assert closed == [True]
