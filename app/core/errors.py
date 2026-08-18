"""Recognising yt-dlp errors and reducing them to stable codes.

This layer knows nothing about the interface language: it returns an
`AppErrorCode` and the GUI composes the user-facing text
(`app/gui/labels.py`). The original yt-dlp message travels in `details`; it
reaches the log and is deliberately left untranslated.

The match patterns come from the messages in the local yt-dlp repository
(`utils/_utils.py`, `YoutubeDL.py`, `postprocessor/ffmpeg.py`).
"""

from __future__ import annotations

import dataclasses
import enum
import errno
import re


class AppErrorCode(enum.Enum):
    """A stable problem identifier, independent of language and yt-dlp version."""

    PRIVATE_VIDEO = 'private_video'
    AGE_RESTRICTED = 'age_restricted'
    LOGIN_REQUIRED = 'login_required'
    GEO_RESTRICTED = 'geo_restricted'
    UNAVAILABLE = 'unavailable'
    UNSUPPORTED_URL = 'unsupported_url'
    INVALID_URL = 'invalid_url'
    FORMAT_UNAVAILABLE = 'format_unavailable'
    NO_FORMATS = 'no_formats'
    FFMPEG_MISSING = 'ffmpeg_missing'
    NETWORK_ERROR = 'network_error'
    SSL_ERROR = 'ssl_error'
    PROXY_ERROR = 'proxy_error'
    PERMISSION_DENIED = 'permission_denied'
    NO_DISK_SPACE = 'no_disk_space'
    POSTPROCESSING_FAILED = 'postprocessing_failed'
    MERGE_FAILED = 'merge_failed'
    NOT_LIVE_YET = 'not_live_yet'
    NOTHING_FOUND = 'nothing_found'
    #: Further playlist pages could not be read
    PLAYLIST_INCOMPLETE = 'playlist_incomplete'
    UNKNOWN = 'unknown'


class ErrorCategory(enum.Enum):
    """Error group; useful for icons, messages and the retry decision."""

    NETWORK = 'network'
    HTTP = 'http'
    EXTRACTOR = 'extractor'
    AUTH = 'auth'
    GEO = 'geo'
    FORMAT = 'format'
    FFMPEG = 'ffmpeg'
    FILESYSTEM = 'filesystem'
    PLAYLIST_ENUMERATION = 'playlist_enumeration'
    UNKNOWN = 'unknown'


#: Which group a given code belongs to
_CATEGORIES: dict[AppErrorCode, ErrorCategory] = {
    AppErrorCode.PRIVATE_VIDEO: ErrorCategory.AUTH,
    AppErrorCode.AGE_RESTRICTED: ErrorCategory.AUTH,
    AppErrorCode.LOGIN_REQUIRED: ErrorCategory.AUTH,
    AppErrorCode.GEO_RESTRICTED: ErrorCategory.GEO,
    AppErrorCode.UNAVAILABLE: ErrorCategory.EXTRACTOR,
    AppErrorCode.UNSUPPORTED_URL: ErrorCategory.EXTRACTOR,
    AppErrorCode.INVALID_URL: ErrorCategory.EXTRACTOR,
    AppErrorCode.NOTHING_FOUND: ErrorCategory.EXTRACTOR,
    AppErrorCode.NOT_LIVE_YET: ErrorCategory.EXTRACTOR,
    AppErrorCode.FORMAT_UNAVAILABLE: ErrorCategory.FORMAT,
    AppErrorCode.NO_FORMATS: ErrorCategory.FORMAT,
    AppErrorCode.FFMPEG_MISSING: ErrorCategory.FFMPEG,
    AppErrorCode.POSTPROCESSING_FAILED: ErrorCategory.FFMPEG,
    AppErrorCode.MERGE_FAILED: ErrorCategory.FFMPEG,
    AppErrorCode.NETWORK_ERROR: ErrorCategory.NETWORK,
    AppErrorCode.SSL_ERROR: ErrorCategory.NETWORK,
    AppErrorCode.PROXY_ERROR: ErrorCategory.NETWORK,
    AppErrorCode.PLAYLIST_INCOMPLETE: ErrorCategory.PLAYLIST_ENUMERATION,
    AppErrorCode.PERMISSION_DENIED: ErrorCategory.FILESYSTEM,
    AppErrorCode.NO_DISK_SPACE: ErrorCategory.FILESYSTEM,
}

#: Transient problems worth another automatic attempt. Anything else (private
#: video, missing FFmpeg, no disk space) will not fix itself, so attempts are
#: not spent on it. Manual retry always stays available.
#:
#: PLAYLIST_INCOMPLETE is deliberately absent: retrying the job would restart
#: enumeration from the first page, discard the entries already discovered and,
#: for a dynamic mix, return a different set of items altogether.
_RETRYABLE = frozenset({
    AppErrorCode.NETWORK_ERROR,
    AppErrorCode.SSL_ERROR,
    AppErrorCode.PROXY_ERROR,
    AppErrorCode.UNKNOWN,
})


def is_retryable(code: AppErrorCode | None) -> bool:
    """Whether an automatic retry makes sense. Never blocks a manual one."""
    return code in _RETRYABLE if code is not None else True


@dataclasses.dataclass(frozen=True)
class FriendlyError:
    """A recognised problem: a code for the GUI plus the original log text."""

    code: AppErrorCode = AppErrorCode.UNKNOWN
    details: str = ''

    @property
    def is_known(self) -> bool:
        return self.code is not AppErrorCode.UNKNOWN

    @property
    def category(self) -> ErrorCategory:
        return _CATEGORIES.get(self.code, ErrorCategory.UNKNOWN)

    @property
    def is_retryable(self) -> bool:
        return is_retryable(self.code)


# Order matters: the first matching fragment wins.
_PATTERNS: tuple[tuple[tuple[str, ...], AppErrorCode], ...] = (
    (('private video', 'this video is private'), AppErrorCode.PRIVATE_VIDEO),
    (('sign in to confirm your age', 'age-restricted', 'age restricted', 'confirm your age'),
     AppErrorCode.AGE_RESTRICTED),
    (('sign in', 'log in', 'login required', 'requires authentication', 'account'),
     AppErrorCode.LOGIN_REQUIRED),
    # yt-dlp extractors use many variants of the same message; the common
    # denominator is the phrase "available in your country"
    (('available in your country', 'geo restricted', 'geo-restricted',
      'blocked in your country', 'not available from your location'), AppErrorCode.GEO_RESTRICTED),
    (('video unavailable', 'has been removed', 'no longer available', 'video has been deleted'),
     AppErrorCode.UNAVAILABLE),
    (('unsupported url',), AppErrorCode.UNSUPPORTED_URL),
    (('is not a valid url', 'invalid url'), AppErrorCode.INVALID_URL),
    (('requested format is not available',), AppErrorCode.FORMAT_UNAVAILABLE),
    (('no video formats found', 'drm protected'), AppErrorCode.NO_FORMATS),
    (('ffmpeg not found', 'ffprobe and ffmpeg not found', 'ffmpeg is not installed'),
     AppErrorCode.FFMPEG_MISSING),
    (('unable to download webpage', 'unable to download api page', 'connection', 'timed out',
      'temporary failure in name resolution', 'network is unreachable'), AppErrorCode.NETWORK_ERROR),
    (('certificate verify failed', 'ssl'), AppErrorCode.SSL_ERROR),
    (('proxy',), AppErrorCode.PROXY_ERROR),
    (('permission denied',), AppErrorCode.PERMISSION_DENIED),
    (('no space left',), AppErrorCode.NO_DISK_SPACE),
    (('postprocessing:', 'error while processing'), AppErrorCode.POSTPROCESSING_FAILED),
    (('merging', 'unable to merge'), AppErrorCode.MERGE_FAILED),
    (('this live event will begin', 'is not currently live', 'premieres in'),
     AppErrorCode.NOT_LIVE_YET),
)


def _clean(text: str) -> str:
    """Strip the prefixes yt-dlp wraps its messages in."""
    text = (text or '').strip()
    for prefix in ('ERROR: ', 'WARNING: '):
        if text.startswith(prefix):
            text = text[len(prefix):]
    # yt-dlp appends a bug-report hint, which is noise for the user
    for marker in ('; please report this issue', '. Please report this issue',
                   ' Please report this issue'):
        index = text.find(marker)
        if index > 0:
            text = text[:index]
    return text.strip()


def describe(exc: BaseException) -> FriendlyError:
    """Recognise an exception and return its code plus the original message."""
    details = _clean(str(exc)) or exc.__class__.__name__

    if isinstance(exc, OSError) and exc.errno:
        if exc.errno == errno.ENOSPC:
            return FriendlyError(AppErrorCode.NO_DISK_SPACE, details)
        if exc.errno in (errno.EACCES, errno.EPERM):
            return FriendlyError(AppErrorCode.PERMISSION_DENIED, details)

    # Checked before the substring table: a paginated playlist failure looks
    # like a plain network error but must not restart the whole job.
    if is_enumeration_error(details):
        return FriendlyError(AppErrorCode.PLAYLIST_INCOMPLETE, details)

    lowered = details.lower()
    for needles, code in _PATTERNS:
        if any(needle in lowered for needle in needles):
            return FriendlyError(code, details)
    return FriendlyError(AppErrorCode.UNKNOWN, details)


def shorten(text: str, limit: int = 160) -> str:
    """Shorten a long message to its first sentence; the rest stays in the log."""
    text = (text or '').replace('\n', ' ').strip()
    if len(text) <= limit:
        return text
    cut = text.find('. ')
    if 0 < cut < limit:
        return text[: cut + 1]
    return text[: limit - 3] + '…'


# ---------------------------------------------------------- error collection

#: A playlist pagination error, e.g.
#: "RDLkCFJjB64pY page 3: Unable to download API page: HTTP Error 403: Forbidden".
#: Such an error is not about one video: it means the rest of the list is
#: unknown, so a complete success must not be reported.
_ENUMERATION_RE = re.compile(
    r'page\s+\d+\s*:.*unable to download|unable to download (?:api page|continuation)',
    re.IGNORECASE,
)

#: yt-dlp appends a technical cause that makes the same error differ per layer
_CAUSED_BY_RE = re.compile(r'\s*\(caused by .*?\)\s*$', re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r'\s+')


def is_enumeration_error(message: str) -> bool:
    """Whether the message reports a failure to read a further playlist page."""
    return bool(_ENUMERATION_RE.search(message or ''))


def normalize_error(message: str) -> str:
    """The message form used for deduplication.

    The same problem comes back with the `ERROR: ` prefix, without it, and
    with a `(caused by ...)` suffix; after normalisation that is one entry,
    not three.
    """
    text = _clean(message or '')
    text = _CAUSED_BY_RE.sub('', text)
    return _WHITESPACE_RE.sub(' ', text).strip()


@dataclasses.dataclass
class ErrorLog:
    """Collects error messages without repetition and separates their kinds."""

    #: Errors concerning the media itself or the download
    items: list[str] = dataclasses.field(default_factory=list)
    #: Errors while reading further playlist pages
    enumeration: list[str] = dataclasses.field(default_factory=list)
    _seen: set[str] = dataclasses.field(default_factory=set, repr=False)

    def add(self, message: str) -> None:
        text = normalize_error(message)
        if not text or text in self._seen:
            return
        self._seen.add(text)
        if is_enumeration_error(text):
            self.enumeration.append(text)
        else:
            self.items.append(text)

    @property
    def enumeration_failed(self) -> bool:
        return bool(self.enumeration)

    def __bool__(self) -> bool:
        return bool(self.items or self.enumeration)
