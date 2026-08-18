"""Checks a packaged artifact can run on itself, with no display and no Python.

A release is a single opaque file. `--version` proves it starts; these prove it
works: that HTTPS reaches YouTube with certificates that verify, that a watch
link carrying playlist context is still one video, that a playlist still
enumerates, and that the bundled FFmpeg really produces a file.

They exist for `scripts/validate_appimage.sh`, which runs them inside a
container that has no Python, no FFmpeg and no Deno. Deliberately not a
download CLI: no options beyond a URL and a destination, and every message is
plain English for a build log rather than translated interface text.
"""

from __future__ import annotations

import ssl
import sys
from pathlib import Path


def _report(label: str, value: object) -> None:
    print(f'{label + ":":22} {value}')


def certificate_source() -> str:
    """Where HTTPS verification gets its trusted roots from.

    A frozen build must not fall back to a path that only exists on the
    machine it was built on, so this is worth stating explicitly.
    """
    paths = ssl.get_default_verify_paths()
    try:
        import certifi

        bundled = certifi.where()
    except Exception:  # noqa: BLE001 - a missing certifi is itself the answer
        bundled = ''

    if bundled and Path(bundled).is_file():
        return f'certifi ({bundled})'
    if paths.cafile and Path(paths.cafile).is_file():
        return f'system ({paths.cafile})'
    if paths.capath and Path(paths.capath).is_dir():
        return f'system ({paths.capath})'
    return 'none found'


def check_url(url: str, verbose: bool = False) -> int:
    """Analyse one address exactly as the interface would.

    Covers in one pass: real HTTPS with certificate verification, the URL
    intent classification, and - for a playlist - that children come out as
    canonical single-media URLs.
    """
    from .core.diagnostics import describe_tool
    from .core.runtime_tools import RuntimeTools
    from .core.urls import classify_url, normalize_url
    from .core.ytdlp_service import Logger, YtDlpService
    from .settings import AppSettings

    tools = RuntimeTools()
    _report('deno', describe_tool(tools.deno))
    _report('certificates', certificate_source())

    intent = classify_url(url)
    _report('url', url)
    _report('intent', intent.name)
    _report('canonical', normalize_url(url, intent))

    messages: list[str] = []
    service = YtDlpService(AppSettings(output_dir='/tmp'), tools)
    _report('js_runtimes', service.base_options().get('js_runtimes') or 'not configured')

    try:
        info = service.extract(url, Logger(lambda level, text: messages.append(f'{level}: {text}')))
    except Exception as exc:  # noqa: BLE001 - the reason is the result
        print(f'FAILED: {exc.__class__.__name__}: {exc}', file=sys.stderr)
        _dump(messages, limit=40)
        return 1

    if verbose:
        print('--- what yt-dlp said ---')
        for text in messages:
            print(f'  {text}')
        print('--- end ---')

    _report('title', info.title)
    _report('is_playlist', info.is_playlist)

    problems: list[str] = []
    if info.is_playlist:
        _report('entries', len(info.entries))
        _report('enumeration', 'complete' if info.entries_complete else 'partial')
        if not info.entries:
            problems.append('the playlist produced no entries')
        for entry in info.entries[:5]:
            if 'list=' in entry.download_url:
                problems.append(f'a child kept its playlist context: {entry.download_url}')
        if info.entries:
            _report('first child', info.entries[0].download_url)
    else:
        _report('formats', len(info.formats))
        if len(info.formats) < 2:
            problems.append(f'only {len(info.formats)} format(s) were offered, '
                            'which usually means the JavaScript runtime was not used')

    for text in messages:
        if 'No supported JavaScript runtime' in text:
            problems.append('yt-dlp reported that it has no JavaScript runtime')
        if 'Only images are available' in text:
            problems.append('yt-dlp could only offer images')

    if problems:
        for problem in problems:
            print(f'FAILED: {problem}', file=sys.stderr)
        return 1

    print('OK')
    return 0


def check_download(url: str, output: str) -> int:
    """Run both workflows that need FFmpeg, and check what came out.

    Audio extraction proves the converter works; a merged download proves the
    muxer does, because YouTube serves high-quality video and audio as separate
    streams that only FFmpeg can join. A `Download completed` line is not
    evidence - ffprobe reading the result is.
    """
    from .core.diagnostics import describe_tool
    from .core.models import DownloadRequest, MediaKind
    from .core.runtime_tools import RuntimeTools
    from .core.ytdlp_service import YtDlpService
    from .settings import AppSettings

    destination = Path(output).expanduser()
    destination.mkdir(parents=True, exist_ok=True)

    tools = RuntimeTools()
    _report('ffmpeg', describe_tool(tools.ffmpeg))
    _report('ffprobe', describe_tool(tools.ffprobe))

    settings = AppSettings(output_dir=str(destination), kind=MediaKind.AUDIO.value,
                           audio_format='mp3', embed_thumbnail=False,
                           embed_metadata=False, embed_chapters=False)
    service = YtDlpService(settings, tools)
    _report('ffmpeg_location', service.base_options().get('ffmpeg_location') or 'not configured')

    request = DownloadRequest(url=url, output_dir=str(destination), kind=MediaKind.AUDIO,
                              audio_format='mp3', embed_thumbnail=False,
                              embed_metadata=False, embed_chapters=False)
    # YouTube sometimes withholds formats for a moment; that is an upstream
    # hiccup, not a broken build, so one retry is allowed - and both the reason
    # and the retry are printed rather than swallowed.
    produced: list[Path] = []
    for attempt in (1, 2):
        produced, messages = _attempt(service, request, destination, attempt)
        if produced:
            break
        print(f'attempt {attempt} produced no audio; what yt-dlp said:', file=sys.stderr)
        _dump(messages)

    if not produced:
        print('FAILED: no MP3 was produced after two attempts.', file=sys.stderr)
        print('       An HTTP 403 above is YouTube refusing the media, not a broken',
              file=sys.stderr)
        print('       build; analysis passing while the download is refused points',
              file=sys.stderr)
        print('       upstream. Anything else is worth investigating here.', file=sys.stderr)
        return 1

    path = produced[0]
    size = path.stat().st_size
    _report('file', path.name)
    _report('size', f'{size} bytes')
    if size < 10_000:
        print('FAILED: the produced file is too small to be real audio', file=sys.stderr)
        return 1

    with path.open('rb') as handle:
        head = handle.read(3)
    if not (head == b'ID3' or head[:2] == b'\xff\xfb'):
        print('FAILED: the produced file has no MP3 header', file=sys.stderr)
        return 1
    _report('header', 'MP3')

    # ffprobe is the bundled binary, so this also proves it works
    probed = _probe(tools.ffprobe.path, path)
    _report('ffprobe says', probed or 'nothing')
    if 'mp3' not in probed.lower():
        print('FAILED: ffprobe does not recognise the file as MP3', file=sys.stderr)
        return 1

    return _check_merge(service, tools, url, destination / 'video')


def _check_merge(service, tools, url: str, destination: Path) -> int:
    """Download video and audio and let FFmpeg mux them into one file."""
    from .core.models import DownloadRequest, MediaKind

    destination.mkdir(parents=True, exist_ok=True)
    print()
    _report('merge test', 'video + audio into MKV')

    request = DownloadRequest(url=url, output_dir=str(destination), kind=MediaKind.VIDEO,
                              container='mkv', quality=480, embed_thumbnail=False,
                              embed_metadata=False, embed_chapters=False)
    produced: list[Path] = []
    for attempt in (1, 2):
        produced, messages = _attempt(service, request, destination, attempt, '*.mkv')
        if produced:
            break
        print(f'attempt {attempt} produced no video; what yt-dlp said:', file=sys.stderr)
        _dump(messages)

    if not produced:
        print('FAILED: no merged file was produced', file=sys.stderr)
        return 1

    path = produced[0]
    _report('file', path.name)
    _report('size', f'{path.stat().st_size} bytes')
    if path.stat().st_size < 100_000:
        print('FAILED: the merged file is too small to hold video', file=sys.stderr)
        return 1

    streams = _probe_streams(tools.ffprobe.path, path)
    _report('streams', streams or 'none')
    if 'video' not in streams or 'audio' not in streams:
        print('FAILED: the merged file does not carry both a video and an audio stream',
              file=sys.stderr)
        return 1

    print('OK')
    return 0


def _attempt(service, request, destination: Path, attempt: int,
             pattern: str = '*.mp3') -> tuple[list[Path], list[str]]:
    """One download, together with everything yt-dlp said about it."""
    from .core.ytdlp_service import DownloadCallbacks, Logger

    messages: list[str] = []
    try:
        result = service.download(
            request, DownloadCallbacks(),
            Logger(lambda level, text: messages.append(f'{level}: {text}')))
        _report('status', result.status.value)
    except Exception as exc:  # noqa: BLE001 - the reason is the result
        print(f'attempt {attempt} raised {exc.__class__.__name__}: {exc}', file=sys.stderr)
    return sorted(destination.rglob(pattern)), messages


def _dump(messages: list[str], limit: int = 12) -> None:
    """What yt-dlp said, so a failing validation run explains itself."""
    interesting = [text for text in messages if not text.startswith('INFO')] or messages
    for text in interesting[-limit:]:
        print(f'  {text}', file=sys.stderr)


def _probe_streams(ffprobe: str, path: Path) -> str:
    """The stream kinds inside a container, as ffprobe sees them."""
    import subprocess

    if not ffprobe:
        return ''
    try:
        completed = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'stream=codec_type',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ''
    return ', '.join(sorted(set(completed.stdout.split())))


def _probe(ffprobe: str, path: Path) -> str:
    import subprocess

    if not ffprobe:
        return ''
    try:
        completed = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'format=format_name,duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ''
    return ' '.join(completed.stdout.split())
