"""Asynchronous thumbnail fetching with a RAM and disk cache.

The cache keeps one source image per URL and hands out variants scaled to a
specific size (queue card vs download dialog preview), so nothing has to be
rescaled on every `paint()`.
"""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QStandardPaths, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QPixmap

_USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) yt-dlp-gui'
_TIMEOUT = 10
_MAX_BYTES = 4 * 1024 * 1024
#: Size stored on disk, with headroom for the preview and HiDPI screens
_STORE_WIDTH = 480
_STORE_HEIGHT = 270


class _FetchSignals(QObject):
    done = Signal(str, bytes)  # url, dane obrazu (puste = niepowodzenie)


class ThumbnailWorker(QRunnable):
    """Fetching a single image. Run by `QThreadPool`."""

    def __init__(self, url: str, signals: _FetchSignals):
        super().__init__()
        self._url = url
        self._signals = signals

    @Slot()
    def run(self) -> None:
        try:
            request = urllib.request.Request(self._url, headers={'User-Agent': _USER_AGENT})
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                data = response.read(_MAX_BYTES)
        except Exception:  # noqa: BLE001 - a missing cover is not a fatal error
            data = b''
        self._signals.done.emit(self._url, data)


class ThumbnailCache(QObject):
    """`get()` never blocks: it returns `None` and emits `loaded` once fetched."""

    loaded = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._source: dict[str, QPixmap] = {}
        self._variants: dict[tuple[str, int, int, int], QPixmap] = {}
        self._pending: set[str] = set()

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._signals = _FetchSignals()
        self._signals.done.connect(self._on_fetched)

        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
        self._dir = Path(base or '') / 'thumbnails'

    def get(self, url: str, width: int, height: int,
            ratio: float = 1.0) -> QPixmap | None:
        """A thumbnail fitted to the given frame, or None plus a fetch request.

        `width` and `height` are logical pixels. On a HiDPI screen the image is
        rendered at `ratio` times that and tagged, so Qt draws it sharp instead
        of scaling a half-resolution bitmap up.
        """
        if not url:
            return None

        ratio = max(1.0, ratio)
        key = (url, width, height, round(ratio * 100))
        cached = self._variants.get(key)
        if cached is not None:
            return cached if not cached.isNull() else None

        source = self._source_pixmap(url)
        if source is None:
            return None
        if source.isNull():
            self._variants[key] = source
            return None

        variant = _fit(source, width, height, ratio)
        self._variants[key] = variant
        return variant

    def shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(2000)

    # --- internals ---

    def _source_pixmap(self, url: str) -> QPixmap | None:
        cached = self._source.get(url)
        if cached is not None:
            return cached

        path = self._path_for(url)
        if path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._source[url] = pixmap
                return pixmap

        if url not in self._pending:
            self._pending.add(url)
            self._pool.start(ThumbnailWorker(url, self._signals))
        return None

    @Slot(str, bytes)
    def _on_fetched(self, url: str, data: bytes) -> None:
        self._pending.discard(url)
        source = QPixmap()
        if not data or not source.loadFromData(data):
            self._source[url] = QPixmap()  # remember the failure, do not ask again
            return

        if source.width() > _STORE_WIDTH or source.height() > _STORE_HEIGHT:
            source = source.scaled(
                _STORE_WIDTH, _STORE_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._source[url] = source
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            source.save(str(self._path_for(url)), 'PNG')
        except OSError:
            pass
        self.loaded.emit(url)

    def _path_for(self, url: str) -> Path:
        return self._dir / f'{hashlib.sha1(url.encode()).hexdigest()}.png'


def _fit(source: QPixmap, width: int, height: int, ratio: float = 1.0) -> QPixmap:
    """Scale keeping the aspect ratio and crop the centre to the given frame.

    The work happens in device pixels; the result is tagged with the ratio so
    the caller can keep thinking in logical ones.
    """
    device_width = max(1, round(width * ratio))
    device_height = max(1, round(height * ratio))
    scaled = source.scaled(
        device_width, device_height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - device_width) // 2)
    y = max(0, (scaled.height() - device_height) // 2)
    cropped = scaled.copy(x, y, min(device_width, scaled.width()),
                          min(device_height, scaled.height()))
    cropped.setDevicePixelRatio(ratio)
    return cropped
