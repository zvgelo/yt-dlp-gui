"""Conversion between queue models and persistent history records.

Kept separate so that neither `DownloadTask` nor `HistoryStore` has to know
about the other.
"""

from __future__ import annotations

from ..state import TaskState
from .history import HistoryRecord, PlaylistRecord, now_iso
from .models import DownloadAttempt, DownloadRequest, DownloadTask, MediaKind, PlaylistJob


def record_from_task(task: DownloadTask) -> HistoryRecord:
    """Take from a task everything that must survive an application restart."""
    request = task.request
    return HistoryRecord(
        id=task.id,
        source_url=request.source_url or request.url,
        status=task.state.value,
        extractor=task.extractor,
        media_id=task.media_id,
        media_kind=request.kind.value,
        output_format=request.target_ext,
        quality=request.quality,
        title=task.title,
        uploader=task.uploader,
        duration=task.duration,
        thumbnail_url=task.thumbnail_url,
        canonical_url=request.url,
        output_directory=request.output_dir,
        # Store the real path rather than one rebuilt from current settings
        final_path=task.filepath,
        playlist_id=task.playlist_id,
        playlist_title=request.playlist_title,
        playlist_index=request.playlist_index,
        created_at=task.created_at or now_iso(),
        started_at=task.started_at,
        completed_at=task.completed_at,
        attempt_count=task.attempt_count,
        error_code=task.error_code.value if task.error_code else '',
        error_message=task.error,
        duplicate_of_record_id=task.duplicate_of_record_id,
        duplicate_kind=task.duplicate_kind,
    )


def task_from_record(record: HistoryRecord, attempts: list[dict] | None = None) -> DownloadTask:
    """Rebuild a history entry as a task in its final state."""
    from .errors import AppErrorCode

    audio = record.media_kind == MediaKind.AUDIO.value
    request = DownloadRequest(
        # Retry must reuse the canonical URL, otherwise a playlist child would
        # send yt-dlp back to the parent playlist
        url=record.canonical_url or record.source_url,
        source_url=record.source_url,
        output_dir=record.output_directory,
        kind=MediaKind.AUDIO if audio else MediaKind.VIDEO,
        quality=record.quality,
        container='' if audio else record.output_format,
        audio_format=record.output_format if audio else '',
        playlist_title=record.playlist_title,
        playlist_index=record.playlist_index,
    )

    error_code = None
    if record.error_code:
        try:
            error_code = AppErrorCode(record.error_code)
        except ValueError:
            error_code = AppErrorCode.UNKNOWN

    task = DownloadTask(
        request=request,
        id=record.id,
        title=record.title,
        uploader=record.uploader,
        duration=record.duration,
        thumbnail_url=record.thumbnail_url,
        media_id=record.media_id,
        extractor=record.extractor,
        state=_state_from_value(record.status),
        playlist_id=record.playlist_id,
        filepath=record.final_path,
        error_code=error_code,
        error=record.error_message,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        attempt_count=record.attempt_count,
        duplicate_of_record_id=record.duplicate_of_record_id,
        duplicate_kind=record.duplicate_kind,
    )
    task.attempts = [DownloadAttempt(**data) for data in attempts or []]
    task.percent = 100.0 if task.state is TaskState.FINISHED else 0.0
    return task


def playlist_record_from_job(job: PlaylistJob) -> PlaylistRecord:
    return PlaylistRecord(
        id=job.id,
        title=job.title,
        source_url=job.source_url,
        status=job.status.value,
        uploader=job.uploader,
        thumbnail_url=job.thumbnail_url,
        total_items=job.total_items,
        enumeration_complete=job.enumeration_complete,
        enumeration_error=job.enumeration_error,
        created_at=job.created_at or now_iso(),
        completed_at='' if job.is_active else now_iso(),
    )


def job_from_playlist_record(record: PlaylistRecord, tasks: list[DownloadTask]) -> PlaylistJob:
    job = PlaylistJob(
        title=record.title,
        source_url=record.source_url,
        id=record.id,
        thumbnail_url=record.thumbnail_url,
        uploader=record.uploader,
        discovered_items=record.total_items,
        enumeration_complete=record.enumeration_complete,
        enumeration_error=record.enumeration_error,
        created_at=record.created_at,
    )
    job.tasks = tasks
    return job


def _state_from_value(value: str) -> TaskState:
    try:
        return TaskState(value)
    except ValueError:
        # A state from a newer program version; treat it as interrupted
        return TaskState.INTERRUPTED
