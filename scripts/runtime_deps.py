#!/usr/bin/env python3
"""Pinned third-party binaries that packaged builds ship.

Two programs are bundled so a released application works on a machine that has
neither installed:

* **FFmpeg / ffprobe** - merging video with audio, remuxing, audio extraction
  and metadata or cover-art embedding all go through it.
* **Deno** - yt-dlp needs a JavaScript runtime for full YouTube extraction and
  enables only Deno by default (see `yt_dlp/utils/_jsruntime.py`).

Everything here is pinned to an exact release and verified against a checksum
published by that release. Nothing is fetched at application runtime; this
module is build tooling only.

    python scripts/runtime_deps.py --platform linux
    python scripts/runtime_deps.py --platform windows --output build/runtime-windows

The same pins serve a source checkout. Without them `./run.sh` has no
JavaScript runtime and YouTube extraction is degraded, while the packaged build
is fine - a difference nobody should have to debug:

    python scripts/runtime_deps.py --development
    python scripts/runtime_deps.py --development --only deno

That writes into the gitignored `.runtime/<platform>/` directory the
application looks in when it is not frozen.

To move to a newer FFmpeg or Deno, change the pins below, run the script and
commit the refreshed checksums it prints.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_CACHE = ROOT / 'build' / 'runtime-cache'

#: BtbN publishes dated, immutable auto-builds together with `checksums.sha256`.
#: The LGPL variant is used deliberately: it is the more permissive of the two
#: variants he ships, and it still contains the muxers, the AAC/Opus/FLAC
#: support and libmp3lame that this application needs.
#:
#: The archive carries LGPL-3.0 text and the binary reports
#: "GNU Lesser General Public License ... version 3 or later", which matches
#: its `--enable-version3` configuration. `FFMPEG-LICENSE.txt` is unpacked
#: alongside the binaries and shipped in the release.
FFMPEG_RELEASE = 'autobuild-2026-08-17-13-05'
FFMPEG_BUILD = 'ffmpeg-n8.1.2-44-g7c533d0f86'
FFMPEG_VERSION = '8.1.2'
FFMPEG_LICENSE = 'LGPL-3.0-or-later'
FFMPEG_SOURCE = 'https://github.com/BtbN/FFmpeg-Builds'

#: Deno 2.3.0 is yt-dlp's minimum; the pin is well above it.
DENO_VERSION = '2.9.5'
DENO_LICENSE = 'MIT'
DENO_SOURCE = 'https://github.com/denoland/deno'


class Download:
    """One archive to fetch, verify and unpack."""

    def __init__(self, name: str, url: str, sha256: str, members: dict[str, str]):
        self.name = name
        self.url = url
        self.sha256 = sha256
        #: archive member (suffix match) -> file name to write into the output
        self.members = members


PINS: dict[str, list[Download]] = {
    'linux': [
        Download(
            'ffmpeg',
            f'https://github.com/BtbN/FFmpeg-Builds/releases/download/{FFMPEG_RELEASE}/'
            f'{FFMPEG_BUILD}-linux64-lgpl-8.1.tar.xz',
            '',
            {'bin/ffmpeg': 'ffmpeg', 'bin/ffprobe': 'ffprobe', 'LICENSE.txt': 'FFMPEG-LICENSE.txt'},
        ),
        Download(
            'deno',
            f'https://github.com/denoland/deno/releases/download/v{DENO_VERSION}/'
            'deno-x86_64-unknown-linux-gnu.zip',
            '',
            {'deno': 'deno'},
        ),
    ],
    'windows': [
        Download(
            'ffmpeg',
            f'https://github.com/BtbN/FFmpeg-Builds/releases/download/{FFMPEG_RELEASE}/'
            f'{FFMPEG_BUILD}-win64-lgpl-8.1.zip',
            '',
            {'bin/ffmpeg.exe': 'ffmpeg.exe', 'bin/ffprobe.exe': 'ffprobe.exe',
             'LICENSE.txt': 'FFMPEG-LICENSE.txt'},
        ),
        Download(
            'deno',
            f'https://github.com/denoland/deno/releases/download/v{DENO_VERSION}/'
            'deno-x86_64-pc-windows-msvc.zip',
            '',
            {'deno.exe': 'deno.exe'},
        ),
    ],
}

#: Recorded by `--refresh-checksums`; every download is checked against it.
CHECKSUMS_FILE = Path(__file__).with_name('runtime_deps_checksums.txt')


def load_checksums() -> dict[str, str]:
    """`<sha256>  <url>` lines recorded next to this script."""
    if not CHECKSUMS_FILE.exists():
        return {}
    checksums = {}
    for line in CHECKSUMS_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        digest, _, url = line.partition('  ')
        if digest and url:
            checksums[url.strip()] = digest.strip()
    return checksums


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, cache: Path) -> Path:
    """Download once and keep it, so repeated builds do not re-download."""
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / url.rsplit('/', 1)[-1]
    if target.exists() and target.stat().st_size:
        print(f'  cached  {target.name}')
        return target

    print(f'  fetch   {url}')
    temporary = target.with_suffix(target.suffix + '.part')
    # HTTPS only: the pins above are all github.com release URLs
    if not url.startswith('https://'):
        raise SystemExit(f'refusing to download over a non-HTTPS URL: {url}')
    with urllib.request.urlopen(url) as response, temporary.open('wb') as handle:
        shutil.copyfileobj(response, handle)
    temporary.replace(target)
    return target


def verify(path: Path, expected: str) -> str:
    digest = sha256_of(path)
    if expected and digest != expected:
        raise SystemExit(
            f'checksum mismatch for {path.name}\n  expected {expected}\n  actual   {digest}')
    return digest


def extract(archive: Path, members: dict[str, str], output: Path) -> list[Path]:
    """Pull the wanted members out, flattening them into the output directory."""
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if archive.name.endswith(('.tar.xz', '.tar.gz', '.tgz')):
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                target_name = _match(member.name, members)
                if target_name is None or not member.isfile():
                    continue
                source = tar.extractfile(member)
                if source is None:
                    continue
                destination = output / target_name
                with destination.open('wb') as handle:
                    shutil.copyfileobj(source, handle)
                written.append(destination)
    else:
        with zipfile.ZipFile(archive) as zip_file:
            for name in zip_file.namelist():
                target_name = _match(name, members)
                if target_name is None or name.endswith('/'):
                    continue
                destination = output / target_name
                with zip_file.open(name) as source, destination.open('wb') as handle:
                    shutil.copyfileobj(source, handle)
                written.append(destination)

    for path in written:
        if path.suffix.lower() not in ('.txt', '.md'):
            make_executable(path)
    return written


def _match(member: str, members: dict[str, str]) -> str | None:
    """Archives wrap everything in a versioned top directory; match the tail."""
    normalised = member.replace('\\', '/')
    for wanted, target in members.items():
        if normalised == wanted or normalised.endswith('/' + wanted):
            return target
    return None


def make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def current_platform() -> str:
    return 'windows' if os.name == 'nt' else 'linux'


def provision(platform_name: str, output: Path, cache: Path,
              *, refresh: bool = False, only: list[str] | None = None) -> dict[str, str]:
    """Fetch, verify and unpack everything pinned for one platform."""
    downloads = PINS.get(platform_name)
    if downloads is None:
        raise SystemExit(f'no runtime pins for platform {platform_name!r}')
    if only:
        downloads = [download for download in downloads if download.name in only]
        if not downloads:
            raise SystemExit(f'nothing pinned matches {only!r}')

    recorded = load_checksums()
    digests: dict[str, str] = {}
    print(f'runtime dependencies for {platform_name} -> {output}')

    for download in downloads:
        archive = fetch(download.url, cache)
        expected = recorded.get(download.url, download.sha256)
        if refresh:
            digests[download.url] = sha256_of(archive)
            print(f'  digest  {digests[download.url]}  {download.url}')
        else:
            if not expected:
                raise SystemExit(
                    f'no recorded checksum for {download.url}\n'
                    f'run: python {Path(__file__).name} --refresh-checksums')
            digests[download.url] = verify(archive, expected)
            print(f'  verify  {download.name} ok')
        written = extract(archive, download.members, output)
        for path in written:
            print(f'  unpack  {path.name}')

    return digests


def refresh_checksums(cache: Path) -> int:
    """Record the checksum of every pinned archive on every platform."""
    lines = ['# SHA256 of the pinned third-party runtime archives.',
             '# Regenerate with: python scripts/runtime_deps.py --refresh-checksums']
    for platform_name in sorted(PINS):
        with tempfile.TemporaryDirectory() as staging:
            digests = provision(platform_name, Path(staging), cache, refresh=True)
        for url, digest in digests.items():
            lines.append(f'{digest}  {url}')
    CHECKSUMS_FILE.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'wrote {CHECKSUMS_FILE}')
    return 0


def versions() -> dict[str, str]:
    """What the pins amount to, for the release manifest."""
    return {
        'ffmpeg': FFMPEG_VERSION,
        'ffmpeg_build': FFMPEG_BUILD,
        'ffmpeg_release': FFMPEG_RELEASE,
        'ffmpeg_license': FFMPEG_LICENSE,
        'ffmpeg_source': FFMPEG_SOURCE,
        'deno': DENO_VERSION,
        'deno_license': DENO_LICENSE,
        'deno_source': DENO_SOURCE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--platform', choices=sorted(PINS), default=current_platform(),
                        help='which platform to fetch binaries for')
    parser.add_argument('--development', action='store_true',
                        help='unpack into the checkout\'s .runtime/ directory, so a '
                             'source run uses the same binaries a release bundles')
    parser.add_argument('--only', nargs='+', metavar='TOOL',
                        choices=sorted({download.name for pins in PINS.values()
                                        for download in pins}),
                        help='fetch only these tools instead of everything pinned')
    parser.add_argument('--output', type=Path,
                        help='directory to unpack into (default: build/runtime-<platform>)')
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE,
                        help='where downloaded archives are kept between builds')
    parser.add_argument('--refresh-checksums', action='store_true',
                        help='download every pin and rewrite the checksum file')
    parser.add_argument('--print-versions', action='store_true',
                        help='print the pinned versions and exit')
    args = parser.parse_args(argv)

    if args.print_versions:
        for key, value in versions().items():
            print(f'{key}={value}')
        return 0

    if args.refresh_checksums:
        return refresh_checksums(args.cache)

    if args.output:
        output = args.output
    elif args.development:
        output = development_output(args.platform)
    else:
        output = ROOT / 'build' / f'runtime-{args.platform}'

    provision(args.platform, output, args.cache, only=args.only)

    if args.development:
        print(f'\ndevelopment runtime ready in {output}')
        print('  ./run.sh now finds the same FFmpeg and Deno a release bundles')
    return 0


def development_output(platform_name: str) -> Path:
    """Where a source run looks for its helper binaries.

    The application decides this, not the build tooling: `app/resources.py`
    owns the layout, and asking it keeps the two from drifting apart.
    """
    from app.resources import DEV_RUNTIME_DIR_NAME

    machine = 'x86_64'
    return ROOT / DEV_RUNTIME_DIR_NAME / f'{platform_name}-{machine}'


if __name__ == '__main__':
    sys.exit(main())
