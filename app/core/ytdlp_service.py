"""The only application layer that talks to `yt_dlp.YoutubeDL`.

Everything below uses the public yt-dlp API: `YoutubeDL.extract_info`,
`progress_hooks`, `postprocessor_hooks`, `logger` and the native
postprocessors. The CLI is never invoked and its output is never parsed.

The postprocessor order mirrors `yt_dlp/__init__.py::get_postprocessors` from
the local repository, and it matters (ModifyChapters before FFmpegMetadata,
metadata after the container conversion, EmbedThumbnail last).
"""

from __future__ import annotations

import dataclasses
import enum
import os
from collections.abc import Callable

from ..settings import AppSettings
from .errors import ErrorLog, normalize_error
from .format_service import build_selector, parse_formats
from .models import (
    DownloadProgress,
    DownloadRequest,
    DownloadResult,
    MediaInfo,
    PlaylistEntry,
    SubtitleTrack,
)
from .output_template import build_output_template
from .runtime_tools import RuntimeTools, ToolSource
from .urls import UrlIntent, canonical_media_url, classify_url, normalize_url

MAX_PLAYLIST_ITEMS = 1000

#: Seconds to wait for an unresponsive host before yt-dlp gives up
SOCKET_TIMEOUT = 20


class PostProcessStage(enum.Enum):
    """A post-processing stage; carries no text, the GUI translates it."""

    MERGING = 'merging'
    REMUXING = 'remuxing'
    CONVERTING_VIDEO = 'converting_video'
    EXTRACTING_AUDIO = 'extracting_audio'
    WRITING_METADATA = 'writing_metadata'
    PARSING_METADATA = 'parsing_metadata'
    EMBEDDING_THUMBNAIL = 'embedding_thumbnail'
    EMBEDDING_SUBTITLES = 'embedding_subtitles'
    CONVERTING_SUBTITLES = 'converting_subtitles'
    CONVERTING_THUMBNAIL = 'converting_thumbnail'
    SPONSORBLOCK = 'sponsorblock'
    REMOVING_SEGMENTS = 'removing_segments'
    SPLITTING_CHAPTERS = 'splitting_chapters'
    MOVING_FILE = 'moving_file'
    CONCATENATING = 'concatenating'
    FIXING_FILE = 'fixing_file'
    OTHER = 'other'


#: Names from `postprocessor_hooks` mapped onto a stage.
#: The keys are `PostProcessor.pp_key()` values, which strip the "PP" suffix
#: and the "FFmpeg" prefix (see yt_dlp/postprocessor/common.py).
POSTPROCESSOR_STAGES = {
    'Merger': PostProcessStage.MERGING,
    'VideoRemuxer': PostProcessStage.REMUXING,
    'VideoConvertor': PostProcessStage.CONVERTING_VIDEO,
    'ExtractAudio': PostProcessStage.EXTRACTING_AUDIO,
    'Metadata': PostProcessStage.WRITING_METADATA,
    'MetadataParser': PostProcessStage.PARSING_METADATA,
    'EmbedThumbnail': PostProcessStage.EMBEDDING_THUMBNAIL,
    'EmbedSubtitle': PostProcessStage.EMBEDDING_SUBTITLES,
    'SubtitlesConvertor': PostProcessStage.CONVERTING_SUBTITLES,
    'ThumbnailsConvertor': PostProcessStage.CONVERTING_THUMBNAIL,
    'SponsorBlock': PostProcessStage.SPONSORBLOCK,
    'ModifyChapters': PostProcessStage.REMOVING_SEGMENTS,
    'SplitChapters': PostProcessStage.SPLITTING_CHAPTERS,
    'MoveFiles': PostProcessStage.MOVING_FILE,
    'Concat': PostProcessStage.CONCATENATING,
    'FixupM3u8': PostProcessStage.FIXING_FILE,
    'FixupM4a': PostProcessStage.FIXING_FILE,
    'FixupDuration': PostProcessStage.FIXING_FILE,
    'FixupTimestamp': PostProcessStage.FIXING_FILE,
    'FixupStretched': PostProcessStage.FIXING_FILE,
    'FixupDuplicateMoov': PostProcessStage.FIXING_FILE,
}


class Logger:
    """A logger matching the `YoutubeDL` contract (debug/info/warning/error).

    Besides forwarding text to the GUI it records errors in `errors`, because
    yt-dlp only reports some problems instead of raising; without that a job
    would finish as a "success" despite visible errors in the log. The logger
    is only one source though: exceptions and the actual `extract_info`
    result also decide the status.
    """

    def __init__(self, sink: Callable[[str, str], None], *, verbose: bool = False,
                 errors: ErrorLog | None = None):
        self._sink = sink
        self._verbose = verbose
        self.errors = errors if errors is not None else ErrorLog()

    def debug(self, msg):
        # yt-dlp sends both real debug lines (the '[debug] ' prefix) and screen messages here
        if msg.startswith('[debug] '):
            if self._verbose:
                self._sink('DEBUG', msg[len('[debug] '):])
        else:
            self._sink('INFO', msg)

    def info(self, msg):
        self._sink('INFO', msg)

    def warning(self, msg, *_args, **_kwargs):
        self._sink('WARN', msg)

    def error(self, msg, *_args, **_kwargs):
        self.errors.add(msg)
        self._sink('ERROR', msg)


class NullLogger(Logger):
    def __init__(self):
        super().__init__(lambda _level, _msg: None)


@dataclasses.dataclass(frozen=True)
class FFmpegStatus:
    available: bool
    probe_available: bool
    version: str = ''
    path: str = ''
    #: True when the copy shipped with this build is the one in use
    bundled: bool = False

    @property
    def message(self) -> str:
        if self.available:
            return f'FFmpeg {self.version}' if self.version else 'FFmpeg available'
        return ('FFmpeg was not found. Merging video with audio, audio conversion, '
                'cover art and subtitle embedding will be unavailable.')


@dataclasses.dataclass
class DownloadCallbacks:
    """Worker hooks; all of them are called from the worker thread."""

    on_progress: Callable[[DownloadProgress], None] | None = None
    on_postprocessor: Callable[[PostProcessStage, str], None] | None = None
    is_cancelled: Callable[[], bool] | None = None


class YtDlpService:
    """Builds the options and runs yt-dlp. The methods block; call from a worker."""

    def __init__(self, settings: AppSettings, tools: RuntimeTools | None = None):
        self._settings = settings
        self._tools = tools if tools is not None else self._build_tools(settings)

    @property
    def settings(self) -> AppSettings:
        return self._settings

    @property
    def tools(self) -> RuntimeTools:
        """The helper binaries this service will hand to yt-dlp."""
        return self._tools

    def update_settings(self, settings: AppSettings) -> None:
        configured_changed = settings.ffmpeg_location != self._settings.ffmpeg_location
        self._settings = settings
        if configured_changed:
            # The probes are cached, so a new configured path needs a new locator
            self._tools = self._build_tools(settings)

    @staticmethod
    def _build_tools(settings: AppSettings) -> RuntimeTools:
        return RuntimeTools({'ffmpeg': settings.ffmpeg_location,
                             'ffprobe': settings.ffmpeg_location})

    # ------------------------------------------------------------ options

    def base_options(self) -> dict:
        """Options shared by analysis and downloading."""
        s = self._settings
        options: dict = {
            'quiet': True,
            'no_warnings': False,
            'noprogress': True,
            'consoletitle': False,
            'color': {'stdout': 'no_color', 'stderr': 'no_color'},
            'ignoreerrors': False,
            'retries': s.retries,
            'fragment_retries': s.retries,
            # An unresponsive host must not pin the download thread. Without a
            # timeout the progress hook never fires, so a cancel request is
            # never noticed and shutdown has nothing to wait for.
            'socket_timeout': SOCKET_TIMEOUT,
            'verbose': s.verbose_log,
        }
        if s.cookies_from_browser:
            options['cookiesfrombrowser'] = (s.cookies_from_browser,)
        if s.cookies_file:
            options['cookiefile'] = s.cookies_file
        if s.proxy:
            options['proxy'] = s.proxy

        # Helper binaries are resolved in one place: bundled first, then the
        # configured path, then PATH. Telling yt-dlp explicitly is what makes a
        # packaged build independent of whatever the machine happens to have.
        location = self._tools.ffmpeg_location
        if location:
            options['ffmpeg_location'] = location

        # Without a JS runtime YouTube extraction is degraded and yt-dlp says so
        # (see yt_dlp/extractor/youtube/_video.py). The parameter shape is
        # documented on YoutubeDL: {'deno': {'path': ...}}.
        js_runtimes = self._tools.js_runtimes
        if js_runtimes:
            options['js_runtimes'] = js_runtimes
        return options

    def probe_options(self, intent: UrlIntent = UrlIntent.UNKNOWN) -> dict:
        """Options for analysing a URL without downloading.

        `extract_flat='in_playlist'` keeps the full metadata for a single media
        item while flattening playlist entries. The playlist itself is then read
        as a stream (`extract_info(process=False)`), so `playlist_items` is not
        set here; the limit is applied while iterating.

        `noplaylist` follows the intent of the address rather than a global
        setting: a watch link that merely carries playlist context analyses one
        video, while a genuine playlist address still enumerates.
        """
        options = self.base_options()
        options.update({
            'skip_download': True,
            'noplaylist': intent is UrlIntent.SINGLE_MEDIA,
            'extract_flat': 'in_playlist',
            'lazy_playlist': True,
        })
        return options

    def download_options(self, request: DownloadRequest) -> dict:
        """The full download options for a single request."""
        s = self._settings
        options = self.base_options()

        template = build_output_template(
            s.outtmpl,
            is_playlist=request.is_playlist_item,
            create_folder=request.create_playlist_folder,
            numbered=request.number_playlist_files,
        )
        options.update({
            'format': build_selector(request),
            'paths': {'home': request.output_dir},
            'outtmpl': {'default': template},
            'restrictfilenames': s.restrict_filenames,
            'windowsfilenames': os.name == 'nt',
            'trim_file_name': 200,
            'overwrites': s.overwrite or None,
            'continuedl': True,
            'concurrent_fragment_downloads': max(1, s.concurrent_fragments),
            'writeinfojson': request.write_info_json,
            'writedescription': request.write_description,
            # A download job always covers exactly one media item, so playlist
            # context in the address must never widen it. This is the second
            # line of defence behind the canonical URL in `DownloadRequest`.
            'noplaylist': True,
            # Process items as they arrive. Without this,
            # YoutubeDL.__process_playlist does `list(entries)` and a failure to
            # read a further page aborts the job before anything is downloaded
            # (yt_dlp/YoutubeDL.py: __process_playlist).
            'lazy_playlist': True,
        })

        if not request.is_audio and request.container:
            # Merge straight into the right container instead of converting later
            options['merge_output_format'] = request.container
            options['final_ext'] = request.container

        rate = _parse_rate(s.rate_limit)
        if rate:
            options['ratelimit'] = rate

        wants_subs = request.write_subtitles and not request.is_audio
        if wants_subs:
            options.update({
                'writesubtitles': True,
                'writeautomaticsub': request.auto_subtitles,
                'subtitleslangs': list(request.subtitle_languages) or ['en'],
            })

        if request.embed_thumbnail or request.write_thumbnail:
            options['writethumbnail'] = True
            if not request.write_thumbnail:
                # The cover is only material to embed; do not leave it on disk
                options['outtmpl']['pl_thumbnail'] = ''

        options['postprocessors'] = self._postprocessors(request, wants_subs=wants_subs)
        return options

    def _postprocessors(self, request: DownloadRequest, *, wants_subs: bool) -> list[dict]:
        s = self._settings
        pps: list[dict] = []

        if request.parse_artist_title and request.is_audio:
            from yt_dlp.postprocessor import MetadataFromFieldPP
            # Write to `artist` and `track`, not to `title`: FFmpegMetadata reads
            # the title tag from ('track', 'title'), so the tags come out right
            # while the filename (%(title)s) stays untouched
            pps.append({
                'key': 'MetadataParser',
                'when': 'pre_process',
                'actions': [MetadataFromFieldPP.to_action('title:(?P<artist>.+?) - (?P<track>.+)')],
            })

        sponsors = s.sponsorblock_categories
        if sponsors:
            pps.append({'key': 'SponsorBlock', 'categories': set(sponsors), 'when': 'after_filter'})

        if request.is_audio:
            pps.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': request.audio_format or 'best',
                'preferredquality': str(request.quality) if request.quality > 0 else '0',
            })
        elif request.container:
            # Remuxing is lossless; it fixes the container when merging did not set it
            pps.append({'key': 'FFmpegVideoRemuxer', 'preferedformat': request.container})

        if wants_subs and request.embed_subtitles:
            pps.append({'key': 'FFmpegEmbedSubtitle', 'already_have_subtitle': True})

        if sponsors:
            # Must come before FFmpegMetadata
            pps.append({
                'key': 'ModifyChapters',
                'remove_sponsor_segments': set(sponsors),
                'sponsorblock_chapter_title': '[SponsorBlock]: %(category_names)l',
            })

        if request.embed_metadata or request.embed_chapters:
            pps.append({
                'key': 'FFmpegMetadata',
                'add_metadata': request.embed_metadata,
                'add_chapters': request.embed_chapters,
                'add_infojson': 'if_exists',
            })

        if request.embed_thumbnail:
            pps.append({'key': 'EmbedThumbnail', 'already_have_thumbnail': request.write_thumbnail})

        return pps

    # ---------------------------------------------------------- analysis

    def extract(self, url: str, logger: Logger | None = None) -> MediaInfo:
        """URL analysis without downloading. Blocking; run it in a worker.

        A playlist is read with `process=False`, so we get an entry generator
        and consume it ourselves. That way a failure to read a further page
        (e.g. HTTP 403 on page 3) does not wipe out the entries found earlier:
        with default settings `YoutubeDL.__process_playlist` calls
        `list(entries)` before any processing, and an exception takes
        everything with it.

        The intent of the address decides everything else: a watch or
        `youtu.be` link is analysed as one video even when it carries playlist
        context, so what the user sees matches what will be downloaded.
        """
        from yt_dlp import YoutubeDL

        intent = classify_url(url)
        target = normalize_url(url, intent)

        options = self.probe_options(intent)
        options['logger'] = logger or NullLogger()
        with YoutubeDL(options) as ydl:
            raw = _resolve_redirects(ydl, target)
            if not raw:
                raise ValueError('No media found at this address')

            if raw.get('_type') in ('playlist', 'multi_video'):
                return build_playlist_info(target, raw)

            processed = ydl.sanitize_info(ydl.process_ie_result(raw, download=False))
        return build_media_info(target, processed)

    # --------------------------------------------------------- downloading

    def download(self, request: DownloadRequest, callbacks: DownloadCallbacks,
                 logger: Logger | None = None) -> DownloadResult:
        """Download the media and return a described result.

        A worker finishing does not by itself mean success: the status follows
        from the exception, the errors collected by the logger and how many
        items were actually downloaded.
        """
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadCancelled

        logger = logger or NullLogger()
        completed_ids: set[str] = set()

        def guard() -> None:
            if callbacks.is_cancelled and callbacks.is_cancelled():
                # Cooperative abort: YoutubeDL recognises this exception and
                # shuts down in a controlled way
                raise DownloadCancelled('Cancelled by the user')

        def progress_hook(payload: dict) -> None:
            guard()
            if payload.get('status') == 'finished':
                # The hook fires once per file (video and audio separately), so
                # count unique media identifiers rather than calls
                media_id = (payload.get('info_dict') or {}).get('id')
                if media_id:
                    completed_ids.add(str(media_id))
            if callbacks.on_progress:
                callbacks.on_progress(DownloadProgress.from_hook(payload))

        def postprocessor_hook(payload: dict) -> None:
            guard()
            if callbacks.on_postprocessor:
                name = payload.get('postprocessor') or ''
                stage = POSTPROCESSOR_STAGES.get(name, PostProcessStage.OTHER)
                callbacks.on_postprocessor(stage, payload.get('status') or '')

        options = self.download_options(request)
        options['progress_hooks'] = [progress_hook]
        options['postprocessor_hooks'] = [postprocessor_hook]
        options['logger'] = logger

        os.makedirs(request.output_dir, exist_ok=True)
        info: dict | None = None
        fatal = False
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(request.url, download=True)
        except DownloadCancelled:
            return DownloadResult.classify(cancelled=True, completed=len(completed_ids))
        except Exception as exc:  # noqa: BLE001 - the exception feeds the status, not a crash
            if callbacks.is_cancelled and callbacks.is_cancelled():
                return DownloadResult.classify(cancelled=True, completed=len(completed_ids))
            logger.errors.add(str(exc))
            fatal = True

        if callbacks.is_cancelled and callbacks.is_cancelled():
            return DownloadResult.classify(cancelled=True, completed=len(completed_ids))

        return build_result(info, logger.errors, completed_ids, fatal=fatal)

    # ------------------------------------------------------------ FFmpeg

    def ffmpeg_status(self) -> FFmpegStatus:
        """What the shared locator found, rather than a second search of our own."""
        ffmpeg, ffprobe = self._tools.ffmpeg, self._tools.ffprobe
        return FFmpegStatus(
            available=ffmpeg.usable,
            probe_available=ffprobe.usable,
            version=ffmpeg.version,
            path=ffmpeg.path,
            bundled=ffmpeg.source is ToolSource.BUNDLED,
        )


# --------------------------------------------------------- converting an info_dict


def build_media_info(url: str, raw: dict) -> MediaInfo:
    """`info_dict` -> `MediaInfo`. The raw dictionary never leaves this module."""
    if raw.get('_type') in ('playlist', 'multi_video'):
        entries = _playlist_entries(raw)
        return MediaInfo(
            url=url,
            title=raw.get('title') or 'Playlista',
            webpage_url=raw.get('webpage_url') or url,
            uploader=raw.get('uploader') or '',
            channel=raw.get('channel') or '',
            extractor=raw.get('extractor_key') or raw.get('extractor') or '',
            thumbnail_url=_pick_thumbnail(raw) or (entries[0].thumbnail_url if entries else ''),
            is_playlist=True,
            playlist_title=raw.get('title') or '',
            entries=tuple(entries),
        )

    return MediaInfo(
        url=url,
        title=raw.get('title') or raw.get('id') or url,
        webpage_url=raw.get('webpage_url') or raw.get('original_url') or url,
        media_id=str(raw.get('id') or ''),
        uploader=raw.get('uploader') or raw.get('uploader_id') or '',
        channel=raw.get('channel') or '',
        duration=raw.get('duration'),
        thumbnail_url=_pick_thumbnail(raw),
        extractor=raw.get('extractor_key') or raw.get('extractor') or '',
        live=bool(raw.get('is_live')),
        formats=parse_formats(raw.get('formats')),
        subtitles=_subtitle_tracks(raw),
    )


def _playlist_entries(raw: dict) -> list[PlaylistEntry]:
    entries: list[PlaylistEntry] = []
    for index, entry in enumerate(raw.get('entries') or [], start=1):
        if not isinstance(entry, dict):
            continue
        # Nested playlists (e.g. a channel with tabs) are flattened one level
        if entry.get('_type') in ('playlist', 'multi_video'):
            entries.extend(_playlist_entries(entry))
            continue
        entry_url = entry.get('webpage_url') or entry.get('url') or ''
        if not entry_url:
            continue
        entries.append(PlaylistEntry(
            url=entry_url,
            title=entry.get('title') or entry_url,
            index=entry.get('playlist_index') or index,
            duration=entry.get('duration'),
            thumbnail_url=_pick_thumbnail(entry),
            uploader=entry.get('uploader') or entry.get('channel') or '',
        ))
    return entries


def _pick_thumbnail(raw: dict) -> str:
    """A medium-sized thumbnail; full 4K covers only slow the UI down."""
    if raw.get('thumbnail'):
        return raw['thumbnail']
    urls = [t.get('url') for t in (raw.get('thumbnails') or []) if isinstance(t, dict) and t.get('url')]
    if not urls:
        return ''
    return urls[min(len(urls) - 1, max(0, len(urls) // 2))]


def _subtitle_tracks(raw: dict) -> tuple[SubtitleTrack, ...]:
    """The subtitles genuinely offered in `subtitles` and `automatic_captions`."""
    tracks: list[SubtitleTrack] = []
    for language, variants in (raw.get('subtitles') or {}).items():
        if language == 'live_chat':
            continue
        tracks.append(SubtitleTrack(language, _subtitle_name(variants, language), automatic=False))

    manual = {t.language for t in tracks}
    for language, variants in (raw.get('automatic_captions') or {}).items():
        if language in manual or '-' in language:
            # Machine-translated variants ('en-pl') only clutter the list
            continue
        tracks.append(SubtitleTrack(language, _subtitle_name(variants, language), automatic=True))

    tracks.sort(key=lambda t: (t.automatic, t.language))
    return tuple(tracks)


def _subtitle_name(variants, language: str) -> str:
    for variant in variants or []:
        if isinstance(variant, dict) and variant.get('name'):
            return variant['name']
    return language


def _resolve_redirects(ydl, url: str, max_depth: int = 5) -> dict | None:
    """Follow `url_result` hand-offs without processing what they point at.

    Some extractors only redirect: `youtu.be/<id>?list=<list>` yields a plain
    `_type: 'url'` pointing at the tab extractor. Passing that to
    `process_ie_result` would eagerly enumerate the entire playlist, which for
    a mix means paging until the server refuses. Each hop is resolved with
    `process=False` so a playlist still arrives as a lazy generator.
    """
    raw = ydl.extract_info(url, download=False, process=False)
    depth = 0
    while raw and raw.get('_type') in ('url', 'url_transparent') and depth < max_depth:
        depth += 1
        raw = ydl.extract_info(raw['url'], download=False, process=False,
                               ie_key=raw.get('ie_key'))
    return raw


def build_playlist_info(url: str, raw: dict) -> MediaInfo:
    """Stream the playlist entries and record whether they could all be read.

    Iterating the generator can break part-way (e.g. HTTP 403 on a further API
    page). The entries collected so far are kept and `entries_complete=False`
    is set, so the GUI never claims to know the full list.
    """
    entries: list[PlaylistEntry] = []
    playlist_url = raw.get('webpage_url') or url
    complete = True
    error = ''

    try:
        for entry in _iter_entries(raw.get('entries')):
            if len(entries) >= MAX_PLAYLIST_ITEMS:
                complete = False
                error = f'Wczytano pierwsze {MAX_PLAYLIST_ITEMS} pozycji playlisty.'
                break
            parsed = _playlist_entry(entry, len(entries) + 1, playlist_url)
            if parsed is not None:
                entries.append(parsed)
    except Exception as exc:  # noqa: BLE001 - a partial list beats no list at all
        complete = False
        error = normalize_error(str(exc))

    return MediaInfo(
        url=url,
        title=raw.get('title') or url,
        webpage_url=raw.get('webpage_url') or url,
        media_id=str(raw.get('id') or ''),
        uploader=raw.get('uploader') or '',
        channel=raw.get('channel') or '',
        extractor=raw.get('extractor_key') or raw.get('extractor') or '',
        thumbnail_url=_pick_thumbnail(raw) or (entries[0].thumbnail_url if entries else ''),
        is_playlist=True,
        playlist_title=raw.get('title') or '',
        entries=tuple(entries),
        entries_complete=complete,
        entries_error=error,
    )


def _iter_entries(entries, depth: int = 0):
    """Flatten nested playlists (e.g. a channel with tabs) without materialising."""
    if entries is None or depth > 2:
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get('_type') in ('playlist', 'multi_video'):
            yield from _iter_entries(entry.get('entries'), depth + 1)
        else:
            yield entry


def _playlist_entry(entry: dict, index: int, playlist_url: str = '') -> PlaylistEntry | None:
    entry_url = entry.get('webpage_url') or entry.get('url') or ''
    if not entry_url:
        return None
    extractor = entry.get('ie_key') or entry.get('extractor_key') or ''
    media_id = str(entry.get('id') or '')
    return PlaylistEntry(
        url=entry_url,
        title=entry.get('title') or entry_url,
        index=entry.get('playlist_index') or index,
        duration=entry.get('duration'),
        thumbnail_url=_pick_thumbnail(entry),
        uploader=entry.get('uploader') or entry.get('channel') or '',
        media_id=media_id,
        extractor=extractor,
        canonical_url=canonical_media_url(entry_url, extractor=extractor, media_id=media_id),
        playlist_url=playlist_url,
    )


def build_result(info: dict | None, errors: ErrorLog, completed_ids: set[str],
                 *, fatal: bool = False) -> DownloadResult:
    """Assemble a `DownloadResult` from `extract_info`, the hooks and the errors."""
    files: list[str] = []
    completed = len(completed_ids)
    failed = 0
    total: int | None = None

    if info and info.get('_type') in ('playlist', 'multi_video'):
        processed = info.get('entries') or []
        done = [entry for entry in processed if entry]
        failed = sum(1 for entry in processed if not entry)
        completed = max(completed, len(done))
        files = [path for path in (final_filepath(entry) for entry in done) if path]
        # With lazy_playlist the full item count is usually unknown
        total = info.get('playlist_count')
    elif info:
        path = final_filepath(info)
        if path:
            files = [path]
        completed = max(completed, 1 if path or completed_ids else 0)
        total = 1

    enumeration_complete = not errors.enumeration_failed
    if not enumeration_complete:
        total = None

    return DownloadResult.classify(
        completed=completed,
        failed=failed,
        total=total,
        enumeration_complete=enumeration_complete,
        fatal=fatal,
        errors=tuple(errors.items),
        enumeration_errors=tuple(errors.enumeration),
        output_files=tuple(files),
    )


def final_filepath(info: dict | None) -> str:
    """The file path after every postprocessor (merging, audio conversion, ...)."""
    if not info:
        return ''
    downloads = info.get('requested_downloads') or []
    if downloads:
        return downloads[0].get('filepath') or downloads[0].get('_filename') or ''
    return info.get('filepath') or info.get('_filename') or ''


def _parse_rate(value: str) -> int | None:
    value = (value or '').strip()
    if not value:
        return None
    try:
        from yt_dlp.utils import parse_bytes
    except ImportError:
        return None
    try:
        return parse_bytes(value) or None
    except (TypeError, ValueError):
        return None
