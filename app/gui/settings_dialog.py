"""Application preferences: every `AppSettings` field plus appearance.

The "Appearance" section covers theme and language. Both apply immediately as
a live preview, and Cancel restores the state from before the dialog opened.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_TITLE
from ..core import diagnostics
from ..core import format_service as fs
from ..core.models import MediaKind
from ..i18n import TranslationManager
from ..settings import DEFAULT_OUTTMPL, AppSettings
from ..theme import ThemeManager
from . import labels
from .about_dialog import AboutDialog
from .focus import order_button_box

#: Browsers supported by yt_dlp.cookies.SUPPORTED_BROWSERS
BROWSERS: tuple[str, ...] = (
    '', 'firefox', 'chrome', 'chromium', 'brave', 'edge', 'opera', 'safari', 'vivaldi', 'whale',
)

#: SponsorBlock categories recognised by SponsorBlockPP
SPONSOR_CATEGORIES: tuple[str, ...] = (
    'sponsor', 'selfpromo', 'intro', 'outro', 'interaction', 'music_offtopic',
)

OUTTMPL_PRESETS: tuple[str, ...] = (
    DEFAULT_OUTTMPL,
    '%(title)s [%(id)s].%(ext)s',
    '%(uploader)s - %(title)s.%(ext)s',
    '%(upload_date>%Y-%m-%d)s - %(title)s.%(ext)s',
)


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, theme_manager: ThemeManager,
                 translations: TranslationManager, ffmpeg_message: str = '', parent=None,
                 *, history_count: int = 0, on_clear_history=None):
        super().__init__(parent)
        self._history_count = history_count
        self._on_clear_history = on_clear_history
        self._settings = settings
        self._themes = theme_manager
        self._translations = translations
        # Remembered in case of Cancel, because the preview is live
        self._initial_theme = theme_manager.key
        self._initial_language = translations.code
        self._ffmpeg_message = ffmpeg_message

        self.setMinimumSize(660, 580)
        self._build()
        self._link_labels()
        self._load()
        self.retranslate_ui()

    def _link_labels(self) -> None:
        """Make every form label the buddy of the control it describes.

        `QFormLayout.addRow()` only sets the buddy for the overload that builds
        the label itself. These labels are kept as attributes so they can be
        retranslated, so the link has to be made here - without it a screen
        reader announces the combo boxes and fields with no name at all.
        """
        for form in self.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if label_item is None or field_item is None:
                    continue
                label = label_item.widget()
                if not isinstance(label, QLabel):
                    continue
                field = _first_focusable(field_item)
                if field is not None:
                    label.setBuddy(field)

    # -------------------------------------------------------- construction

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.setAccessibleName(self.tr('Settings sections'))
        self.tabs.addTab(self._tab_general(), '')
        self.tabs.addTab(self._tab_files(), '')
        self.tabs.addTab(self._tab_metadata(), '')
        self.tabs.addTab(self._tab_subtitles(), '')
        self.tabs.addTab(self._tab_network(), '')
        self.tabs.addTab(self._tab_about(), '')
        layout.addWidget(self.tabs, 1)

        self.buttons = QDialogButtonBox()
        self._cancel_button = self.buttons.addButton('', QDialogButtonBox.ButtonRole.RejectRole)
        self._save_button = self.buttons.addButton('', QDialogButtonBox.ButtonRole.AcceptRole)
        self._save_button.setProperty('accent', True)
        self._save_button.setDefault(True)
        self._cancel_button.clicked.connect(self.reject)
        self._save_button.clicked.connect(self.accept)
        layout.addWidget(self.buttons)
        order_button_box(self, self.buttons)

    def _tab_general(self) -> QWidget:
        page, form = _form_page()
        self._form_general = form

        self.appearance_section = _section()
        form.addRow(self.appearance_section)

        self.theme_combo = QComboBox()
        self.theme_combo.currentIndexChanged.connect(self._preview_theme)
        self.theme_row_label = QLabel()
        form.addRow(self.theme_row_label, self.theme_combo)

        self.language_combo = QComboBox()
        # Language names always appear in their own language; never translated
        for language in self._translations.languages:
            self.language_combo.addItem(language.native_name, language.code)
        self.language_combo.currentIndexChanged.connect(self._preview_language)
        self.language_row_label = QLabel()
        form.addRow(self.language_row_label, self.language_combo)

        self.appearance_hint = _hint()
        form.addRow('', self.appearance_hint)

        self.download_section = _section()
        form.addRow(self.download_section)

        row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        row.addWidget(self.dir_edit, 1)
        self.dir_browse = QPushButton()
        self.dir_browse.clicked.connect(lambda: _pick_dir(self, self.dir_edit))
        row.addWidget(self.dir_browse)
        self.dir_row_label = QLabel()
        form.addRow(self.dir_row_label, row)

        self.kind_combo = QComboBox()
        self.kind_row_label = QLabel()
        form.addRow(self.kind_row_label, self.kind_combo)

        self.quality_combo = QComboBox()
        self.quality_row_label = QLabel()
        form.addRow(self.quality_row_label, self.quality_combo)

        self.video_container_combo = QComboBox()
        self.container_row_label = QLabel()
        form.addRow(self.container_row_label, self.video_container_combo)

        self.audio_format_combo = QComboBox()
        self.audio_row_label = QLabel()
        form.addRow(self.audio_row_label, self.audio_format_combo)

        self.smart_check = QCheckBox()
        form.addRow('', self.smart_check)
        self.autostart_check = QCheckBox()
        form.addRow('', self.autostart_check)
        self.verbose_check = QCheckBox()
        form.addRow('', self.verbose_check)
        return page

    def _tab_files(self) -> QWidget:
        page, form = _form_page()

        self.outtmpl_preset = QComboBox()
        self.outtmpl_preset.currentIndexChanged.connect(self._apply_outtmpl_preset)
        self.preset_row_label = QLabel()
        form.addRow(self.preset_row_label, self.outtmpl_preset)

        self.outtmpl_edit = QLineEdit()
        self.outtmpl_row_label = QLabel()
        form.addRow(self.outtmpl_row_label, self.outtmpl_edit)

        self.outtmpl_hint = _hint()
        form.addRow('', self.outtmpl_hint)

        self.playlist_section = _section()
        form.addRow(self.playlist_section)
        self.playlist_folder_check = QCheckBox()
        form.addRow('', self.playlist_folder_check)
        self.playlist_number_check = QCheckBox()
        form.addRow('', self.playlist_number_check)
        self.playlist_hint = _hint()
        form.addRow('', self.playlist_hint)

        self.restrict_check = QCheckBox()
        form.addRow('', self.restrict_check)
        self.overwrite_check = QCheckBox()
        form.addRow('', self.overwrite_check)

        self.history_section = _section()
        form.addRow(self.history_section)
        self.history_count_label = QLabel()
        self.history_row_label = QLabel()
        form.addRow(self.history_row_label, self.history_count_label)
        self.clear_history_button = QPushButton()
        self.clear_history_button.clicked.connect(self._clear_history)
        self.clear_history_button.setEnabled(self._on_clear_history is not None)
        form.addRow('', self.clear_history_button)
        self.history_hint = _hint()
        form.addRow('', self.history_hint)
        return page

    def _tab_metadata(self) -> QWidget:
        page, form = _form_page()

        self.metadata_check = QCheckBox()
        form.addRow('', self.metadata_check)
        self.chapters_check = QCheckBox()
        form.addRow('', self.chapters_check)
        self.embed_thumb_check = QCheckBox()
        form.addRow('', self.embed_thumb_check)
        self.thumb_hint = _hint()
        form.addRow('', self.thumb_hint)
        self.write_thumb_check = QCheckBox()
        form.addRow('', self.write_thumb_check)
        self.artist_check = QCheckBox()
        form.addRow('', self.artist_check)
        self.infojson_check = QCheckBox()
        form.addRow('', self.infojson_check)
        self.description_check = QCheckBox()
        form.addRow('', self.description_check)

        self.sponsor_section = _section()
        form.addRow(self.sponsor_section)
        self.sponsor_checks: dict[str, QCheckBox] = {}
        for value in SPONSOR_CATEGORIES:
            check = QCheckBox()
            self.sponsor_checks[value] = check
            form.addRow('', check)
        return page

    def _tab_subtitles(self) -> QWidget:
        page, form = _form_page()

        self.subs_check = QCheckBox()
        form.addRow('', self.subs_check)
        self.auto_subs_check = QCheckBox()
        form.addRow('', self.auto_subs_check)
        self.embed_subs_check = QCheckBox()
        form.addRow('', self.embed_subs_check)

        self.sub_langs_edit = QLineEdit()
        self.sub_langs_row_label = QLabel()
        form.addRow(self.sub_langs_row_label, self.sub_langs_edit)
        self.subs_hint = _hint()
        form.addRow('', self.subs_hint)
        return page

    def _tab_network(self) -> QWidget:
        page, form = _form_page()

        self.rate_edit = QLineEdit()
        self.rate_row_label = QLabel()
        form.addRow(self.rate_row_label, self.rate_edit)

        self.fragments_spin = QSpinBox()
        self.fragments_spin.setRange(1, 32)
        self.fragments_row_label = QLabel()
        form.addRow(self.fragments_row_label, self.fragments_spin)

        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 100)
        self.retries_row_label = QLabel()
        form.addRow(self.retries_row_label, self.retries_spin)

        self.job_retries_spin = QSpinBox()
        self.job_retries_spin.setRange(0, 20)
        self.job_retries_row_label = QLabel()
        form.addRow(self.job_retries_row_label, self.job_retries_spin)

        self.job_delay_spin = QSpinBox()
        self.job_delay_spin.setRange(0, 600)
        self.job_delay_row_label = QLabel()
        form.addRow(self.job_delay_row_label, self.job_delay_spin)

        self.retries_hint = _hint()
        form.addRow('', self.retries_hint)

        self.proxy_edit = QLineEdit()
        self.proxy_row_label = QLabel()
        form.addRow(self.proxy_row_label, self.proxy_edit)

        self.cookies_combo = QComboBox()
        self.cookies_row_label = QLabel()
        form.addRow(self.cookies_row_label, self.cookies_combo)

        row = QHBoxLayout()
        self.cookies_file_edit = QLineEdit()
        row.addWidget(self.cookies_file_edit, 1)
        self.cookies_browse = QPushButton()
        self.cookies_browse.clicked.connect(self._pick_cookie_file)
        row.addWidget(self.cookies_browse)
        self.cookies_file_row_label = QLabel()
        form.addRow(self.cookies_file_row_label, row)
        self.cookies_hint = _hint()
        form.addRow('', self.cookies_hint)

        self.ffmpeg_section = _section()
        form.addRow(self.ffmpeg_section)
        ffmpeg_row = QHBoxLayout()
        self.ffmpeg_edit = QLineEdit()
        ffmpeg_row.addWidget(self.ffmpeg_edit, 1)
        self.ffmpeg_browse = QPushButton()
        self.ffmpeg_browse.clicked.connect(lambda: _pick_dir(self, self.ffmpeg_edit))
        ffmpeg_row.addWidget(self.ffmpeg_browse)
        self.ffmpeg_row_label = QLabel()
        form.addRow(self.ffmpeg_row_label, ffmpeg_row)

        self.ffmpeg_status = QLabel()
        self.ffmpeg_status.setWordWrap(True)
        self.ffmpeg_status_label = QLabel()
        form.addRow(self.ffmpeg_status_label, self.ffmpeg_status)
        return page

    def _tab_about(self) -> QWidget:
        """Versions and resolved dependency paths, ready to paste into a report."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.about_title = QLabel()
        self.about_title.setObjectName('TitleLabel')
        layout.addWidget(self.about_title)

        self.about_text = QPlainTextEdit()
        self.about_text.setReadOnly(True)
        self.about_text.setObjectName('LogView')
        layout.addWidget(self.about_text, 1)

        row = QHBoxLayout()
        self.about_button = QPushButton()
        self.about_button.clicked.connect(self._open_about)
        row.addWidget(self.about_button)
        row.addStretch(1)
        self.copy_diagnostics_button = QPushButton()
        self.copy_diagnostics_button.clicked.connect(self._copy_diagnostics)
        row.addWidget(self.copy_diagnostics_button)
        layout.addLayout(row)

        self.about_hint = _hint()
        layout.addWidget(self.about_hint)
        return page

    def _open_about(self) -> None:
        AboutDialog(self, self._themes).exec()

    def _copy_diagnostics(self) -> None:
        QApplication.clipboard().setText(self.about_text.toPlainText())
        self.copy_diagnostics_button.setText(self.tr('Copied'))
        QTimer.singleShot(1500, lambda: self.copy_diagnostics_button.setText(
            self.tr('Copy system information')))

    # --------------------------------------------------------------- text

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr('Preferences'))
        for index, text in enumerate((
            self.tr('General'), self.tr('Files'), self.tr('Metadata and cover art'),
            self.tr('Subtitles'), self.tr('Network and FFmpeg'), self.tr('Diagnostics'),
        )):
            self.tabs.setTabText(index, text)

        self._cancel_button.setText(self.tr('Cancel'))
        self._save_button.setText(self.tr('Save'))

        self.about_title.setText(self.tr('Version and dependencies'))
        self.copy_diagnostics_button.setText(self.tr('Copy system information'))
        self.about_button.setText(self.tr('About {0}').format(APP_TITLE))
        self.about_hint.setText(self.tr(
            'Attach this to a bug report. Paths and versions only; nothing personal.'))
        # Deliberately untranslated: this block is technical and goes to a report
        self.about_text.setPlainText(diagnostics.collect().as_text())

        self.appearance_section.setText(self.tr('Appearance'))
        self.theme_row_label.setText(self.tr('Theme:'))
        self.language_row_label.setText(self.tr('Language:'))
        self.appearance_hint.setText(
            self.tr('Changes apply immediately. Cancelling restores the previous choice.'))

        self.download_section.setText(self.tr('Downloading'))
        self.dir_row_label.setText(self.tr('Download folder:'))
        self.dir_browse.setText(self.tr('Choose…'))
        self.dir_browse.setAccessibleName(self.tr('Choose destination folder'))
        self.kind_row_label.setText(self.tr('Default mode:'))
        self.quality_row_label.setText(self.tr('Default quality:'))
        self.container_row_label.setText(self.tr('Default video container:'))
        self.audio_row_label.setText(self.tr('Default audio format:'))
        self.smart_check.setText(
            self.tr('Automatic mode — download at once, without the format window'))
        self.autostart_check.setText(self.tr('Start downloading as soon as items are queued'))
        self.verbose_check.setText(self.tr('Verbose log (diagnostics)'))

        self.preset_row_label.setText(self.tr('Ready-made patterns:'))
        self.outtmpl_row_label.setText(self.tr('File name:'))
        self.outtmpl_hint.setText(
            self.tr('yt-dlp fields such as %(title)s, %(id)s, %(uploader)s, %(ext)s.'))
        self.playlist_section.setText(self.tr('Playlists'))
        self.playlist_folder_check.setText(self.tr('Create a separate folder for playlists'))
        self.playlist_number_check.setText(self.tr('Number playlist files'))
        self.playlist_number_check.setToolTip(
            self.tr('Add the playlist position before the file name'))
        self.playlist_hint.setText(
            self.tr('The playlist name is only used as a folder — never as part of '
                    'the file name.'))
        self.restrict_check.setText(self.tr('Limit file names to ASCII characters'))
        self.overwrite_check.setText(self.tr('Overwrite existing files'))

        self.history_section.setText(self.tr('Download history'))
        self.history_row_label.setText(self.tr('Stored records:'))
        self.history_count_label.setText(labels.items_count(self._history_count))
        self.clear_history_button.setText(self.tr('Clear history'))
        self.history_hint.setText(self.tr('Downloaded files will not be deleted.'))

        self.metadata_check.setText(self.tr('Save tags (title, author, date, description)'))
        self.chapters_check.setText(self.tr('Save chapters'))
        self.embed_thumb_check.setText(self.tr('Embed cover art in the file'))
        self.thumb_hint.setText(self.tr('Supported containers: MP3, M4A/MP4, MKV/MKA, OPUS, FLAC.'))
        self.write_thumb_check.setText(self.tr('Also save cover art as a separate image'))
        self.artist_check.setText(
            self.tr('Split “Artist - Title” into separate tags (audio mode)'))
        self.infojson_check.setText(self.tr('Save full metadata next to the file (.info.json)'))
        self.description_check.setText(self.tr('Save the description to a .description file'))
        self.sponsor_section.setText(self.tr('SponsorBlock — cut out segments'))
        for value, text in zip(SPONSOR_CATEGORIES, (
            self.tr('Sponsors'), self.tr('Self-promotion'), self.tr('Intro'), self.tr('Outro'),
            self.tr('Subscription reminders'), self.tr('Non-music sections'),
        ), strict=True):
            self.sponsor_checks[value].setText(text)

        self.subs_check.setText(self.tr('Download subtitles by default'))
        self.auto_subs_check.setText(self.tr('Allow automatically generated subtitles'))
        self.embed_subs_check.setText(self.tr('Embed subtitles in the video file'))
        self.sub_langs_row_label.setText(self.tr('Preferred languages:'))
        self.sub_langs_edit.setPlaceholderText('pl,en')
        self.subs_hint.setText(
            self.tr('Comma-separated language codes; “all” downloads everything available. '
                    'The download window narrows the list to subtitles the item actually has.'))

        self.rate_row_label.setText(self.tr('Speed limit:'))
        self.rate_edit.setPlaceholderText(self.tr('no limit, e.g. 2M or 500K'))
        self.fragments_row_label.setText(self.tr('Parallel fragments:'))
        self.retries_row_label.setText(self.tr('yt-dlp retries:'))
        self.job_retries_row_label.setText(self.tr('Job retries:'))
        self.job_delay_row_label.setText(self.tr('Delay between job retries (s):'))
        self.retries_hint.setText(
            self.tr('The first value applies inside a single yt-dlp attempt (HTTP, fragments). '
                    'The second repeats the whole job; only after using it up does an item '
                    'move to the Failed tab.'))
        self.proxy_row_label.setText(self.tr('Proxy:'))
        self.proxy_edit.setPlaceholderText(self.tr('e.g. socks5://127.0.0.1:1080'))
        self.cookies_row_label.setText(self.tr('Cookies from browser:'))
        self.cookies_file_row_label.setText(self.tr('Cookie file:'))
        self.cookies_file_edit.setPlaceholderText(self.tr('cookies.txt file (optional)'))
        self.cookies_browse.setText(self.tr('Choose…'))
        self.cookies_browse.setAccessibleName(self.tr('Choose cookies file'))
        self.cookies_hint.setText(
            self.tr('Cookies allow downloading private or age-restricted items '
                    'and items that require signing in.'))
        self.ffmpeg_section.setText(self.tr('FFmpeg'))
        self.ffmpeg_row_label.setText(self.tr('FFmpeg folder:'))
        self.ffmpeg_edit.setPlaceholderText(self.tr('detect automatically'))
        self.ffmpeg_browse.setText(self.tr('Choose…'))
        self.ffmpeg_browse.setAccessibleName(self.tr('Choose FFmpeg location'))
        self.ffmpeg_status_label.setText(self.tr('Status:'))
        self.ffmpeg_status.setText(self._ffmpeg_message)
        self.ffmpeg_status.setObjectName(
            'StatusOk' if self._ffmpeg_message.startswith('FFmpeg') else 'StatusWarn')

        self._reload_combos()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _reload_combos(self) -> None:
        _refill(self.kind_combo,
                [(kind.value, labels.media_kind_label(kind)) for kind in MediaKind])
        _refill(self.quality_combo,
                [(value, labels.quality_label(value)) for value in fs.QUALITY_LADDER])
        _refill(self.video_container_combo,
                [(value, labels.container_label(value)) for value in fs.VIDEO_CONTAINERS])
        _refill(self.audio_format_combo,
                [(value, labels.audio_format_label(value)) for value in fs.AUDIO_FORMATS])
        _refill(self.cookies_combo,
                [(name, name.capitalize() if name else self.tr('— do not use —'))
                 for name in BROWSERS])
        _refill(self.outtmpl_preset,
                [('', self.tr('— custom —'))]
                + [(value, f'{name}   ({value})') for value, name in zip(OUTTMPL_PRESETS, (
                    self.tr('Title'), self.tr('Title [ID]'), self.tr('Author - Title'),
                    self.tr('Date - Title')), strict=True)])
        _select(self.theme_combo_entries(), self.theme_combo, self._themes.key)
        _select(None, self.language_combo, self._translations.code)

    def theme_combo_entries(self):
        """Theme names are translated, but their identifiers stay stable."""
        entries = [(theme.key, labels.theme_name(theme.key)) for theme in self._themes.themes]
        _refill(self.theme_combo, entries)
        return entries

    # -------------------------------------------------------------- data

    def _load(self) -> None:
        s = self._settings
        self.dir_edit.setText(s.output_dir)
        self.smart_check.setChecked(s.smart_mode)
        self.autostart_check.setChecked(s.autostart)
        self.verbose_check.setChecked(s.verbose_log)

        self.outtmpl_edit.setText(s.outtmpl)
        self.playlist_folder_check.setChecked(s.create_playlist_folder)
        self.playlist_number_check.setChecked(s.number_playlist_files)
        self.restrict_check.setChecked(s.restrict_filenames)
        self.overwrite_check.setChecked(s.overwrite)

        self.metadata_check.setChecked(s.embed_metadata)
        self.chapters_check.setChecked(s.embed_chapters)
        self.embed_thumb_check.setChecked(s.embed_thumbnail)
        self.write_thumb_check.setChecked(s.write_thumbnail)
        self.artist_check.setChecked(s.parse_artist_title)
        self.infojson_check.setChecked(s.write_info_json)
        self.description_check.setChecked(s.write_description)
        active = s.sponsorblock_categories
        for value, check in self.sponsor_checks.items():
            check.setChecked(value in active)

        self.subs_check.setChecked(s.write_subtitles)
        self.auto_subs_check.setChecked(s.auto_subtitles)
        self.embed_subs_check.setChecked(s.embed_subtitles)
        self.sub_langs_edit.setText(s.subtitle_languages)

        self.rate_edit.setText(s.rate_limit)
        self.fragments_spin.setValue(s.concurrent_fragments)
        self.retries_spin.setValue(s.retries)
        self.job_retries_spin.setValue(s.job_retries)
        self.job_delay_spin.setValue(s.job_retry_delay)
        self.proxy_edit.setText(s.proxy)
        self.cookies_file_edit.setText(s.cookies_file)
        self.ffmpeg_edit.setText(s.ffmpeg_location)
        self._pending = s

    def _apply_saved_selection(self) -> None:
        """Restore the combo selections after a rebuild, e.g. a language change."""
        s = self._settings
        for combo, value in ((self.kind_combo, s.kind),
                             (self.quality_combo, s.quality),
                             (self.video_container_combo, s.video_container),
                             (self.audio_format_combo, s.audio_format),
                             (self.cookies_combo, s.cookies_from_browser)):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)

    def result_settings(self) -> AppSettings:
        sponsors = ','.join(value for value, check in self.sponsor_checks.items() if check.isChecked())
        return self._settings.replace(
            output_dir=self.dir_edit.text().strip() or self._settings.output_dir,
            kind=self.kind_combo.currentData(),
            quality=self.quality_combo.currentData(),
            video_container=self.video_container_combo.currentData(),
            audio_format=self.audio_format_combo.currentData(),
            smart_mode=self.smart_check.isChecked(),
            autostart=self.autostart_check.isChecked(),
            verbose_log=self.verbose_check.isChecked(),
            outtmpl=self.outtmpl_edit.text().strip() or DEFAULT_OUTTMPL,
            create_playlist_folder=self.playlist_folder_check.isChecked(),
            number_playlist_files=self.playlist_number_check.isChecked(),
            restrict_filenames=self.restrict_check.isChecked(),
            overwrite=self.overwrite_check.isChecked(),
            embed_metadata=self.metadata_check.isChecked(),
            embed_chapters=self.chapters_check.isChecked(),
            embed_thumbnail=self.embed_thumb_check.isChecked(),
            write_thumbnail=self.write_thumb_check.isChecked(),
            parse_artist_title=self.artist_check.isChecked(),
            write_info_json=self.infojson_check.isChecked(),
            write_description=self.description_check.isChecked(),
            sponsorblock_remove=sponsors,
            write_subtitles=self.subs_check.isChecked(),
            auto_subtitles=self.auto_subs_check.isChecked(),
            embed_subtitles=self.embed_subs_check.isChecked(),
            subtitle_languages=self.sub_langs_edit.text().strip() or 'en',
            rate_limit=self.rate_edit.text().strip(),
            concurrent_fragments=self.fragments_spin.value(),
            retries=self.retries_spin.value(),
            job_retries=self.job_retries_spin.value(),
            job_retry_delay=self.job_delay_spin.value(),
            proxy=self.proxy_edit.text().strip(),
            cookies_from_browser=self.cookies_combo.currentData(),
            cookies_file=self.cookies_file_edit.text().strip(),
            ffmpeg_location=self.ffmpeg_edit.text().strip(),
        )

    def _clear_history(self) -> None:
        """The main window shows the confirmation; it owns the queue and history."""
        if self._on_clear_history is None:
            return
        self._on_clear_history()
        self._history_count = 0
        self.history_count_label.setText(labels.items_count(0))

    # ---------------------------------------------- theme and language

    def _preview_theme(self) -> None:
        """Live preview, not persisted, so that Cancel can undo it."""
        key = self.theme_combo.currentData()
        if key:
            self._themes.set_theme(key, persist=False)

    def _preview_language(self) -> None:
        code = self.language_combo.currentData()
        if code:
            self._translations.set_language(code, persist=False)
            self._apply_saved_selection()

    def accept(self) -> None:
        theme_key = self.theme_combo.currentData()
        if theme_key and not self._themes.set_theme(theme_key, persist=True):
            # set_theme returns False when the theme is already active (set by the preview)
            self._themes.persist()
        language_code = self.language_combo.currentData()
        if language_code and not self._translations.set_language(language_code, persist=True):
            self._translations.persist()
        super().accept()

    def reject(self) -> None:
        self._themes.set_theme(self._initial_theme, persist=False)
        self._translations.set_language(self._initial_language, persist=False)
        super().reject()

    # -------------------------------------------------------------- helpers

    def _apply_outtmpl_preset(self, index: int) -> None:
        value = self.outtmpl_preset.itemData(index)
        if value:
            self.outtmpl_edit.setText(value)

    def _pick_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr('Cookie file'), self.cookies_file_edit.text(),
            self.tr('Text files (*.txt);;All files (*)'))
        if path:
            self.cookies_file_edit.setText(path)


def _first_focusable(item) -> QWidget | None:
    """The control a form row is really about.

    A row holds either the widget itself or a layout, as with a line edit
    followed by a browse button; the first focusable widget is the field.
    """
    widget = item.widget()
    if widget is not None:
        return widget if widget.focusPolicy() != Qt.FocusPolicy.NoFocus else None

    layout = item.layout()
    if layout is None:
        return None
    for index in range(layout.count()):
        found = _first_focusable(layout.itemAt(index))
        if found is not None:
            return found
    return None


def _form_page() -> tuple[QWidget, QFormLayout]:
    page = QWidget()
    form = QFormLayout(page)
    form.setContentsMargins(18, 18, 18, 18)
    form.setSpacing(10)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return page, form


def _hint() -> QLabel:
    label = QLabel()
    label.setObjectName('Hint')
    label.setWordWrap(True)
    return label


def _section() -> QLabel:
    label = QLabel()
    label.setObjectName('SectionLabel')
    label.setContentsMargins(0, 10, 0, 0)
    return label


def _refill(combo: QComboBox, entries) -> None:
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for value, text in entries:
        combo.addItem(text, value)
    index = combo.findData(current)
    combo.setCurrentIndex(max(0, index))
    combo.blockSignals(False)


def _select(_entries, combo: QComboBox, value) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)


def _pick_dir(parent, edit: QLineEdit) -> None:
    title = QCoreApplication.translate('SettingsDialog', 'Choose folder')
    directory = QFileDialog.getExistingDirectory(parent, title, edit.text())
    if directory:
        edit.setText(directory)
