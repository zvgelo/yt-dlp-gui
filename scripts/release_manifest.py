#!/usr/bin/env python3
"""Describe a set of release artifacts: what they are and what is inside them.

Written next to the artifacts so a download can be traced back to the commit
and the dependency versions it was built from, months later, without guessing.

    python scripts/release_manifest.py --platform linux
    python scripts/release_manifest.py --platform windows --dist dist/windows

Produces `release-manifest.json` and `SHA256SUMS.txt`. No absolute developer
paths and no secrets go into either file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: Extensions that count as a release artifact rather than a by-product
ARTIFACT_SUFFIXES = ('.AppImage', '.zip', '.exe')


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        completed = subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                                   text=True, check=False)
    except OSError:
        return ''
    return completed.stdout.strip()


def build_summary(build_dir: Path) -> dict:
    """What `scripts/build_app.py` recorded about the freeze, if it ran here."""
    summary = build_dir / 'build-summary.json'
    if not summary.is_file():
        return {}
    try:
        return json.loads(summary.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def collect(dist: Path, platform_name: str, build_dir: Path) -> dict:
    from app import __version__
    from scripts.runtime_deps import versions as pinned_versions

    summary = build_summary(build_dir)
    pins = pinned_versions()

    artifacts = []
    for path in sorted(dist.iterdir()):
        if path.is_file() and path.suffix in ARTIFACT_SUFFIXES:
            artifacts.append({
                'name': path.name,
                'size_bytes': path.stat().st_size,
                'sha256': sha256_of(path),
            })

    return {
        'app': 'yt-dlp-gui',
        'version': __version__,
        'platform': platform_name,
        'architecture': 'x86_64',
        'built_at': summary.get('built_at')
        or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'git': {
            'commit': summary.get('commit') or git_value('rev-parse', 'HEAD')[:12],
            'describe': git_value('describe', '--tags', '--always', '--dirty'),
            # Whether the tree had uncommitted changes when this was built
            'tree_state': summary.get('tree_state', ''),
        },
        'build_environment': {
            'python': summary.get('build_python') or platform.python_version(),
            'system': platform.system(),
            'libc': summary.get('build_libc')
            or ' '.join(platform.libc_ver()).strip() or 'n/a',
            'container_image': summary.get('container_image', ''),
            'container_image_id': summary.get('container_image_id', ''),
            'appimagetool': os.environ.get('YTDLP_GUI_APPIMAGETOOL', ''),
        },
        'bundled': {
            'yt_dlp': summary.get('yt_dlp', ''),
            'pyside6': summary.get('pyside6', ''),
            'pyinstaller': summary.get('pyinstaller', ''),
            'ffmpeg': pins['ffmpeg'],
            'ffmpeg_build': pins['ffmpeg_build'],
            'ffmpeg_license': pins['ffmpeg_license'],
            'deno': pins['deno'],
            'deno_license': pins['deno_license'],
        },
        'artifacts': artifacts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--platform', choices=('linux', 'windows'),
                        default='windows' if sys.platform == 'win32' else 'linux')
    parser.add_argument('--dist', type=Path, help='directory holding the artifacts')
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build' / 'frozen',
                        help='where build-summary.json was written')
    args = parser.parse_args(argv)

    dist = args.dist or ROOT / 'dist' / args.platform
    if not dist.is_dir():
        raise SystemExit(f'no artifacts directory at {dist}')

    manifest = collect(dist, args.platform, args.build_dir)
    if not manifest['artifacts']:
        raise SystemExit(f'no release artifacts found in {dist}')

    manifest_path = dist / 'release-manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')

    sums_path = dist / 'SHA256SUMS.txt'
    sums_path.write_text(
        ''.join(f'{item["sha256"]}  {item["name"]}\n' for item in manifest['artifacts']),
        encoding='utf-8')

    print(f'yt-dlp-gui {manifest["version"]} ({args.platform})')
    print(f'  commit   {manifest["git"]["commit"]}')
    print(f'  yt-dlp   {manifest["bundled"]["yt_dlp"]}')
    print(f'  ffmpeg   {manifest["bundled"]["ffmpeg"]}')
    print(f'  deno     {manifest["bundled"]["deno"]}')
    for item in manifest['artifacts']:
        print(f'  {item["name"]}  {item["size_bytes"] / 1024 / 1024:.0f} MB')
        print(f'    sha256 {item["sha256"]}')
    print(f'  wrote {manifest_path.name} and {sums_path.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
