"""Download worker: lives in its own `QThread` and runs one job at a time.

Cancellation is cooperative: a `threading.Event` set from the GUI thread
makes the progress hook raise `DownloadCancelled`, which `YoutubeDL` handles
natively. `QThread.terminate()` is never called.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Signal, Slot

from ..core.errors import describe
from ..core.models import DownloadProgress, DownloadRequest, DownloadResult, DownloadResultStatus
from ..core.ytdlp_service import DownloadCallbacks, Logger, YtDlpService

#: Minimum gap between progress signals; the hook can fire hundreds of times/s
PROGRESS_INTERVAL = 0.12


class DownloadWorker(QObject):
    started = Signal(str)  # task_id
    progress = Signal(str, object)  # task_id, DownloadProgress
    postprocessing = Signal(str, object)  # task_id, PostProcessStage
    completed = Signal(str, object)  # task_id, DownloadResult
    failed = Signal(str, object)  # task_id, FriendlyError
    cancelled = Signal(str)  # task_id
    log = Signal(str, str)  # level, message

    def __init__(self, service: YtDlpService):
        super().__init__()
        self._service = service
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        """Called from the GUI thread; `Event` is safe across threads."""
        self._cancel.set()

    @Slot(str, object)
    def run_task(self, task_id: str, request: DownloadRequest) -> None:
        self._cancel.clear()
        self.started.emit(task_id)

        last_emit = 0.0

        def on_progress(progress: DownloadProgress) -> None:
            nonlocal last_emit
            now = time.monotonic()
            if progress.status == 'downloading' and now - last_emit < PROGRESS_INTERVAL:
                return
            last_emit = now
            self.progress.emit(task_id, progress)

        def on_postprocessor(stage, status: str) -> None:
            if status in ('started', 'processing'):
                self.postprocessing.emit(task_id, stage)

        callbacks = DownloadCallbacks(
            on_progress=on_progress,
            on_postprocessor=on_postprocessor,
            is_cancelled=self._cancel.is_set,
        )
        logger = Logger(self.log.emit, verbose=self._service.settings.verbose_log)

        try:
            result: DownloadResult = self._service.download(request, callbacks, logger)
        except Exception as exc:  # noqa: BLE001 - a worker must not crash the app
            # The service maps the usual failures onto a status, so only
            # unforeseen situations reach this point (a read-only folder, ...)
            if self._cancel.is_set():
                self.cancelled.emit(task_id)
                return
            friendly = describe(exc)
            self.log.emit('ERROR', friendly.details)
            self.failed.emit(task_id, friendly)
            return

        if result.status is DownloadResultStatus.CANCELLED:
            self.cancelled.emit(task_id)
            return
        self.completed.emit(task_id, result)
