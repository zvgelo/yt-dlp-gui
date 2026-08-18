"""Application settings stored in `QSettings`.

`AppSettings` is a plain dataclass (core uses it without Qt) while
`SettingsStore` only reads and writes it. On Linux QSettings writes INI, so
every value comes back as text; hence the coercion by field type.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

from . import APP_NAME, ORG_NAME
from .core.models import QUALITY_BEST, MediaKind

#: Default filename template. The playlist part (folder, index) is added by
#: `app/core/output_template.py`; the playlist name never enters the filename.
DEFAULT_OUTTMPL = '%(title)s.%(ext)s'


def default_output_dir() -> str:
    # Localised download folder first, then the English default
    for candidate in (Path.home() / 'Pobrane', Path.home() / 'Downloads'):
        if candidate.is_dir():
            return str(candidate)
    return str(Path.home())


@dataclasses.dataclass
class AppSettings:
    # --- default selection ---
    output_dir: str = dataclasses.field(default_factory=default_output_dir)
    kind: str = MediaKind.VIDEO.value
    quality: int = QUALITY_BEST
    video_container: str = 'mp4'
    audio_format: str = 'mp3'

    # --- naming ---
    outtmpl: str = DEFAULT_OUTTMPL
    #: Save a playlist into a separate folder named after it
    create_playlist_folder: bool = True
    #: Prefix the filename with the playlist index (001 - Title.mp4)
    number_playlist_files: bool = True
    restrict_filenames: bool = False
    overwrite: bool = False

    # --- metadata and cover art ---
    embed_metadata: bool = True
    embed_chapters: bool = True
    embed_thumbnail: bool = True
    write_thumbnail: bool = False
    write_info_json: bool = False
    write_description: bool = False
    parse_artist_title: bool = True
    sponsorblock_remove: str = ''

    # --- subtitles ---
    write_subtitles: bool = False
    auto_subtitles: bool = False
    embed_subtitles: bool = True
    subtitle_languages: str = 'pl,en'

    # --- network ---
    rate_limit: str = ''
    concurrent_fragments: int = 4
    #: Retries inside yt-dlp (HTTP and fragments) within a single attempt
    retries: int = 10
    #: Retries of the whole job after a failed attempt. A separate layer from
    #: `retries`: only exhausting it moves the item to the "Failed" tab.
    job_retries: int = 2
    #: Delay between automatic job retries (seconds)
    job_retry_delay: int = 5
    proxy: str = ''
    cookies_from_browser: str = ''
    cookies_file: str = ''
    ffmpeg_location: str = ''

    # --- GUI behaviour ---
    smart_mode: bool = False
    autostart: bool = True
    verbose_log: bool = False

    @property
    def media_kind(self) -> MediaKind:
        try:
            return MediaKind(self.kind)
        except ValueError:
            return MediaKind.VIDEO

    @property
    def subtitle_language_list(self) -> tuple[str, ...]:
        langs = tuple(x.strip() for x in self.subtitle_languages.split(',') if x.strip())
        return langs or ('en',)

    @property
    def sponsorblock_categories(self) -> frozenset[str]:
        return frozenset(x.strip() for x in self.sponsorblock_remove.split(',') if x.strip())

    def replace(self, **changes) -> AppSettings:
        return dataclasses.replace(self, **changes)


class SettingsStore:
    """Thin layer over QSettings, keeping the whole mapping in one place."""

    GROUP = 'app'

    def __init__(self, settings: QSettings | None = None):
        self._settings = settings or QSettings(ORG_NAME, APP_NAME)

    def load(self) -> AppSettings:
        defaults = AppSettings()
        values = {}
        self._settings.beginGroup(self.GROUP)
        try:
            for field in dataclasses.fields(AppSettings):
                if not self._settings.contains(field.name):
                    continue
                raw = self._settings.value(field.name)
                coerced = _coerce(field.type, raw)
                if coerced is not None:
                    values[field.name] = coerced
        finally:
            self._settings.endGroup()
        return dataclasses.replace(defaults, **values)

    def save(self, settings: AppSettings) -> None:
        self._settings.beginGroup(self.GROUP)
        try:
            for key, value in dataclasses.asdict(settings).items():
                self._settings.setValue(key, value)
        finally:
            self._settings.endGroup()
        self._settings.sync()

    # --- window state is kept separately, outside the domain model ---

    def save_geometry(self, geometry: QByteArray, state: QByteArray) -> None:
        self._settings.setValue('window/geometry', geometry)
        self._settings.setValue('window/state', state)
        self._settings.sync()

    def geometry(self) -> QByteArray | None:
        return _as_bytes(self._settings.value('window/geometry'))

    def window_state(self) -> QByteArray | None:
        return _as_bytes(self._settings.value('window/state'))


_TRUE = {'true', '1', 'yes', 'on'}
_FALSE = {'false', '0', 'no', 'off', ''}


def _coerce(field_type: object, value):
    """QSettings returns text; coerce it to the type declared on the field."""
    name = field_type if isinstance(field_type, str) else getattr(field_type, '__name__', '')
    if value is None:
        return None
    try:
        if name == 'bool':
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in _TRUE:
                return True
            if text in _FALSE:
                return False
            return None
        if name == 'int':
            return int(value)
        if name == 'str':
            return str(value)
    except (TypeError, ValueError):
        return None
    return value


def _as_bytes(value) -> QByteArray | None:
    if isinstance(value, QByteArray):
        return value
    if isinstance(value, (bytes, bytearray)):
        return QByteArray(bytes(value))
    return None
