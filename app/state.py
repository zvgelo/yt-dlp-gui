"""Application and task states.

Widgets react to `AppState` (what the window as a whole is doing) and queue
cards to `TaskState` (what is happening to one item).

The enums carry no user-facing text; `app/gui/labels.py` turns them into words
so the domain layer stays language agnostic.
"""

from __future__ import annotations

import enum


class AppState(enum.Enum):
    """Overall application state, used to enable and disable controls."""

    IDLE = 'idle'
    ANALYZING = 'analyzing'
    READY = 'ready'
    DOWNLOADING = 'downloading'
    POSTPROCESSING = 'postprocessing'
    FINISHED = 'finished'
    ERROR = 'error'
    CANCELLED = 'cancelled'

    @property
    def is_busy(self) -> bool:
        return self in (AppState.ANALYZING, AppState.DOWNLOADING, AppState.POSTPROCESSING)


class TaskState(enum.Enum):
    """State of a single queue item."""

    QUEUED = 'queued'
    DOWNLOADING = 'downloading'
    POSTPROCESSING = 'postprocessing'
    #: An attempt failed but automatic retries are still available
    RETRYING = 'retrying'
    #: A duplicate was found; waiting for the user without blocking the queue
    NEEDS_REVIEW = 'needs_review'
    FINISHED = 'finished'
    #: Something was downloaded but completeness cannot be guaranteed
    COMPLETED_WITH_ERRORS = 'completed_with_errors'
    #: The same item already exists in the destination folder
    SKIPPED_DUPLICATE = 'skipped_duplicate'
    #: The user deliberately skipped the item; this is not an error
    SKIPPED_BY_USER = 'skipped_by_user'
    ERROR = 'error'
    CANCELLED = 'cancelled'
    #: The application closed mid-work; restored from history as interrupted
    INTERRUPTED = 'interrupted'

    @property
    def is_active(self) -> bool:
        """Waiting or working — the definition behind the "In progress" tab."""
        return self in ACTIVE_TASK_STATES

    @property
    def needs_decision(self) -> bool:
        """Waiting for the user — the definition behind the "Needs review" tab."""
        return self in REVIEW_TASK_STATES

    @property
    def is_skipped(self) -> bool:
        """Skipped deliberately or automatically; deliberately not an error."""
        return self in SKIPPED_TASK_STATES

    @property
    def is_final(self) -> bool:
        return self in TERMINAL_TASK_STATES

    @property
    def is_ok(self) -> bool:
        """Whether the task finished without reservations."""
        return self is TaskState.FINISHED

    @property
    def shows_progress(self) -> bool:
        """Whether to draw a progress bar; a queued item has not started yet."""
        return self in (TaskState.DOWNLOADING, TaskState.POSTPROCESSING)

    @property
    def is_failed(self) -> bool:
        """Final failure — the definition behind the "Failed" tab.

        A failed attempt is not enough: while automatic retries remain the task
        is RETRYING and stays in progress.
        """
        return self is TaskState.ERROR


#: States meaning work is pending or running. Single source of truth so views
#: never repeat `if state != FINISHED and ...`.
ACTIVE_TASK_STATES = frozenset({
    TaskState.QUEUED,
    TaskState.DOWNLOADING,
    TaskState.POSTPROCESSING,
    TaskState.RETRYING,
})

#: Skips form their own category and are never reported as errors
SKIPPED_TASK_STATES = frozenset({
    TaskState.SKIPPED_DUPLICATE,
    TaskState.SKIPPED_BY_USER,
})

#: Final states; the task will not return to the queue on its own
TERMINAL_TASK_STATES = frozenset({
    TaskState.FINISHED,
    TaskState.COMPLETED_WITH_ERRORS,
    TaskState.ERROR,
    TaskState.CANCELLED,
    TaskState.INTERRUPTED,
    *SKIPPED_TASK_STATES,
})

#: Waiting for a decision: neither active nor final
REVIEW_TASK_STATES = frozenset({TaskState.NEEDS_REVIEW})
