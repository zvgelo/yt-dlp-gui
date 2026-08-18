"""Detection of duplicate downloads.

Everything rests on telling two identities apart:

* `MediaIdentity` - *what* the media is at the provider (extractor + id),
* `ArtifactIdentity` - *what the user wants out of it* (media kind, output
  format, quality).

That way the same video fetched once as MP4 1080p and once as MP3 is not a
duplicate, even though the `media_id` is identical.

This layer knows nothing about Qt or widgets; the GUI decides what to show.
"""

from __future__ import annotations

import dataclasses
import enum
import os
import threading

from .history import HistoryRecord, HistoryStore, MediaIdentity
from .models import DownloadRequest
from .output_template import PLAYLIST_FOLDER


class DuplicateKind(enum.Enum):
    """The kind of conflict detected."""

    NONE = 'none'
    #: The same artifact already exists in the same target folder
    SAME_TARGET = 'same_target'
    #: The same artifact exists elsewhere; needs a decision
    OTHER_TARGET = 'other_target'
    #: The same artifact is already queued or currently downloading
    ALREADY_QUEUED = 'already_queued'


class DuplicatePolicy(enum.Enum):
    """What to do with a conflict within a single batch."""

    ASK = 'ask'
    DOWNLOAD_ALL_FOR_QUEUE = 'download_all_for_queue'
    SKIP_ALL_FOR_QUEUE = 'skip_all_for_queue'


@dataclasses.dataclass(frozen=True)
class ArtifactIdentity:
    """The concrete file the user wants to obtain from a given media item."""

    media: MediaIdentity
    media_kind: str
    output_format: str
    quality: int = 0

    @property
    def is_valid(self) -> bool:
        return self.media.is_valid

    @property
    def key(self) -> str:
        return f'{self.media.key}|{self.media_kind}|{self.output_format}|{self.quality}'

    @classmethod
    def from_request(cls, request: DownloadRequest, identity: MediaIdentity) -> ArtifactIdentity:
        return cls(
            media=identity,
            media_kind=request.kind.value,
            output_format=request.target_ext,
            quality=request.quality,
        )

    @classmethod
    def from_record(cls, record: HistoryRecord) -> ArtifactIdentity:
        return cls(
            media=record.identity,
            media_kind=record.media_kind,
            output_format=record.output_format,
            quality=record.quality,
        )


@dataclasses.dataclass(frozen=True)
class DuplicateCheckResult:
    kind: DuplicateKind = DuplicateKind.NONE
    existing_record: HistoryRecord | None = None

    @property
    def is_duplicate(self) -> bool:
        return self.kind is not DuplicateKind.NONE

    @property
    def needs_decision(self) -> bool:
        return self.kind in (DuplicateKind.OTHER_TARGET, DuplicateKind.ALREADY_QUEUED)


def target_directory(request: DownloadRequest) -> str:
    """The real target folder, including the playlist subfolder when one is made.

    Comparing `output_dir` alone is not enough: two playlists saved under the
    same base folder end up in different subfolders.
    """
    directory = os.path.normpath(request.output_dir or '')
    if request.is_playlist_item and request.create_playlist_folder and request.playlist_title:
        # Counterpart of PLAYLIST_FOLDER from the output template
        assert PLAYLIST_FOLDER.endswith('/')
        directory = os.path.join(directory, _safe_component(request.playlist_title))
    return directory


def _safe_component(name: str) -> str:
    """An approximation of what yt-dlp will do with the folder name."""
    cleaned = ''.join('_' if ch in '/\\:*?"<>|' else ch for ch in name).strip(' .')
    return cleaned or 'playlist'


class DuplicateService:
    """Checks for conflicts and reserves artifacts that are being processed.

    `check_and_reserve` is a single operation under the lock; otherwise two
    threads could both hear "not a duplicate" and fetch the same media.
    """

    def __init__(self, history: HistoryStore | None = None):
        self._history = history
        self._lock = threading.RLock()
        #: Artifacts reserved by queued or currently downloading items
        self._reserved: dict[str, str] = {}
        #: Per-batch conflict resolution policy
        self._policies: dict[str, DuplicatePolicy] = {}

    # ------------------------------------------------------------- policies

    def policy(self, batch_id: str) -> DuplicatePolicy:
        with self._lock:
            return self._policies.get(batch_id, DuplicatePolicy.ASK)

    def set_policy(self, batch_id: str, policy: DuplicatePolicy) -> None:
        """The policy applies to this batch only; it is not a stored setting."""
        with self._lock:
            if policy is DuplicatePolicy.ASK:
                self._policies.pop(batch_id, None)
            else:
                self._policies[batch_id] = policy

    def forget_batch(self, batch_id: str) -> None:
        with self._lock:
            self._policies.pop(batch_id, None)

    # --------------------------------------------------------- reservations

    def reserve(self, artifact: ArtifactIdentity, owner_id: str) -> bool:
        """Reserve an artifact. False when someone else already holds it."""
        if not artifact.is_valid:
            return True
        with self._lock:
            current = self._reserved.get(artifact.key)
            if current is not None and current != owner_id:
                return False
            self._reserved[artifact.key] = owner_id
            return True

    def release(self, artifact: ArtifactIdentity, owner_id: str) -> None:
        """Release a reservation once the job finishes or is cancelled."""
        if not artifact.is_valid:
            return
        with self._lock:
            if self._reserved.get(artifact.key) == owner_id:
                del self._reserved[artifact.key]

    def release_owner(self, owner_id: str) -> None:
        """Release everything an owner held, e.g. after a worker crash."""
        with self._lock:
            for key in [k for k, v in self._reserved.items() if v == owner_id]:
                del self._reserved[key]

    def reserved_count(self) -> int:
        with self._lock:
            return len(self._reserved)

    # ------------------------------------------------------------------ checks

    def check(self, request: DownloadRequest, identity: MediaIdentity,
              owner_id: str = '') -> DuplicateCheckResult:
        """The check alone, without reserving; used by tests and previews."""
        artifact = ArtifactIdentity.from_request(request, identity)
        if not artifact.is_valid:
            # Without a stable identifier we do not guess by title or filename
            return DuplicateCheckResult()

        with self._lock:
            holder = self._reserved.get(artifact.key)
            if holder is not None and holder != owner_id:
                return DuplicateCheckResult(DuplicateKind.ALREADY_QUEUED)

        return self._check_history(request, artifact)

    def check_and_reserve(self, request: DownloadRequest, identity: MediaIdentity,
                          owner_id: str) -> DuplicateCheckResult:
        """Check and reserve as one operation, so there is no race."""
        artifact = ArtifactIdentity.from_request(request, identity)
        if not artifact.is_valid:
            return DuplicateCheckResult()

        with self._lock:
            holder = self._reserved.get(artifact.key)
            if holder is not None and holder != owner_id:
                return DuplicateCheckResult(DuplicateKind.ALREADY_QUEUED)

            result = self._check_history(request, artifact)
            if result.kind is DuplicateKind.NONE:
                self._reserved[artifact.key] = owner_id
            return result

    def _check_history(self, request: DownloadRequest,
                       artifact: ArtifactIdentity) -> DuplicateCheckResult:
        if self._history is None:
            return DuplicateCheckResult()

        records = [record for record in self._history.find_by_identity(artifact.media)
                   if ArtifactIdentity.from_record(record) == artifact]
        if not records:
            return DuplicateCheckResult()

        target = os.path.normpath(target_directory(request))
        same_target = None
        other_target = None
        for record in records:
            # A record alone does not prove the file still exists; check the disk
            if not record.file_exists():
                continue
            existing_dir = os.path.normpath(os.path.dirname(record.final_path))
            if existing_dir == target:
                same_target = record
                break
            other_target = other_target or record

        if same_target is not None:
            return DuplicateCheckResult(DuplicateKind.SAME_TARGET, same_target)
        if other_target is not None:
            return DuplicateCheckResult(DuplicateKind.OTHER_TARGET, other_target)
        # History remembers the download but the file is gone; fetching again is fine
        return DuplicateCheckResult()
