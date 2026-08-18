"""URL intent classification and canonical single-media URLs.

One central place decides whether an address means *this one video* or *a whole
playlist*, and turns a single-media address into its canonical form. Every other
layer — analysis, download, playlist children, retries, history — asks here
instead of re-implementing the rules.

The distinction matters because a link copied while a video plays inside a
playlist or a YouTube Mix carries the playlist context:

    https://youtu.be/NPmRmfodJmk?list=RDLkCFJjB64pY

`YoutubeYtBeIE` rewrites that into `watch?v=<id>&list=<id>`, handed to
`YoutubeTabIE`, whose `_yes_playlist()` then enumerates the entire mix (see
`yt_dlp/extractor/youtube/_redirect.py` and `yt_dlp/extractor/common.py`). The
user asked for one song, so the intent is SINGLE_MEDIA and the URL is
normalised to `https://www.youtube.com/watch?v=<id>`.

A bare playlist address (`youtube.com/playlist?list=...`) keeps the PLAYLIST
intent, and anything we do not recognise stays UNKNOWN so yt-dlp decides.
"""

from __future__ import annotations

import enum
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

#: Query parameters that carry playlist or mix context rather than identity.
PLAYLIST_QUERY_PARAMS = frozenset({
    'list', 'index', 'start_radio', 'feature', 'pp', 'playlist', 'playnext',
})

#: Hosts served by the YouTube extractors.
_YOUTUBE_HOSTS = frozenset({
    'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com',
    'youtube-nocookie.com', 'www.youtube-nocookie.com', 'youtu.be', 'www.youtu.be',
})

_YOUTUBE_WATCH = 'https://www.youtube.com/watch?v={media_id}'
#: A YouTube video id: exactly 11 characters from the URL-safe base64 alphabet
_YOUTUBE_ID_RE = re.compile(r'^[0-9A-Za-z_-]{11}$')

#: Path prefixes that address exactly one video, with the id as the next segment
_SINGLE_MEDIA_PATHS = ('shorts', 'live', 'embed', 'v')

#: Path prefixes that always address a collection
_PLAYLIST_PATHS = ('playlist', 'channel', 'user', 'c', 'feed', 'results', 'podcast')


class UrlIntent(enum.Enum):
    """What an address means to the user who pasted it."""

    #: Exactly one video or track, even when playlist context rides along
    SINGLE_MEDIA = 'single_media'
    #: A playlist, mix, channel or another collection
    PLAYLIST = 'playlist'
    #: Not recognised here; yt-dlp decides
    UNKNOWN = 'unknown'


def is_youtube_url(url: str) -> bool:
    """True when the address is served by the YouTube extractors."""
    return _host(url) in _YOUTUBE_HOSTS


def is_youtube(extractor: str) -> bool:
    """True for every YouTube extractor key (`Youtube`, `youtube:tab`, ...)."""
    return (extractor or '').lower().startswith('youtube')


def youtube_video_id(url: str) -> str:
    """The video id an address points at, or an empty string.

    Recognises `youtu.be/<id>`, `watch?v=<id>` and the `shorts` / `live` /
    `embed` / `v` path forms.
    """
    parsed = urlparse(url or '')
    host = (parsed.hostname or '').lower()
    if host not in _YOUTUBE_HOSTS:
        return ''

    segments = [segment for segment in parsed.path.split('/') if segment]

    if host in ('youtu.be', 'www.youtu.be'):
        candidate = segments[0] if segments else ''
        return candidate if _YOUTUBE_ID_RE.match(candidate) else ''

    if segments and segments[0] == 'watch':
        pass  # the id lives in the query, handled below
    elif len(segments) >= 2 and segments[0] in _SINGLE_MEDIA_PATHS:
        return segments[1] if _YOUTUBE_ID_RE.match(segments[1]) else ''
    elif segments:
        return ''

    candidate = _query(url).get('v', '')
    return candidate if _YOUTUBE_ID_RE.match(candidate) else ''


def classify_url(url: str) -> UrlIntent:
    """Decide whether an address means one media item or a collection.

    The presence of a `list=` parameter alone never makes something a playlist:
    a watch or `youtu.be` link identifies one video, and the playlist context is
    only where it was found.
    """
    if not (url or '').strip():
        return UrlIntent.UNKNOWN

    if not is_youtube_url(url):
        return UrlIntent.UNKNOWN

    if youtube_video_id(url):
        return UrlIntent.SINGLE_MEDIA

    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split('/') if segment]
    first = segments[0] if segments else ''
    if first in _PLAYLIST_PATHS or first.startswith('@'):
        return UrlIntent.PLAYLIST
    if not first and 'list' in _query(url):
        return UrlIntent.PLAYLIST
    return UrlIntent.UNKNOWN


def strip_playlist_params(url: str) -> str:
    """Drop playlist-context query parameters, keeping everything else intact."""
    if not url:
        return ''
    parsed = urlparse(url)
    if not parsed.query:
        return url
    kept = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key not in PLAYLIST_QUERY_PARAMS]
    return urlunparse(parsed._replace(query=urlencode(kept)))


def normalize_url(url: str, intent: UrlIntent | None = None) -> str:
    """Canonical form of an address for the given intent.

    SINGLE_MEDIA YouTube links become `https://www.youtube.com/watch?v=<id>`.
    Everything else is returned untouched, so other services and genuine
    playlist addresses keep working exactly as before.
    """
    url = (url or '').strip()
    if not url:
        return ''

    intent = classify_url(url) if intent is None else intent
    if intent is not UrlIntent.SINGLE_MEDIA:
        return url

    media_id = youtube_video_id(url)
    if media_id:
        return _YOUTUBE_WATCH.format(media_id=media_id)
    return strip_playlist_params(url)


def canonical_media_url(url: str, *, extractor: str = '', media_id: str = '') -> str:
    """A URL that resolves to exactly one media item.

    Used for playlist entries, where the extractor and the media id are already
    known from the enumeration. YouTube gets an explicit `watch?v=<id>` URL;
    other services only lose their playlist query parameters, which is safe
    whatever the extractor.
    """
    if is_youtube(extractor) and media_id and _YOUTUBE_ID_RE.match(media_id):
        return _YOUTUBE_WATCH.format(media_id=media_id)

    if is_youtube_url(url):
        normalized = normalize_url(url, UrlIntent.SINGLE_MEDIA)
        if normalized != url:
            return normalized
    return strip_playlist_params(url)


def has_playlist_context(url: str) -> bool:
    """True when the URL would make an extractor look at a playlist."""
    if not url:
        return False
    query = _query(url)
    return any(key in query for key in PLAYLIST_QUERY_PARAMS if key != 'feature')


def playlist_url_for(url: str) -> str:
    """The playlist an address was found in, or an empty string.

    Lets the interface offer "download the whole playlist instead" without
    re-parsing the original address elsewhere.
    """
    playlist_id = _query(url).get('list', '')
    if not playlist_id or not is_youtube_url(url):
        return ''
    return f'https://www.youtube.com/playlist?list={playlist_id}'


def _host(url: str) -> str:
    try:
        return (urlparse(url or '').hostname or '').lower()
    except ValueError:
        return ''


def _query(url: str) -> dict[str, str]:
    try:
        return dict(parse_qsl(urlparse(url or '').query, keep_blank_values=True))
    except ValueError:
        return {}
