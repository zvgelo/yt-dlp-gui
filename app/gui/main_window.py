"""Main window: ties the top bar, filters, card list and log to the controller.

The window never calls yt-dlp directly; it delegates analysis and downloads to
`DownloadController` and receives the results through signals.
"""

from __future__ import annotations

import itertools
import os
import subprocess
import sys

from PySide6.QtCore import QEvent, QItemSelectionModel, QModelIndex, Qt, QUrl, Slot
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_TITLE, __version__
from ..core import diagnostics
from ..core.download_controller import DownloadController
from ..core.duplicates import DuplicatePolicy
from ..core.errors import AppErrorCode, FriendlyError
from ..core.history import HistoryStore
from ..core.models import DownloadRequest, DownloadTask, MediaInfo, MediaKind, PlaylistJob
from ..core.ytdlp_service import YtDlpService
from ..i18n import TranslationManager
from ..paths import history_path
from ..settings import AppSettings, SettingsStore
from ..state import AppState, TaskState
from ..theme import Theme, ThemeManager
from ..workers.thumbnail_worker import ThumbnailCache
from . import icons, labels
from .about_dialog import AboutDialog
from .card_delegate import CardDelegate
from .download_dialog import DownloadDialog
from .empty_state import EmptyState
from .error_details_dialog import ErrorDetailsDialog
from .log_widget import LogDock
from .playlist_dialog import PlaylistDialog
from .queue_model import (
    FILTER_ORDER,
    PLAYLIST_ROLE,
    TASK_ROLE,
    PlaylistModel,
    QueueFilter,
    QueueFilterProxy,
    QueueModel,
)
from .settings_dialog import SettingsDialog
from .top_bar import TopBar


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, store: SettingsStore, service: YtDlpService,
                 theme_manager: ThemeManager, translations: TranslationManager):
        super().__init__()
        self._settings = settings
        self._store = store
        self._service = service
        self._themes = theme_manager
        self._translations = translations
        self._ffmpeg = service.ffmpeg_status()
        self._filter = QueueFilter.ALL

        self.history = HistoryStore(history_path())
        self.controller = DownloadController(service, self, history=self.history)
        self.thumbnails = ThumbnailCache(self)
        self.model = QueueModel(self.controller, self)
        self.proxy = QueueFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.playlist_model = PlaylistModel(self.controller, self)

        # Wide enough that the top bar is not immediately squeezed, and short
        # enough to open on a 1366x768 screen
        self.resize(1100, 680)
        self._build_ui()
        self._connect()
        self._restore_window()
        self.retranslate_ui()
        self.restyle()
        self._announce_dependencies()
        self._restore_history()
        self._refresh()

    # --------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.top_bar = TopBar(self._settings, self)
        layout.addWidget(self.top_bar)
        layout.addWidget(self._build_filter_bar())
        layout.addWidget(self._build_review_bar())
        layout.addWidget(self._build_failed_bar())
        layout.addWidget(self._build_stack(), 1)
        self.setCentralWidget(central)

        self.log_dock = LogDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

        self._build_tab_order()
        self._build_shortcuts()

    def _build_tab_order(self) -> None:
        """Follow the layout instead of the order the widgets happened to be built.

        The action bars are created before the queue view but sit above it, and
        only one of them is ever visible, so the chain has to be spelled out.
        """
        bar = self.top_bar
        chain = [
            bar.paste_button, bar.kind_combo, bar.quality_combo, bar.container_combo,
            bar.dir_button, bar.start_button, bar.pause_button, bar.cancel_button,
            bar.log_button, bar.settings_button,
            *self._filter_buttons.values(),
            self.search_edit,
            self.approve_button, self.skip_button, self.approve_all_button,
            self.skip_all_button, self.batch_button,
            self.retry_button, self.details_button, self.remove_failed_button,
            self.retry_all_button, self.remove_all_failed_button,
            self.view,
        ]
        for first, second in itertools.pairwise(chain):
            self.setTabOrder(first, second)

    def _build_filter_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName('FilterBar')
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(2)

        self._filter_buttons: dict[QueueFilter, QToolButton] = {}
        for queue_filter in FILTER_ORDER:
            button = QToolButton()
            button.setObjectName('FilterTab')
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, f=queue_filter: self._set_filter(f))
            layout.addWidget(button)
            self._filter_buttons[queue_filter] = button
        self._filter_buttons[QueueFilter.ALL].setChecked(True)

        layout.addStretch(1)
        self.count_label = QLabel()
        self.count_label.setObjectName('CountLabel')
        layout.addWidget(self.count_label)
        layout.addSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(170)
        self.search_edit.textChanged.connect(self.proxy.set_search)
        layout.addWidget(self.search_edit)
        return bar

    def _build_review_bar(self) -> QWidget:
        """Actions for "Needs review", visible only on that tab."""
        bar = QWidget()
        bar.setObjectName('ActionBar')
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self.review_hint = QLabel()
        self.review_hint.setObjectName('MutedLabel')
        layout.addWidget(self.review_hint)
        layout.addStretch(1)

        self.approve_button = QPushButton()
        self.approve_button.setProperty('accent', True)
        self.approve_button.clicked.connect(self._approve_selected)
        layout.addWidget(self.approve_button)

        self.skip_button = QPushButton()
        self.skip_button.clicked.connect(self._skip_selected)
        layout.addWidget(self.skip_button)

        self.approve_all_button = QPushButton()
        self.approve_all_button.clicked.connect(self.controller.approve_all)
        layout.addWidget(self.approve_all_button)

        self.skip_all_button = QPushButton()
        self.skip_all_button.clicked.connect(self.controller.skip_all)
        layout.addWidget(self.skip_all_button)

        self.batch_button = QToolButton()
        self.batch_button.setObjectName('BarButton')
        self.batch_button.setText('⋯')
        self.batch_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._batch_menu = QMenu(self.batch_button)
        self._batch_download_action = self._batch_menu.addAction(
            '', lambda: self.controller.apply_batch_policy(
                DuplicatePolicy.DOWNLOAD_ALL_FOR_QUEUE))
        self._batch_skip_action = self._batch_menu.addAction(
            '', lambda: self.controller.apply_batch_policy(
                DuplicatePolicy.SKIP_ALL_FOR_QUEUE))
        self._batch_menu.addSeparator()
        self._about_action = self._batch_menu.addAction('', self.open_about)
        self.batch_button.setMenu(self._batch_menu)
        layout.addWidget(self.batch_button)

        self.review_bar = bar
        bar.hide()
        return bar

    def _build_failed_bar(self) -> QWidget:
        """Actions for "Failed", visible only on that tab."""
        bar = QWidget()
        bar.setObjectName('ActionBar')
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self.failed_hint = QLabel()
        self.failed_hint.setObjectName('MutedLabel')
        layout.addWidget(self.failed_hint)
        layout.addStretch(1)

        self.retry_button = QPushButton()
        self.retry_button.setProperty('accent', True)
        self.retry_button.clicked.connect(self._retry_selected)
        layout.addWidget(self.retry_button)

        self.details_button = QPushButton()
        self.details_button.clicked.connect(self._show_error_details)
        layout.addWidget(self.details_button)

        self.remove_failed_button = QPushButton()
        self.remove_failed_button.clicked.connect(self._remove_selected)
        layout.addWidget(self.remove_failed_button)

        self.retry_all_button = QPushButton()
        self.retry_all_button.clicked.connect(self.controller.retry_all_failed)
        layout.addWidget(self.retry_all_button)

        self.remove_all_failed_button = QPushButton()
        self.remove_all_failed_button.clicked.connect(self._remove_all_failed)
        layout.addWidget(self.remove_all_failed_button)

        self.failed_bar = bar
        bar.hide()
        return bar

    def _build_stack(self) -> QWidget:
        self.stack = QStackedWidget()
        self.empty_state = EmptyState(self)
        self.stack.addWidget(self.empty_state)

        self.view = QListView()
        self.view.setObjectName('QueueView')
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(CardDelegate(self.thumbnails, self))
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.stack.addWidget(self.view)
        return self.stack

    def _build_shortcuts(self) -> None:
        self._actions = {}
        for key, sequence, slot in (
            ('paste', QKeySequence.StandardKey.Paste, self.paste_links),
            ('settings', QKeySequence('Ctrl+,'), self.open_settings),
            ('remove', QKeySequence.StandardKey.Delete, self._remove_selected),
            ('log', QKeySequence('Ctrl+L'), self._toggle_log),
            ('about', QKeySequence(QKeySequence.StandardKey.HelpContents), self.open_about),
        ):
            action = QAction(self)
            action.setShortcut(sequence)
            action.triggered.connect(slot)
            self.addAction(action)
            self._actions[key] = action

    def _connect(self) -> None:
        bar = self.top_bar
        bar.pasteRequested.connect(self.paste_links)
        bar.startRequested.connect(self.controller.start)
        bar.pauseRequested.connect(self.controller.pause)
        bar.cancelRequested.connect(self._cancel_selected)
        bar.directoryRequested.connect(self._choose_directory)
        bar.settingsRequested.connect(self.open_settings)
        bar.logToggled.connect(self._toggle_log)
        bar.defaultsChanged.connect(self._on_defaults_changed)

        self.controller.analysisFinished.connect(self._on_analysis_finished)
        self.controller.analysisFailed.connect(self._on_analysis_failed)
        self.controller.queueChanged.connect(self._refresh)
        self.controller.playlistsChanged.connect(self._refresh)
        self.controller.appStateChanged.connect(lambda *_: self._refresh())
        self.controller.logMessage.connect(self.log_dock.append)
        self.controller.reviewRequested.connect(self._on_review_requested)
        self.controller.taskFailed.connect(self._on_task_failed)
        self.controller.persistenceFailed.connect(self._on_persistence_failed)

        self.view.customContextMenuRequested.connect(self._show_context_menu)
        self.view.doubleClicked.connect(self._open_selected_file)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._refresh())
        self.thumbnails.loaded.connect(lambda *_: self.view.viewport().update())
        self._themes.themeChanged.connect(self._on_theme_changed)

    # --------------------------------------------------------------- text

    def retranslate_ui(self) -> None:
        self.setWindowTitle(f'{APP_TITLE} {__version__}')
        for queue_filter, button in self._filter_buttons.items():
            _set_tab_text(button, labels.queue_filter_label(queue_filter.value))
        self.search_edit.setPlaceholderText(self.tr('Search…'))
        self.search_edit.setAccessibleName(self.tr('Search downloads'))
        self.view.setAccessibleName(self.tr('Download queue'))
        self.batch_button.setAccessibleName(self.tr('More actions'))
        self.review_hint.setText(self.tr('These items need your decision:'))
        self.approve_button.setText(self.tr('Download'))
        self.skip_button.setText(self.tr('Skip'))
        self.approve_all_button.setText(self.tr('Download all'))
        self.skip_all_button.setText(self.tr('Skip all'))
        self.batch_button.setToolTip(self.tr('More actions'))
        self._batch_download_action.setText(self.tr('Download all in current queue'))
        self._batch_skip_action.setText(self.tr('Skip all in current queue'))
        self._about_action.setText(self.tr('About {0}').format(APP_TITLE))

        self.failed_hint.setText(self.tr('These downloads did not succeed:'))
        self.retry_button.setText(self.tr('Retry'))
        self.details_button.setText(self.tr('Show details'))
        self.remove_failed_button.setText(self.tr('Remove'))
        self.retry_all_button.setText(self.tr('Retry all'))
        self.remove_all_failed_button.setText(self.tr('Remove all'))
        self._refresh()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    @Slot(object)
    def _on_theme_changed(self, _theme: Theme) -> None:
        """QSS restyles the widgets itself; refresh the manually painted parts."""
        self.restyle()

    def restyle(self) -> None:
        icons.clear_cache()
        self.setWindowIcon(icons.app_icon())
        self.top_bar.restyle()
        self.empty_state.restyle()
        self.log_dock.restyle()
        self.view.viewport().update()

    def _restore_history(self) -> None:
        """Load earlier downloads; without this everything is lost on restart."""
        try:
            restored = self.controller.restore_history()
        except Exception as exc:  # noqa: BLE001 - a corrupt database must not block start-up
            self.log_dock.append('WARN', f'Could not load history: {exc}')
            return
        if restored:
            self.log_dock.append('INFO', f'Historia: {restored}')

    def clear_history(self) -> None:
        """Clear the history after confirmation. Downloaded files are never removed."""
        answer = QMessageBox.question(
            self, self.tr('Clear history'),
            self.tr('Are you sure you want to clear download history?\n\n'
                    'This removes download records, but does not delete '
                    'downloaded files from the disk.'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer is not QMessageBox.StandardButton.Yes:
            return
        self.controller.clear_history()
        self.statusBar().showMessage(self.tr('History cleared'), 5000)
        self._refresh()

    # ---------------------------------------------------------- adding URLs

    @Slot()
    def paste_links(self) -> None:
        from ..utils import formatting as fmt

        urls = fmt.extract_urls(QApplication.clipboard().text())
        if not urls:
            self.statusBar().showMessage(self.tr('The clipboard contains no address'), 5000)
            return
        self.add_urls(urls)

    def add_urls(self, urls: list[str]) -> None:
        for url in dict.fromkeys(urls):
            self.controller.analyze(url)
        self._refresh()

    @Slot(str, object)
    def _on_analysis_finished(self, _request_id: str, info: MediaInfo) -> None:
        if info.is_playlist:
            self._handle_playlist(info)
        elif self._settings.smart_mode:
            self.controller.enqueue([self._task_from_defaults(info)],
                                    autostart=self._settings.autostart)
        else:
            self._handle_single(info)
        self._refresh()

    @Slot(str, object)
    def _on_analysis_failed(self, _request_id: str, error: FriendlyError) -> None:
        self.statusBar().showMessage(labels.error_text(error), 10000)
        self.log_dock.append('ERROR', error.details)
        self._refresh()

    def _handle_single(self, info: MediaInfo) -> None:
        if not info.has_formats:
            self.statusBar().showMessage(
                labels.error_message(AppErrorCode.NO_FORMATS), 8000)
            return
        dialog = DownloadDialog(info, self._settings, self.thumbnails,
                                ffmpeg_available=self._ffmpeg.available, parent=self)
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        self._apply_settings(dialog.applied_settings())
        self.controller.enqueue([dialog.build_task()], autostart=self._settings.autostart)

    def _handle_playlist(self, info: MediaInfo) -> None:
        if not info.entries_complete:
            message = self.tr('The full playlist could not be loaded — found {0}, more may exist.')
            text = message.format(labels.items_count(info.entry_count))
            self.statusBar().showMessage(text, 12000)
            self.log_dock.append('WARN', f'{text} {info.entries_error}'.strip())

        if self._settings.smart_mode:
            tasks = [self._task_from_defaults_entry(info, entry) for entry in info.entries]
        else:
            dialog = PlaylistDialog(info, self._settings,
                                    ffmpeg_available=self._ffmpeg.available, parent=self)
            if dialog.exec() != int(QDialog.DialogCode.Accepted):
                return
            self._apply_settings(dialog.applied_settings())
            tasks = dialog.build_tasks()

        # A playlist gets its own record: the "Playlists" tab shows it as a
        # single row instead of every downloaded file separately
        job = PlaylistJob(
            title=info.playlist_title or info.title,
            source_url=info.webpage_url or info.url,
            thumbnail_url=info.thumbnail_url,
            uploader=info.author,
            discovered_items=info.entry_count if info.entries_complete else None,
            enumeration_complete=info.entries_complete,
            enumeration_error=info.entries_error,
        )
        self.controller.enqueue(tasks, autostart=self._settings.autostart, playlist=job)

    def _task_from_defaults(self, info: MediaInfo) -> DownloadTask:
        return DownloadTask(
            request=self._request_from_defaults(info.webpage_url or info.url),
            title=info.title,
            uploader=info.author,
            duration=info.duration,
            thumbnail_url=info.thumbnail_url,
            media_id=info.media_id,
            extractor=info.extractor,
        )

    def _task_from_defaults_entry(self, info: MediaInfo, entry) -> DownloadTask:
        request = self._request_from_defaults(entry.download_url)
        request.source_url = entry.url
        request.playlist_title = info.playlist_title
        request.playlist_index = entry.index
        request.create_playlist_folder = self._settings.create_playlist_folder
        request.number_playlist_files = self._settings.number_playlist_files
        return DownloadTask(
            request=request,
            title=entry.title,
            uploader=entry.uploader or info.author,
            duration=entry.duration,
            thumbnail_url=entry.thumbnail_url,
            media_id=entry.media_id,
            extractor=entry.extractor,
        )

    def _request_from_defaults(self, url: str) -> DownloadRequest:
        """A request built from the top-bar selection (smart mode)."""
        bar = self.top_bar
        s = self._settings
        audio = bar.kind is MediaKind.AUDIO
        ffmpeg = self._ffmpeg.available
        return DownloadRequest(
            url=url,
            output_dir=s.output_dir,
            kind=bar.kind,
            quality=bar.quality,
            container='' if audio else bar.container,
            audio_format=bar.container if audio else s.audio_format,
            write_subtitles=s.write_subtitles,
            auto_subtitles=s.auto_subtitles,
            embed_subtitles=s.embed_subtitles and ffmpeg,
            subtitle_languages=s.subtitle_language_list,
            embed_metadata=s.embed_metadata and ffmpeg,
            embed_chapters=s.embed_chapters and ffmpeg,
            embed_thumbnail=s.embed_thumbnail and ffmpeg,
            write_thumbnail=s.write_thumbnail,
            write_info_json=s.write_info_json,
            write_description=s.write_description,
            parse_artist_title=s.parse_artist_title,
        )

    # ---------------------------------------------------------- interaction

    def _selected_tasks(self) -> list[DownloadTask]:
        tasks = []
        for index in self.view.selectionModel().selectedIndexes():
            task = index.data(TASK_ROLE)
            if task is not None:
                tasks.append(task)
        return tasks

    def _selected_playlists(self) -> list[PlaylistJob]:
        jobs = []
        for index in self.view.selectionModel().selectedIndexes():
            job = index.data(PLAYLIST_ROLE)
            if job is not None:
                jobs.append(job)
        return jobs

    @Slot()
    def _cancel_selected(self) -> None:
        tasks = self._selected_tasks()
        for job in self._selected_playlists():
            tasks.extend(job.tasks)
        if tasks:
            self.controller.cancel([task.id for task in tasks])
        else:
            self.controller.cancel_active()

    @Slot()
    def _remove_selected(self) -> None:
        tasks = self._selected_tasks()
        for job in self._selected_playlists():
            tasks.extend(job.tasks)
        if tasks:
            self.controller.remove([task.id for task in tasks])

    @Slot()
    def _approve_selected(self) -> None:
        tasks = self._selected_tasks() or self.controller.pending_review()
        self.controller.approve([task.id for task in tasks])

    @Slot()
    def _skip_selected(self) -> None:
        tasks = self._selected_tasks() or self.controller.pending_review()
        self.controller.skip([task.id for task in tasks])

    @Slot(object)
    def _on_review_requested(self, task) -> None:
        """A quiet notice instead of a modal dialog for every duplicate."""
        self.statusBar().showMessage(
            self.tr('Duplicate found — “{0}” needs your decision.').format(task.display_title),
            10000)

    @Slot(str)
    def _on_persistence_failed(self, _detail: str) -> None:
        """The download itself is fine; only the bookkeeping failed."""
        self.statusBar().showMessage(
            self.tr('Could not save download history. The download itself is unaffected.'),
            8000)

    @Slot(object)
    def _on_task_failed(self, task) -> None:
        """A quiet notice, without a modal dialog for every item."""
        self.statusBar().showMessage(
            self.tr('Could not download “{0}”. See the Failed tab.').format(task.display_title),
            10000)

    @Slot()
    def _show_error_details(self) -> None:
        tasks = [task for task in self._selected_tasks() if task.state.is_failed]
        tasks = tasks or self.controller.failed_tasks()
        if tasks:
            ErrorDetailsDialog(tasks[0], self).exec()

    def _remove_all_failed(self) -> None:
        if not self.controller.failed_tasks():
            return
        answer = QMessageBox.question(
            self, self.tr('Remove entries?'),
            self.tr('Remove all failed entries from history?\n\n'
                    'Downloaded files will not be deleted.'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer is QMessageBox.StandardButton.Yes:
            self.controller.remove_failed()

    @Slot()
    def _retry_selected(self) -> None:
        tasks = self._selected_tasks()
        for job in self._selected_playlists():
            tasks.extend(job.tasks)
        if tasks:
            self.controller.retry([task.id for task in tasks])

    def _show_context_menu(self, position) -> None:
        index = self.view.indexAt(position)
        if index.isValid() and not self.view.selectionModel().isSelected(index):
            self.view.selectionModel().select(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
        tasks = self._selected_tasks()
        jobs = self._selected_playlists()
        if not tasks and not jobs:
            return

        menu = QMenu(self)
        first = tasks[0] if tasks else None
        if first is not None and first.filepath and os.path.exists(first.filepath):
            menu.addAction(icons.icon('video'), self.tr('Open file'), self._open_selected_file)
            menu.addAction(icons.icon('folder'), self.tr('Show in folder'), self._open_folder)
            menu.addSeparator()
        menu.addAction(self.tr('Copy address'), self._copy_urls)

        if any(task.state.needs_decision for task in tasks):
            menu.addSeparator()
            menu.addAction(icons.icon('download'), self.tr('Download'), self._approve_selected)
            menu.addAction(icons.icon('skip'), self.tr('Skip'), self._skip_selected)

        if any(task.state.is_failed for task in tasks):
            menu.addSeparator()
            menu.addAction(icons.icon('retry'), self.tr('Retry'), self._retry_selected)
            menu.addAction(icons.icon('review'), self.tr('Show details'),
                           self._show_error_details)

        candidates = tasks + [task for job in jobs for task in job.tasks]
        if any(task.state.is_final for task in candidates):
            menu.addAction(icons.icon('retry'), self.tr('Download again'), self._retry_selected)
        if any(not task.state.is_final for task in candidates):
            menu.addAction(icons.icon('cancel'), self.tr('Cancel'), self._cancel_selected)
        menu.addSeparator()
        menu.addAction(self.tr('Remove from history'), self._remove_selected)
        menu.addAction(self.tr('Remove completed'), self.controller.remove_finished)
        menu.exec(self.view.viewport().mapToGlobal(position))

    @Slot(QModelIndex)
    def _open_selected_file(self, *_args) -> None:
        tasks = self._selected_tasks()
        if tasks and tasks[0].filepath and os.path.exists(tasks[0].filepath):
            QDesktopServices.openUrl(QUrl.fromLocalFile(tasks[0].filepath))

    def _open_folder(self) -> None:
        tasks = self._selected_tasks()
        if not tasks:
            return
        path = tasks[0].filepath
        directory = os.path.dirname(path) if path else tasks[0].request.output_dir
        if not os.path.isdir(directory):
            return
        if sys.platform.startswith('linux'):
            try:
                subprocess.Popen(['xdg-open', directory])
                return
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(directory))

    def _copy_urls(self) -> None:
        tasks = self._selected_tasks()
        urls = [task.url for task in tasks] + [job.source_url for job in self._selected_playlists()]
        if urls:
            QApplication.clipboard().setText('\n'.join(urls))

    def _toggle_log(self) -> None:
        self.log_dock.setVisible(not self.log_dock.isVisible())

    @Slot()
    def open_settings(self) -> None:
        dialog = SettingsDialog(self._settings, self._themes, self._translations,
                                self._ffmpeg.message, self,
                                history_count=self.controller.history_count(),
                                on_clear_history=self.clear_history)
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        self._apply_settings(dialog.result_settings())
        self._ffmpeg = self._service.ffmpeg_status()
        self.top_bar.apply_settings(self._settings)
        self.statusBar().showMessage(self.tr('Settings saved'), 4000)

    @Slot()
    def open_about(self) -> None:
        """Identity and versions; the technical block lives in Preferences."""
        AboutDialog(self, self._themes).exec()

    def _choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, self.tr('Download folder'), self._settings.output_dir)
        if directory:
            self._apply_settings(self._settings.replace(output_dir=directory))
            self.top_bar.update_directory(directory)

    def _on_defaults_changed(self) -> None:
        bar = self.top_bar
        changes = {'kind': bar.kind.value, 'quality': bar.quality}
        if bar.kind is MediaKind.AUDIO:
            changes['audio_format'] = bar.container
        else:
            changes['video_container'] = bar.container
        self._apply_settings(self._settings.replace(**changes))

    def _apply_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self._store.save(settings)
        self._service.update_settings(settings)

    def _set_filter(self, queue_filter: QueueFilter) -> None:
        self._filter = queue_filter
        for key, button in self._filter_buttons.items():
            button.setChecked(key is queue_filter)
        self.review_bar.setVisible(queue_filter is QueueFilter.NEEDS_REVIEW)
        self.failed_bar.setVisible(queue_filter is QueueFilter.FAILED)

        # Playlists have their own model whose row is a playlist, not a file
        if queue_filter.uses_playlist_model:
            self.view.setModel(self.playlist_model)
        else:
            self.view.setModel(self.proxy)
            self.proxy.set_filter(queue_filter)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._refresh())
        self.search_edit.setEnabled(not queue_filter.uses_playlist_model)
        self._refresh()

    # --------------------------------------------------------------- view

    def _announce_dependencies(self) -> None:
        """Say once, at start-up, what is missing and what it costs.

        Detection is structural - the tools were probed directly - so nothing
        here depends on catching a phrase in yt-dlp's output. A packaged build
        normally reaches none of the warnings, because it bundles both.
        """
        level = 'INFO' if self._ffmpeg.available else 'WARN'
        self.log_dock.append(level, self._ffmpeg.message)

        js_runtime = self._service.tools.deno
        self.log_dock.append(
            'INFO' if js_runtime.usable else 'WARN',
            f'JavaScript runtime: {diagnostics.describe_tool(js_runtime)}')

        # One status bar message, and the more damaging problem wins
        if not self._ffmpeg.available:
            self.statusBar().showMessage(self.tr(
                'FFmpeg was not found. Merging, conversion and audio extraction '
                'will not work.'), 15000)
        elif not js_runtime.usable:
            self.statusBar().showMessage(self.tr(
                'No supported JavaScript runtime was found. Some YouTube formats '
                'may be unavailable.'), 15000)

    def _refresh(self) -> None:
        if self._filter.uses_playlist_model:
            visible = len(self.controller.playlists)
        else:
            visible = self.proxy.rowCount()
        self.count_label.setText(labels.items_count(visible))
        self.stack.setCurrentIndex(1 if visible else 0)
        self._refresh_tab_badges()

        self.top_bar.apply_state(
            self.controller.state,
            running=self.controller.is_running,
            has_selection=bool(self.view.selectionModel().hasSelection()),
        )
        self.statusBar().showMessage(self._status_text())

    def _refresh_tab_badges(self) -> None:
        """Tab badge; for now only where something is waiting for an action."""
        pending = len(self.controller.pending_review())
        button = self._filter_buttons[QueueFilter.NEEDS_REVIEW]
        label = labels.queue_filter_label(QueueFilter.NEEDS_REVIEW.value)
        _set_tab_text(button, f'{label}  {pending}' if pending else label)

        has_pending = bool(pending)
        for widget in (self.approve_all_button, self.skip_all_button, self.batch_button):
            widget.setEnabled(has_pending)

        failed = len(self.controller.failed_tasks())
        failed_button = self._filter_buttons[QueueFilter.FAILED]
        failed_label = labels.queue_filter_label(QueueFilter.FAILED.value)
        _set_tab_text(failed_button, f'{failed_label}  {failed}' if failed else failed_label)
        for widget in (self.retry_all_button, self.remove_all_failed_button,
                       self.details_button):
            widget.setEnabled(bool(failed))

    def _status_text(self) -> str:
        parts = []
        pending = self.controller.pending_analyses
        if pending:
            parts.append(self.tr('Analysing {0}…').format(labels.items_count(pending)))

        active = self.controller.active_task
        if active is not None:
            if active.state is TaskState.POSTPROCESSING:
                stage = (labels.postprocess_stage_label(active.stage) if active.stage
                         else labels.task_state_label(TaskState.POSTPROCESSING))
                parts.append(f'{active.display_title} — {stage}')
            else:
                from ..utils import formatting as fmt
                parts.append(f'{active.display_title} — {active.percent:.0f}% '
                             f'({fmt.speed(active.progress.speed)})')

        waiting = self.controller.count_in_state(TaskState.QUEUED)
        if waiting:
            parts.append(self.tr('queued: {0}').format(waiting))
        failed = self.controller.count_in_state(TaskState.ERROR)
        if failed:
            parts.append(self.tr('errors: {0}').format(failed))
        partial = self.controller.count_in_state(TaskState.COMPLETED_WITH_ERRORS)
        if partial:
            parts.append(self.tr('completed with errors: {0}').format(partial))
        review = len(self.controller.pending_review())
        if review:
            parts.append(self.tr('awaiting decision: {0}').format(review))
        if not self.controller.is_running and active is None and waiting:
            parts.append(self.tr('paused'))
        return ' · '.join(parts) or self._idle_message()

    def _idle_message(self) -> str:
        state = self.controller.state
        if state is AppState.FINISHED:
            return self.tr('All downloads finished')
        if state is AppState.ERROR:
            return self.tr('Finished with errors — see the log for details')
        if state is AppState.CANCELLED:
            return self.tr('Cancelled')
        return self.tr('Ready')

    # ----------------------------------------------------------- window

    def _restore_window(self) -> None:
        geometry = self._store.geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self._store.window_state()
        if state is not None:
            self.restoreState(state)
            self.log_dock.hide()

    def closeEvent(self, event) -> None:
        if getattr(self, '_shutdown_done', False):
            # Already shut down (a signal, session logout); asking again would
            # block the close behind a dialog nobody is there to answer
            event.accept()
            return

        busy = self.controller.count_in_state(TaskState.DOWNLOADING, TaskState.POSTPROCESSING)
        if busy:
            answer = QMessageBox.question(
                self, self.tr('Close the program?'),
                self.tr('A download is in progress. Closing will interrupt it. Continue?'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer is not QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        self._store.save_geometry(self.saveGeometry(), self.saveState())
        self.shutdown()
        event.accept()

    def shutdown(self) -> None:
        """Orderly thread shutdown. Safe to call more than once."""
        if getattr(self, '_shutdown_done', False):
            return
        self._shutdown_done = True
        self._store.save(self._settings)
        self.thumbnails.shutdown()
        self.controller.shutdown()
        self.controller.close_history()


def _set_tab_text(button: QToolButton, text: str) -> None:
    """Set the caption and prevent elision so the tab stays readable."""
    button.setText(text)
    button.setMinimumWidth(button.sizeHint().width())
