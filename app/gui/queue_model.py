"""Qt models for the download list and for playlists.

The models are thin wrappers over `DownloadController`; they keep no copy of
the state, so the view cannot drift apart from the queue.

The "Playlists" tab uses a separate model because its row is a whole
playlist (`PlaylistJob`) rather than a single downloaded file.
"""

from __future__ import annotations

import enum

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QSortFilterProxyModel, Qt

from ..core.download_controller import DownloadController
from ..core.models import DownloadTask, MediaKind
from ..state import TaskState

TASK_ROLE = int(Qt.ItemDataRole.UserRole) + 1
PLAYLIST_ROLE = int(Qt.ItemDataRole.UserRole) + 2


class QueueFilter(enum.Enum):
    """Tabs above the list. Labels are translated by `app/gui/labels.py`."""

    ALL = 'all'
    IN_PROGRESS = 'in_progress'
    NEEDS_REVIEW = 'needs_review'
    FAILED = 'failed'
    VIDEO = 'video'
    AUDIO = 'audio'
    PLAYLISTS = 'playlists'
    COMPLETED = 'completed'

    @property
    def uses_playlist_model(self) -> bool:
        """Whether the tab shows playlists instead of individual files."""
        return self is QueueFilter.PLAYLISTS


#: Order of the tabs in the filter bar
FILTER_ORDER: tuple[QueueFilter, ...] = (
    QueueFilter.ALL,
    QueueFilter.IN_PROGRESS,
    QueueFilter.NEEDS_REVIEW,
    QueueFilter.FAILED,
    QueueFilter.VIDEO,
    QueueFilter.AUDIO,
    QueueFilter.PLAYLISTS,
    QueueFilter.COMPLETED,
)

#: States visible in the "Completed" tab
_COMPLETED_STATES = frozenset({TaskState.FINISHED, TaskState.COMPLETED_WITH_ERRORS})


class QueueModel(QAbstractListModel):
    """The list of individual download items."""

    def __init__(self, controller: DownloadController, parent: QObject | None = None):
        super().__init__(parent)
        self._controller = controller
        controller.tasksAdded.connect(self._on_tasks_added)
        controller.taskChanged.connect(self._on_task_changed)
        controller.tasksRemoved.connect(self._on_tasks_removed)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._controller.tasks)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        tasks = self._controller.tasks
        if not index.isValid() or not 0 <= index.row() < len(tasks):
            return None
        task = tasks[index.row()]
        if role == TASK_ROLE:
            return task
        if role == int(Qt.ItemDataRole.DisplayRole):
            return task.display_title
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return task.error or task.filepath or task.url
        return None

    def _on_tasks_added(self, tasks: list[DownloadTask]) -> None:
        total = len(self._controller.tasks)
        self.beginInsertRows(QModelIndex(), total - len(tasks), total - 1)
        self.endInsertRows()

    def _on_task_changed(self, task_id: str) -> None:
        row = self._controller.index_of(task_id)
        if row >= 0:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index)

    def _on_tasks_removed(self, _task_ids: list[str]) -> None:
        # The controller has already removed the items; a reset is simplest
        self.beginResetModel()
        self.endResetModel()


class PlaylistModel(QAbstractListModel):
    """The list of playlists: one playlist is one row, not its files."""

    def __init__(self, controller: DownloadController, parent: QObject | None = None):
        super().__init__(parent)
        self._controller = controller
        controller.playlistsChanged.connect(self._on_playlists_changed)
        controller.taskChanged.connect(lambda *_: self._refresh_rows())

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._controller.playlists)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        playlists = self._controller.playlists
        if not index.isValid() or not 0 <= index.row() < len(playlists):
            return None
        job = playlists[index.row()]
        if role == PLAYLIST_ROLE:
            return job
        if role == int(Qt.ItemDataRole.DisplayRole):
            return job.title
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return job.enumeration_error or job.source_url
        return None

    def _on_playlists_changed(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def _refresh_rows(self) -> None:
        """An item change shifts the playlist counters, so refresh the rows."""
        count = self.rowCount()
        if count:
            self.dataChanged.emit(self.index(0, 0), self.index(count - 1, 0))


class QueueFilterProxy(QSortFilterProxyModel):
    """Tab filter plus a title search box."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._filter = QueueFilter.ALL
        self._search = ''

    def set_filter(self, queue_filter: QueueFilter) -> None:
        self._filter = queue_filter
        # `invalidateFilter()` and `invalidateRowsFilter()` are both deprecated
        # in PySide6; `invalidate()` is the public way to ask for a re-filter
        self.invalidate()

    def set_search(self, text: str) -> None:
        self._search = (text or '').strip().casefold()
        self.invalidate()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        source = self.sourceModel()
        if source is None:
            return False
        task: DownloadTask | None = source.index(source_row, 0, source_parent).data(TASK_ROLE)
        if task is None:
            return False

        if self._search and self._search not in task.display_title.casefold():
            return False

        if self._filter is QueueFilter.ALL:
            return True
        if self._filter is QueueFilter.IN_PROGRESS:
            # One shared definition of "in progress": an item awaiting a user
            # decision cannot run, so it does not belong here
            return task.state.is_active
        if self._filter is QueueFilter.NEEDS_REVIEW:
            return task.state.needs_decision
        if self._filter is QueueFilter.FAILED:
            # Final failures only: cancelled, skipped and partially successful
            # items have their own semantics
            return task.state.is_failed
        if self._filter is QueueFilter.VIDEO:
            # Filter by media kind, regardless of whether it came from a playlist
            return task.kind is MediaKind.VIDEO
        if self._filter is QueueFilter.AUDIO:
            return task.kind is MediaKind.AUDIO
        if self._filter is QueueFilter.COMPLETED:
            return task.state in _COMPLETED_STATES
        return True
