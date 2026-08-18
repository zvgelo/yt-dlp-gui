#!/usr/bin/env python3
"""Prove the bundled helper binaries are really used, not merely present.

`--version` on a binary says nothing about whether yt-dlp reaches for it. This
script drives the application's own `YtDlpService` with the runtime directory a
packaged build ships and checks what actually happened:

* the JS runtime - yt-dlp warns loudly when it cannot find one, so the absence
  of that warning plus the resolved path is the evidence,
* FFmpeg - an audio extraction produces an MP3 that only a working FFmpeg can
  have written.

    python scripts/integration_check.py --runtime build/runtime-linux
    python scripts/integration_check.py --runtime build/runtime-linux --skip-download

It needs network access and downloads one short public video, so it is not part
of the unit test suite.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: A short, public, Creative Commons clip; small enough to fetch in seconds
DEFAULT_URL = 'https://www.youtube.com/watch?v=NPmRmfodJmk'

WARNING_NO_JS = 'No supported JavaScript runtime'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--runtime', type=Path,
                        help='directory holding the bundled ffmpeg/ffprobe/deno')
    parser.add_argument('--url', default=DEFAULT_URL, help='media to analyse and download')
    parser.add_argument('--skip-download', action='store_true',
                        help='only analyse; do not fetch any media')
    args = parser.parse_args(argv)

    if args.runtime:
        # `resources.runtime_dir()` is what RuntimeTools consults
        import app.resources as resources

        target = args.runtime.resolve()
        resources.runtime_dir = lambda: target  # type: ignore[assignment]
        import app.core.runtime_tools as runtime_tools

        runtime_tools.runtime_dir = lambda: target  # type: ignore[assignment]

    from app.core.diagnostics import collect, describe_tool
    from app.core.models import DownloadRequest, MediaKind
    from app.core.runtime_tools import RuntimeTools, ToolSource
    from app.core.ytdlp_service import DownloadCallbacks, Logger, YtDlpService
    from app.settings import AppSettings

    tools = RuntimeTools()
    print('resolved tools')
    for name, info in tools.summary().items():
        print(f'  {name + ":":9} {describe_tool(info)}')

    failures: list[str] = []
    if args.runtime:
        for name, info in tools.summary().items():
            if info.source is not ToolSource.BUNDLED:
                failures.append(f'{name} resolved to {info.source.value}, not the bundled copy')

    diagnostics = collect(tools)
    print(f'\nyt-dlp {diagnostics.yt_dlp_version} from {diagnostics.yt_dlp_location}')

    with tempfile.TemporaryDirectory() as staging:
        settings = AppSettings(output_dir=staging, kind=MediaKind.AUDIO.value,
                               audio_format='mp3', embed_thumbnail=False,
                               embed_metadata=False, embed_chapters=False)
        service = YtDlpService(settings, tools)

        options = service.base_options()
        print('\noptions handed to yt-dlp')
        print(f'  ffmpeg_location: {options.get("ffmpeg_location", "(none)")}')
        print(f'  js_runtimes:     {options.get("js_runtimes", "(none)")}')
        if 'js_runtimes' not in options:
            failures.append('yt-dlp was not told about a JavaScript runtime')
        if 'ffmpeg_location' not in options:
            failures.append('yt-dlp was not told where FFmpeg is')

        messages: list[str] = []
        logger = Logger(lambda level, message: messages.append(f'{level}: {message}'))

        print(f'\nanalysing {args.url}')
        info = service.extract(args.url, logger)
        print(f'  title:   {info.title}')
        print(f'  formats: {len(info.formats)}')
        if not info.formats:
            failures.append('the analysis returned no formats')

        js_warnings = [line for line in messages if WARNING_NO_JS in line]
        if js_warnings:
            failures.append('yt-dlp still reports no JavaScript runtime')
            print(f'  !! {js_warnings[0][:120]}')
        else:
            print('  no "missing JavaScript runtime" warning was emitted')

        if args.skip_download:
            return _report(failures)

        print('\ndownloading and extracting audio')
        request = DownloadRequest(url=info.webpage_url or args.url, output_dir=staging,
                                  kind=MediaKind.AUDIO, audio_format='mp3',
                                  embed_thumbnail=False, embed_metadata=False,
                                  embed_chapters=False)
        result = service.download(request, DownloadCallbacks(), logger)
        print(f'  status: {result.status.value}')

        produced = sorted(Path(staging).rglob('*.mp3'))
        for path in produced:
            print(f'  wrote:  {path.name} ({path.stat().st_size} bytes)')
        if not produced:
            failures.append('no MP3 was produced, so FFmpeg did not run')
        elif produced[0].stat().st_size < 10_000:
            failures.append('the MP3 is suspiciously small')
        else:
            with produced[0].open('rb') as handle:
                head = handle.read(4)
            if not (head.startswith(b'ID3') or head[:2] == b'\xff\xfb'):
                failures.append('the produced file does not look like an MP3')
            else:
                print('  the file carries an MP3 header')

    return _report(failures)


def _report(failures: list[str]) -> int:
    print()
    if failures:
        print('FAILED')
        for failure in failures:
            print(f'  - {failure}')
        return 1
    print('all integration checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
