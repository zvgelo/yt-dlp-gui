"""Turning domain enums and codes into text in the current language.

This is the only place where application state becomes words. It keeps
`app/core` language agnostic, and language switching takes effect at once:
the functions run on every view refresh, so nothing needs caching.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from ..core import format_service as fs
from ..core.errors import AppErrorCode, FriendlyError, shorten
from ..core.models import (
    QUALITY_BEST,
    QUALITY_WORST,
    DownloadProgress,
    DownloadResult,
    DownloadResultStatus,
    MediaInfo,
    MediaKind,
    QualityGrade,
)
from ..core.ytdlp_service import PostProcessStage
from ..state import TaskState
from ..utils import formatting as fmt


def translate(context: str, text: str, disambiguation: str | None = None, n: int = -1) -> str:
    return QCoreApplication.translate(context, text, disambiguation, n)


# ------------------------------------------------------------------- counters


def items_count(count: int) -> str:
    """Item count with the correct plural form.

    Plurals are requested directly through `QCoreApplication.translate`; only
    then does `lupdate` mark the message as `numerus` and generate the three
    forms Polish requires.
    """
    return QCoreApplication.translate('Labels', '%n item(s)', 'queue size', count)


def downloaded_count(count: int) -> str:
    return QCoreApplication.translate('Labels', '%n downloaded', None, count)


def failed_count(count: int) -> str:
    return QCoreApplication.translate('Labels', '%n failed', None, count)


def attempts_count(count: int) -> str:
    # A separate function, because lupdate does not recognise a call nested in
    # another call argument; the plural would simply be lost there
    return QCoreApplication.translate('Labels', 'Attempts: %n', None, count)


# ------------------------------------------------------------- media kinds


def media_kind_label(kind: MediaKind) -> str:
    return translate('Labels', 'Video') if kind is MediaKind.VIDEO else translate('Labels', 'Audio only')


# ----------------------------------------------------------------- quality


def quality_grade_label(grade: QualityGrade) -> str:
    return {
        QualityGrade.AUTOMATIC: translate('Labels', 'Automatic'),
        QualityGrade.ULTRA: translate('Labels', 'Ultra quality'),
        QualityGrade.HIGH: translate('Labels', 'High quality'),
        QualityGrade.GOOD: translate('Labels', 'Good quality'),
        QualityGrade.NORMAL: translate('Labels', 'Normal quality'),
        QualityGrade.LOW: translate('Labels', 'Low quality'),
    }[grade]


def quality_label(value: int, *, kind: MediaKind = MediaKind.VIDEO, short: bool = False) -> str:
    """Label of an entry in the quality selector."""
    if value == QUALITY_BEST:
        return translate('Labels', 'Best') if short else translate('Labels', 'Best available')
    if value == QUALITY_WORST:
        return translate('Labels', 'Lowest')
    if kind is MediaKind.AUDIO:
        return fmt.bitrate(value)
    return f'{value}p' if short else fs.height_label(value)


def quality_details(option) -> str:
    """Technical description of an entry (codecs, container), or the auto wording."""
    if option.grade is QualityGrade.AUTOMATIC:
        return translate('Labels', 'best available video and audio')
    return option.details


def audio_quality_details(option) -> str:
    if option.grade is QualityGrade.AUTOMATIC:
        return translate('Labels', 'original audio stream')
    return option.details


# ---------------------------------------------------------------- containers


def container_label(value: str) -> str:
    return translate('Labels', 'Auto') if not value else value.upper() if value != 'webm' else 'WebM'


def audio_format_label(value: str) -> str:
    return translate('Labels', 'Original') if not value else value.upper()


# ------------------------------------------------------------------- states


def task_state_label(state: TaskState) -> str:
    return {
        TaskState.QUEUED: translate('Labels', 'Queued'),
        TaskState.DOWNLOADING: translate('Labels', 'Downloading'),
        TaskState.POSTPROCESSING: translate('Labels', 'Processing'),
        TaskState.FINISHED: translate('Labels', 'Done'),
        TaskState.COMPLETED_WITH_ERRORS: translate('Labels', 'With errors'),
        TaskState.ERROR: translate('Labels', 'Error'),
        TaskState.CANCELLED: translate('Labels', 'Cancelled'),
        TaskState.INTERRUPTED: translate('Labels', 'Interrupted'),
        TaskState.NEEDS_REVIEW: translate('Labels', 'Decision required'),
        TaskState.RETRYING: translate('Labels', 'Retrying'),
        TaskState.SKIPPED_DUPLICATE: translate('Labels', 'Skipped'),
        TaskState.SKIPPED_BY_USER: translate('Labels', 'Skipped'),
    }.get(state, translate('Labels', 'Unknown'))


def task_state_badge(state: TaskState, percent: float = 0.0) -> str:
    """Short caption in the status column of a card."""
    if state is TaskState.DOWNLOADING:
        return f'{percent:.0f}%'
    if state is TaskState.FINISHED:
        return '✓ ' + translate('Labels', 'Done')
    if state is TaskState.COMPLETED_WITH_ERRORS:
        return '⚠ ' + translate('Labels', 'With errors')
    if state is TaskState.ERROR:
        return '✕ ' + translate('Labels', 'Error')
    if state is TaskState.INTERRUPTED:
        return '⏸ ' + translate('Labels', 'Interrupted')
    if state is TaskState.NEEDS_REVIEW:
        return '⚠ ' + translate('Labels', 'Decision required')
    if state.is_skipped:
        return '⊘ ' + translate('Labels', 'Skipped')
    return task_state_label(state)


def postprocess_stage_label(stage: PostProcessStage) -> str:
    return {
        PostProcessStage.MERGING: translate('Labels', 'Merging video and audio'),
        PostProcessStage.REMUXING: translate('Labels', 'Changing container'),
        PostProcessStage.CONVERTING_VIDEO: translate('Labels', 'Converting video'),
        PostProcessStage.EXTRACTING_AUDIO: translate('Labels', 'Extracting audio'),
        PostProcessStage.WRITING_METADATA: translate('Labels', 'Writing metadata'),
        PostProcessStage.PARSING_METADATA: translate('Labels', 'Parsing metadata'),
        PostProcessStage.EMBEDDING_THUMBNAIL: translate('Labels', 'Embedding cover art'),
        PostProcessStage.EMBEDDING_SUBTITLES: translate('Labels', 'Embedding subtitles'),
        PostProcessStage.CONVERTING_SUBTITLES: translate('Labels', 'Converting subtitles'),
        PostProcessStage.CONVERTING_THUMBNAIL: translate('Labels', 'Converting cover art'),
        PostProcessStage.SPONSORBLOCK: translate('Labels', 'Fetching SponsorBlock data'),
        PostProcessStage.REMOVING_SEGMENTS: translate('Labels', 'Removing segments'),
        PostProcessStage.SPLITTING_CHAPTERS: translate('Labels', 'Splitting chapters'),
        PostProcessStage.MOVING_FILE: translate('Labels', 'Moving file'),
        PostProcessStage.CONCATENATING: translate('Labels', 'Concatenating files'),
        PostProcessStage.FIXING_FILE: translate('Labels', 'Fixing file'),
        PostProcessStage.OTHER: translate('Labels', 'Processing'),
    }.get(stage, translate('Labels', 'Processing'))


# ------------------------------------------------------------------ errors


def error_message(code: AppErrorCode) -> str:
    return {
        AppErrorCode.PRIVATE_VIDEO: translate('Labels', 'This video is private.'),
        AppErrorCode.AGE_RESTRICTED: translate('Labels', 'This video is age-restricted.'),
        AppErrorCode.LOGIN_REQUIRED: translate('Labels', 'This video requires signing in.'),
        AppErrorCode.GEO_RESTRICTED: translate('Labels', 'This video is blocked in your region.'),
        AppErrorCode.UNAVAILABLE: translate('Labels', 'This video was removed or is unavailable.'),
        AppErrorCode.UNSUPPORTED_URL: translate('Labels', 'This address is not supported.'),
        AppErrorCode.INVALID_URL: translate('Labels', 'Invalid address.'),
        AppErrorCode.FORMAT_UNAVAILABLE: translate('Labels', 'The selected format is not available.'),
        AppErrorCode.NO_FORMATS: translate('Labels', 'No downloadable formats were found.'),
        AppErrorCode.FFMPEG_MISSING: translate('Labels', 'FFmpeg was not found.'),
        AppErrorCode.NETWORK_ERROR: translate('Labels', 'Network problem.'),
        AppErrorCode.SSL_ERROR: translate('Labels', 'SSL certificate error.'),
        AppErrorCode.PROXY_ERROR: translate('Labels', 'Proxy connection error.'),
        AppErrorCode.PERMISSION_DENIED: translate('Labels', 'No permission to write to the selected folder.'),
        AppErrorCode.NO_DISK_SPACE: translate('Labels', 'No space left on the disk.'),
        AppErrorCode.POSTPROCESSING_FAILED: translate('Labels', 'Post-processing failed.'),
        AppErrorCode.MERGE_FAILED: translate('Labels', 'Could not merge video and audio.'),
        AppErrorCode.NOT_LIVE_YET: translate('Labels', 'The live stream has not started yet.'),
        AppErrorCode.NOTHING_FOUND: translate('Labels', 'Nothing was found at this address.'),
        AppErrorCode.PLAYLIST_INCOMPLETE: translate('Labels', 'The playlist could not be fully retrieved.'),
    }.get(code, '')


def error_hint(code: AppErrorCode) -> str:
    return {
        AppErrorCode.PRIVATE_VIDEO: translate('Labels', 'It needs an account with access — try browser cookies.'),
        AppErrorCode.AGE_RESTRICTED: translate('Labels', 'Enable browser cookies in Preferences → Network.'),
        AppErrorCode.LOGIN_REQUIRED: translate('Labels', 'Enable browser cookies in Preferences → Network.'),
        AppErrorCode.GEO_RESTRICTED: translate('Labels', 'A proxy set in Preferences → Network may help.'),
        AppErrorCode.UNSUPPORTED_URL: translate('Labels', 'yt-dlp has no extractor for this site.'),
        AppErrorCode.FORMAT_UNAVAILABLE: translate('Labels', 'Pick another quality or “Best available”.'),
        AppErrorCode.NO_FORMATS: translate('Labels', 'The video may be DRM protected.'),
        AppErrorCode.FFMPEG_MISSING: translate('Labels', 'Install FFmpeg or set its folder in Preferences → Network.'),
        AppErrorCode.NETWORK_ERROR: translate('Labels', 'Check your connection and try again.'),
        AppErrorCode.PROXY_ERROR: translate('Labels', 'Check the proxy address in Preferences → Network.'),
        AppErrorCode.PERMISSION_DENIED: translate('Labels', 'Choose a different destination folder.'),
        AppErrorCode.POSTPROCESSING_FAILED: translate('Labels', 'Check whether FFmpeg is installed.'),
        AppErrorCode.MERGE_FAILED: translate('Labels', 'This usually means FFmpeg is missing or too old.'),
    }.get(code, '')


def error_text(error: FriendlyError, *, with_hint: bool = True) -> str:
    """A sentence for the user; for an unknown error, the original yt-dlp text."""
    message = error_message(error.code)
    if not message:
        return shorten(error.details)
    hint = error_hint(error.code) if with_hint else ''
    return f'{message} {hint}'.strip()


# ---------------------------------------------------------------- progress


def describe_progress(progress: DownloadProgress) -> str:
    """`24.8 MB / 36.2 MB · 8.4 MB/s · ETA 00:02`."""
    parts = [f'{fmt.size(progress.downloaded_bytes)} / {fmt.size(progress.total_bytes)}',
             fmt.speed(progress.speed)]
    if progress.eta:
        parts.append(translate('Labels', 'ETA {0}').format(fmt.eta(progress.eta)))
    if progress.fragment_count and progress.fragment_index:
        parts.append(translate('Labels', 'fragment {0}/{1}').format(progress.fragment_index,
                                                   progress.fragment_count))
    return fmt.join(*parts)


# ------------------------------------------------------------------ results


def result_count_label(result: DownloadResult) -> str:
    """`3 / 10` only when the total is genuinely known, otherwise just the count."""
    if result.total_is_known:
        return f'{result.completed_items} / {result.total_items}'
    return downloaded_count(result.completed_items)


def describe_result(result: DownloadResult) -> str:
    """A short sentence for the card; full messages stay in the log."""
    if not result.playlist_enumeration_complete:
        if result.completed_items:
            return translate('Labels', 'The playlist could not be fully retrieved — some items may be missing.')
        return translate('Labels', 'The playlist could not be retrieved.')
    if result.errors:
        return shorten(result.errors[0])
    if result.failed_items:
        attempted = result.completed_items + result.failed_items
        return translate('Labels', 'Could not download {0} of {1} items.').format(result.failed_items, attempted)
    return ''


def entry_count_label(info: MediaInfo) -> str:
    """Playlist item count, with a caveat when the list was not read in full."""
    count = info.entry_count
    if info.entries_complete:
        return items_count(count)
    return translate('Labels', 'at least {0}').format(items_count(count))


# -------------------------------------------------------------- appearance


def theme_name(key: str) -> str:
    """Theme name; the identifier (`light`/`dark`/`steel`) stays stable."""
    return {
        'light': translate('Labels', 'Light'),
        'dark': translate('Labels', 'Dark'),
        'steel': translate('Labels', 'Steel'),
    }.get(key, key)


def queue_filter_label(value: str) -> str:
    return {
        'all': translate('Labels', 'All'),
        'in_progress': translate('Labels', 'In progress'),
        'needs_review': translate('Labels', 'Needs review'),
        'failed': translate('Labels', 'Failed'),
        'video': translate('Labels', 'Video'),
        'audio': translate('Labels', 'Audio'),
        'playlists': translate('Labels', 'Playlists'),
        'completed': translate('Labels', 'Completed'),
    }.get(value, value)


# ---------------------------------------------------------------- playlists


def playlist_summary(job) -> str:
    """The counters row under a playlist title."""
    parts = [downloaded_count(job.completed_items)]
    if job.failed_items:
        parts.append(failed_count(job.failed_items))
    if job.is_active:
        active = job.active_task
        if active is not None:
            parts.append(translate('Labels', 'now: {0}').format(active.display_title))
    elif not job.enumeration_complete:
        parts.append(translate('Labels', 'the full playlist could not be retrieved'))
    elif job.total_items is not None:
        parts.insert(0, items_count(job.total_items))
    return fmt.join(*parts)


def playlist_status_badge(job) -> str:
    if job.is_active:
        return f'{job.percent:.0f}%'
    return result_status_short(job.status)


def result_status_short(status: DownloadResultStatus) -> str:
    return {
        DownloadResultStatus.SUCCESS: '✓ ' + translate('Labels', 'Done'),
        DownloadResultStatus.PARTIAL_SUCCESS: '⚠ ' + translate('Labels', 'With errors'),
        DownloadResultStatus.ERROR: '✕ ' + translate('Labels', 'Error'),
        DownloadResultStatus.CANCELLED: translate('Labels', 'Cancelled'),
    }[status]


def processing_fallback() -> str:
    return translate('Labels', 'Processing…')


def connecting_label() -> str:
    return translate('Labels', 'Connecting…')


# ------------------------------------------------------------- duplicates


def duplicate_summary(task) -> str:
    """Row on a "Needs review" card: where the conflict is and where we would save."""
    from ..core.duplicates import DuplicateKind, target_directory

    if task.duplicate_kind == DuplicateKind.ALREADY_QUEUED.value:
        return translate('Labels', 'The same item is already in the queue.')

    parts = [translate('Labels', 'This item has already been downloaded.')]
    if task.duplicate_of_path:
        parts.append(translate('Labels', 'Existing file: {0}').format(task.duplicate_of_path))
    parts.append(translate('Labels', 'New destination: {0}').format(
        target_directory(task.request)))
    return ' · '.join(parts)


def skipped_summary(task) -> str:
    from ..state import TaskState

    if task.state is TaskState.SKIPPED_DUPLICATE:
        return translate('Labels', 'Skipped — the file already exists in the destination folder.')
    return translate('Labels', 'Skipped by you.')


# ------------------------------------------------------------- job failures


def failure_summary(task) -> str:
    """Row on a card in the "Failed" tab: reason, attempt count and time."""
    from ..core.errors import AppErrorCode, FriendlyError

    parts = [error_text(FriendlyError(task.error_code or AppErrorCode.UNKNOWN, task.error),
                        with_hint=False)]
    if task.attempt_count:
        parts.append(attempts_count(task.attempt_count))
    last = task.last_attempt
    if last is not None and last.finished_at:
        parts.append(translate('Labels', 'Last attempt: {0}').format(_short_time(last.finished_at)))
    return fmt.join(*parts)


def retry_summary(task) -> str:
    """Opis podczas oczekiwania na automatyczne ponowienie."""
    from ..core.errors import AppErrorCode, FriendlyError

    reason = error_text(FriendlyError(task.error_code or AppErrorCode.UNKNOWN, task.error),
                        with_hint=False)
    return fmt.join(translate('Labels', 'Retrying…'), reason)


def attempt_line(attempt) -> str:
    """A single row in the error details."""
    kind = translate('Labels', 'manual') if attempt.manual else translate('Labels', 'automatic')
    when = _short_time(attempt.finished_at or attempt.started_at)
    outcome = attempt.error_message or translate('Labels', 'succeeded')
    return f'#{attempt.number} ({kind}) · {when} · {outcome}'


def _short_time(value: str) -> str:
    """`2026-08-17T14:23:11+00:00` -> `14:23`; returns the input on an odd format."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(value).astimezone().strftime('%H:%M')
    except (TypeError, ValueError):
        return value
