"""URL analysis (`extract_info(download=False)`) run in a thread pool."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ..core.errors import AppErrorCode, FriendlyError, describe
from ..core.models import MediaInfo
from ..core.ytdlp_service import Logger, YtDlpService


class ExtractSignals(QObject):
    finished = Signal(str, object)  # request_id, MediaInfo
    failed = Signal(str, object)  # request_id, FriendlyError
    log = Signal(str, str)  # level, message


class ExtractWorker(QRunnable):
    """Jedno zapytanie o metadane. Uruchamiane przez `QThreadPool`."""

    def __init__(self, request_id: str, url: str, service: YtDlpService,
                 owner: QObject | None = None):
        super().__init__()
        # The signal object is parented to the caller: QThreadPool deletes the
        # runnable as soon as run() returns, which would destroy an unparented
        # QObject while its queued signals are still in flight.
        self.signals = ExtractSignals(owner)
        self._request_id = request_id
        self._url = url
        self._service = service

    @Slot()
    def run(self) -> None:
        logger = Logger(self.signals.log.emit, verbose=self._service.settings.verbose_log)
        try:
            info: MediaInfo = self._service.extract(self._url, logger)
        except Exception as exc:  # noqa: BLE001 - every extractor error must reach the GUI
            friendly: FriendlyError = describe(exc)
            self.signals.log.emit('ERROR', friendly.details)
            self.signals.failed.emit(self._request_id, friendly)
            return

        if info.is_playlist and not info.entries:
            code = (AppErrorCode.PLAYLIST_INCOMPLETE if not info.entries_complete
                    else AppErrorCode.NOTHING_FOUND)
            self.signals.failed.emit(self._request_id,
                                     FriendlyError(code, info.entries_error))
            return
        self.signals.finished.emit(self._request_id, info)
