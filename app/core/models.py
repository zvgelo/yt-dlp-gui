"""Application models: plain Python, no Qt dependency, no raw info_dict.

The raw yt-dlp `info_dict` never reaches the widgets; it is translated here.
"""

from __future__ import annotations

import dataclasses
import enum
import uuid

from ..state import TaskState
from ..utils import formatting as fmt
from .errors import AppErrorCode


def _new_id(prefix: str) -> str:
    """An identifier stable across runs; it is stored in the history database."""
    return f'{prefix}-{uuid.uuid4().hex[:12]}'


class MediaKind(enum.Enum):
    """Whether we fetch picture with sound, or sound alone."""

    VIDEO = 'video'
    AUDIO = 'audio'


class QualityGrade(enum.Enum):
    """Colloquial quality grade shown next to the resolution or bitrate."""

    AUTOMATIC = 'automatic'
    ULTRA = 'ultra'
    HIGH = 'high'
    GOOD = 'good'
    NORMAL = 'normal'
    LOW = 'low'


#: Special quality selector values
QUALITY_BEST = 0
QUALITY_WORST = -1


# --------------------------------------------------------------------------- format


@dataclasses.dataclass(frozen=True)
class FormatInfo:
    """One `info_dict['formats']` entry, mapped onto the application model."""

    format_id: str
    ext: str | None = None
    width: int | None = None
    height: int | None = None
    resolution: str | None = None
    fps: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    tbr: float | None = None
    vbr: float | None = None
    abr: float | None = None
    filesize: int | None = None
    filesize_approx: int | None = None
    protocol: str | None = None
    format_note: str | None = None
    language: str | None = None
    dynamic_range: str | None = None

    @property
    def has_video(self) -> bool:
        return bool(self.vcodec) and self.vcodec != 'none'

    @property
    def has_audio(self) -> bool:
        return bool(self.acodec) and self.acodec != 'none'

    @property
    def is_muxed(self) -> bool:
        return self.has_video and self.has_audio

    @property
    def is_video_only(self) -> bool:
        return self.has_video and not self.has_audio

    @property
    def is_audio_only(self) -> bool:
        return self.has_audio and not self.has_video

    @property
    def size(self) -> int | None:
        """The exact size, or the approximate one when it is unknown."""
        return self.filesize or self.filesize_approx

    @property
    def is_storyboard(self) -> bool:
        return (self.ext or '') == 'mhtml' or (self.format_note or '').lower() == 'storyboard'

    @property
    def height_label(self) -> str:
        if self.height:
            return f'{self.height}p'
        return self.resolution or (self.format_note or '')

    @property
    def bitrate(self) -> float | None:
        return self.abr or self.tbr


@dataclasses.dataclass(frozen=True)
class QualityOption:
    """An entry in the simple quality selector; only heights that truly exist."""

    value: int  # height in pixels; QUALITY_BEST / QUALITY_WORST at the extremes
    label: str  # '1080p (Full HD)'; empty for the "best available" entry
    grade: QualityGrade
    details: str = ''  # 'MP4 - H.264 - AAC'; technical notation, never translated
    filesize: int | None = None


@dataclasses.dataclass(frozen=True)
class FormatVariant:
    """An entry in the advanced selector: one stream or a pair of streams."""

    selector: str  # a ready value for the `format` option, e.g. '299+140'
    label: str  # '1080p - 60 FPS - H.264 - MP4'; technical notation
    grade: QualityGrade
    filesize: int | None
    height: int | None
    abr: float | None = None


# ---------------------------------------------------------------------------- media


@dataclasses.dataclass(frozen=True)
class SubtitleTrack:
    language: str
    name: str
    automatic: bool

    @property
    def display_name(self) -> str:
        """The language name reported by the service; kept as-is."""
        return self.name or self.language


@dataclasses.dataclass(frozen=True)
class PlaylistEntry:
    #: URL as reported while enumerating the playlist; may carry playlist context
    url: str
    title: str
    index: int
    duration: float | None = None
    thumbnail_url: str = ''
    uploader: str = ''
    #: Provider-side identity, the basis for duplicate detection
    media_id: str = ''
    extractor: str = ''
    #: URL that resolves to this single item; never used to enumerate a playlist
    canonical_url: str = ''
    #: URL of the playlist this entry was discovered in
    playlist_url: str = ''

    @property
    def download_url(self) -> str:
        """URL a download job must use. Falls back to the discovered URL."""
        return self.canonical_url or self.url


@dataclasses.dataclass(frozen=True)
class MediaInfo:
    """The result of a URL analysis, handed to the GUI."""

    url: str
    title: str
    webpage_url: str = ''
    #: Media identifier at the provider (e.g. a YouTube video id)
    media_id: str = ''
    uploader: str = ''
    channel: str = ''
    duration: float | None = None
    thumbnail_url: str = ''
    extractor: str = ''
    live: bool = False
    formats: tuple[FormatInfo, ...] = ()
    subtitles: tuple[SubtitleTrack, ...] = ()
    is_playlist: bool = False
    playlist_title: str = ''
    entries: tuple[PlaylistEntry, ...] = ()
    #: False when the extractor aborted pagination (e.g. HTTP 403 on a further
    #: page): only some entries are known and the full count is not
    entries_complete: bool = True
    #: The message that stopped enumeration (empty when it completed)
    entries_error: str = ''

    @property
    def author(self) -> str:
        return self.uploader or self.channel

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def has_formats(self) -> bool:
        return bool(self.formats)


# -------------------------------------------------------------------------- request


@dataclasses.dataclass
class DownloadRequest:
    """Everything needed to build the `YoutubeDL` options for one item."""

    #: URL used for downloading; for playlist items this is the canonical
    #: single-media URL, so yt-dlp never re-enumerates the parent playlist
    url: str
    output_dir: str
    #: URL the item was discovered through, kept for history and display
    source_url: str = ''

    kind: MediaKind = MediaKind.VIDEO
    quality: int = QUALITY_BEST
    container: str = 'mp4'  # video container: mp4/mkv/webm/'' (auto)
    audio_format: str = 'mp3'  # audio codec: mp3/m4a/aac/opus/flac/wav/'' (auto)
    format_selector: str = ''  # set only by the advanced selection

    # subtitles
    write_subtitles: bool = False
    auto_subtitles: bool = False
    embed_subtitles: bool = True
    subtitle_languages: tuple[str, ...] = ('pl', 'en')

    # metadata and cover art
    embed_metadata: bool = True
    embed_chapters: bool = True
    embed_thumbnail: bool = True
    write_thumbnail: bool = False
    write_info_json: bool = False
    write_description: bool = False
    parse_artist_title: bool = True

    # Playlist context, captured when the task is created so that a retry uses
    # the same configuration rather than the current global settings
    playlist_title: str = ''
    playlist_index: int | None = None
    create_playlist_folder: bool = True
    number_playlist_files: bool = True

    def __post_init__(self) -> None:
        """Canonicalise the download URL, whoever built the request.

        Every path ends here - the GUI, a playlist child, a retry and a record
        restored from history - so a download job can never carry playlist
        context such as `?list=...` into yt-dlp. The address the user actually
        pasted is kept in `source_url` for history and diagnostics.
        """
        from .urls import normalize_url

        original = (self.url or '').strip()
        self.source_url = (self.source_url or original).strip()
        self.url = normalize_url(original)

    @property
    def is_playlist_item(self) -> bool:
        return bool(self.playlist_title)

    @property
    def is_audio(self) -> bool:
        return self.kind is MediaKind.AUDIO

    @property
    def target_ext(self) -> str:
        return self.audio_format if self.is_audio else self.container


# ------------------------------------------------------------------------- progress


@dataclasses.dataclass(frozen=True)
class DownloadProgress:
    """A normalised payload from `progress_hooks`."""

    status: str = ''
    filename: str = ''
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed: float | None = None
    eta: float | None = None
    elapsed: float | None = None
    fragment_index: int | None = None
    fragment_count: int | None = None

    @property
    def percent(self) -> float | None:
        if self.total_bytes and self.downloaded_bytes is not None:
            return min(100.0, self.downloaded_bytes * 100.0 / self.total_bytes)
        if self.fragment_count and self.fragment_index is not None:
            return min(100.0, self.fragment_index * 100.0 / self.fragment_count)
        return None

    @classmethod
    def from_hook(cls, payload: dict) -> DownloadProgress:
        return cls(
            status=payload.get('status') or '',
            filename=payload.get('filename') or '',
            downloaded_bytes=payload.get('downloaded_bytes'),
            total_bytes=payload.get('total_bytes') or payload.get('total_bytes_estimate'),
            speed=payload.get('speed'),
            eta=payload.get('eta'),
            elapsed=payload.get('elapsed'),
            fragment_index=payload.get('fragment_index'),
            fragment_count=payload.get('fragment_count'),
        )


# -------------------------------------------------------------------- result


class DownloadResultStatus(enum.Enum):
    """The real outcome of a job, independent of the worker having finished."""

    SUCCESS = 'success'
    PARTIAL_SUCCESS = 'partial_success'
    ERROR = 'error'
    CANCELLED = 'cancelled'


@dataclasses.dataclass
class DownloadResult:
    """The result of a single download job.

    `total_items is None` means the full item count is unknown, which is the
    case with `lazy_playlist` and whenever enumeration was interrupted. The
    total is never guessed from the number of downloaded items.
    """

    status: DownloadResultStatus

    total_items: int | None = None
    completed_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0

    #: False when not all playlist pages could be read
    playlist_enumeration_complete: bool = True

    errors: tuple[str, ...] = ()
    enumeration_errors: tuple[str, ...] = ()
    output_files: tuple[str, ...] = ()

    @property
    def primary_file(self) -> str:
        return self.output_files[0] if self.output_files else ''

    @property
    def is_success(self) -> bool:
        return self.status is DownloadResultStatus.SUCCESS

    @property
    def has_problems(self) -> bool:
        return self.status in (DownloadResultStatus.PARTIAL_SUCCESS, DownloadResultStatus.ERROR)

    @property
    def total_is_known(self) -> bool:
        """Whether `x of y` may be shown; otherwise the GUI reports the count only."""
        return self.total_items is not None and self.playlist_enumeration_complete

    @classmethod
    def classify(cls, *, cancelled: bool = False, completed: int = 0, failed: int = 0,
                 skipped: int = 0, total: int | None = None,
                 enumeration_complete: bool = True, fatal: bool = False,
                 errors: tuple[str, ...] = (), enumeration_errors: tuple[str, ...] = (),
                 output_files: tuple[str, ...] = ()) -> DownloadResult:
        """The only place deciding the status; do not duplicate this logic."""
        if cancelled:
            status = DownloadResultStatus.CANCELLED
        elif completed == 0:
            # Nothing came out: a fatal error, aborted enumeration or an empty result
            status = DownloadResultStatus.ERROR
        elif fatal or failed or not enumeration_complete or errors or enumeration_errors:
            # Something succeeded, but completeness cannot be guaranteed
            status = DownloadResultStatus.PARTIAL_SUCCESS
        else:
            status = DownloadResultStatus.SUCCESS

        return cls(
            status=status,
            total_items=total if enumeration_complete else None,
            completed_items=completed,
            failed_items=failed,
            skipped_items=skipped,
            playlist_enumeration_complete=enumeration_complete,
            errors=tuple(errors),
            enumeration_errors=tuple(enumeration_errors),
            output_files=tuple(output_files),
        )


# ------------------------------------------------------------------ attempts


@dataclasses.dataclass
class DownloadAttempt:
    """A single download attempt, inspectable in the error details."""

    number: int
    started_at: str
    finished_at: str = ''
    status: str = ''
    error_code: str = ''
    error_message: str = ''
    #: True when the user started the attempt rather than the automation
    manual: bool = False

    @property
    def succeeded(self) -> bool:
        return not self.error_code and not self.error_message


# ----------------------------------------------------------------------------- task


@dataclasses.dataclass
class DownloadTask:
    """A queue item: the request, the metadata to display and the current state."""

    request: DownloadRequest

    id: str = dataclasses.field(default_factory=lambda: _new_id('task'))
    title: str = ''
    uploader: str = ''
    duration: float | None = None
    thumbnail_url: str = ''
    quality_label: str = ''
    expected_size: int | None = None
    #: Media identity at the provider; used when writing history
    media_id: str = ''
    extractor: str = ''

    state: TaskState = TaskState.QUEUED
    #: Post-processing stage (an enum, not text; the GUI translates it)
    stage: object | None = None
    progress: DownloadProgress = dataclasses.field(default_factory=DownloadProgress)
    percent: float = 0.0
    #: Identifier of the playlist this item came from (None = a single media).
    #: The playlist itself lives as a separate `PlaylistJob` record, so the
    #: "Playlists" tab shows playlists rather than their files.
    playlist_id: str | None = None

    filepath: str = ''
    #: The recognised problem kind (the GUI turns it into localised text)
    error_code: AppErrorCode | None = None
    #: The original yt-dlp message, for the log and hints; never translated
    error: str = ''
    #: Filled in on completion; the source of truth about the job outcome
    result: DownloadResult | None = None

    #: The batch this item was added in; drives the duplicate policy
    batch_id: str = ''
    #: Context of the detected duplicate (empty when there was no conflict)
    duplicate_kind: str = ''
    duplicate_of_record_id: str = ''
    #: Path of the existing file, shown on the "Needs review" card
    duplicate_of_path: str = ''

    #: Timestamps and the attempt counter; both go into the persistent history
    created_at: str = ''
    started_at: str = ''
    completed_at: str = ''
    attempt_count: int = 0
    #: How many automatic retries were used since the last user decision
    auto_retries: int = 0
    #: The full attempt history; a manual retry never clears it
    attempts: list[DownloadAttempt] = dataclasses.field(default_factory=list)
    #: True when the user triggered the next attempt
    manual_retry_pending: bool = False

    @property
    def url(self) -> str:
        return self.request.url

    @property
    def display_title(self) -> str:
        return self.title or self.request.url

    @property
    def kind(self) -> MediaKind:
        return self.request.kind

    @property
    def summary(self) -> str:
        """The metadata row under the card title."""
        return fmt.join(
            fmt.duration(self.duration) if self.duration else '',
            fmt.size(self.progress.total_bytes or self.expected_size),
            (self.request.target_ext or '').upper(),
            self.quality_label,
            self.uploader,
        )

    @property
    def last_attempt(self) -> DownloadAttempt | None:
        return self.attempts[-1] if self.attempts else None

    def begin_attempt(self, timestamp: str) -> DownloadAttempt:
        attempt = DownloadAttempt(number=len(self.attempts) + 1, started_at=timestamp,
                                  manual=self.manual_retry_pending)
        self.attempts.append(attempt)
        self.attempt_count = len(self.attempts)
        self.manual_retry_pending = False
        return attempt

    def finish_attempt(self, timestamp: str, status: str, *, error_code: str = '',
                       error_message: str = '') -> None:
        attempt = self.last_attempt
        if attempt is None:
            return
        attempt.finished_at = timestamp
        attempt.status = status
        attempt.error_code = error_code
        attempt.error_message = error_message

    def reset(self) -> None:
        """Prepare the task for another attempt. The attempt history stays."""
        self.state = TaskState.QUEUED
        self.stage = None
        self.progress = DownloadProgress()
        self.percent = 0.0
        self.error = ''
        self.error_code = None
        self.result = None


# --------------------------------------------------------------------- playlist

@dataclasses.dataclass
class PlaylistJob:
    """A playlist as a parent job: one entry regardless of the file count.

    The counters are not stored here but computed from the child items
    (`tasks`), so they cannot drift apart from the queue state.
    """

    title: str
    source_url: str

    id: str = dataclasses.field(default_factory=lambda: _new_id('playlist'))
    thumbnail_url: str = ''
    uploader: str = ''
    #: Number of items known at analysis time (None when enumeration failed)
    discovered_items: int | None = None
    #: False when not all playlist pages could be read
    enumeration_complete: bool = True
    enumeration_error: str = ''
    created_at: str = ''

    #: Items belonging to this playlist; the source of every counter
    tasks: list[DownloadTask] = dataclasses.field(default_factory=list)

    @property
    def total_items(self) -> int | None:
        """The full item count, or None when enumeration did not finish."""
        return len(self.tasks) if self.enumeration_complete else None

    @property
    def completed_items(self) -> int:
        return sum(1 for task in self.tasks if task.state is TaskState.FINISHED)

    @property
    def failed_items(self) -> int:
        return sum(1 for task in self.tasks if task.state is TaskState.ERROR)

    @property
    def cancelled_items(self) -> int:
        return sum(1 for task in self.tasks if task.state is TaskState.CANCELLED)

    @property
    def partial_items(self) -> int:
        return sum(1 for task in self.tasks if task.state is TaskState.COMPLETED_WITH_ERRORS)

    @property
    def active_task(self) -> DownloadTask | None:
        return next((task for task in self.tasks if task.state.is_active), None)

    @property
    def is_active(self) -> bool:
        return any(not task.state.is_final for task in self.tasks)

    @property
    def percent(self) -> float:
        """Progress of the whole playlist, computed from completed items."""
        if not self.tasks:
            return 0.0
        done = self.completed_items + self.failed_items + self.cancelled_items + self.partial_items
        return min(100.0, done * 100.0 / len(self.tasks))

    @property
    def status(self) -> DownloadResultStatus:
        """Overall status; never SUCCESS when something failed or the list is partial."""
        if self.is_active:
            return DownloadResultStatus.PARTIAL_SUCCESS if self.failed_items else \
                DownloadResultStatus.SUCCESS
        if not self.completed_items and not self.partial_items:
            if self.cancelled_items and not self.failed_items:
                return DownloadResultStatus.CANCELLED
            return DownloadResultStatus.ERROR
        if self.failed_items or self.partial_items or not self.enumeration_complete:
            return DownloadResultStatus.PARTIAL_SUCCESS
        return DownloadResultStatus.SUCCESS

    def as_result(self) -> DownloadResult:
        """Rezultat playlisty w tej samej postaci, co pojedynczego zadania."""
        return DownloadResult(
            status=self.status,
            total_items=self.total_items,
            completed_items=self.completed_items,
            failed_items=self.failed_items,
            skipped_items=self.cancelled_items,
            playlist_enumeration_complete=self.enumeration_complete,
            enumeration_errors=(self.enumeration_error,) if self.enumeration_error else (),
            output_files=tuple(task.filepath for task in self.tasks if task.filepath),
        )
