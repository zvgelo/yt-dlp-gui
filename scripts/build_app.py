#!/usr/bin/env python3
"""Freeze the application with PyInstaller.

The step both platforms share: compile the translations, fetch the pinned
helper binaries, record what went into the build, then run PyInstaller against
`packaging/yt-dlp-gui.spec`. The platform scripts wrap this and turn the result
into an AppImage or a ZIP.

    python scripts/build_app.py
    python scripts/build_app.py --skip-runtime-deps      # reuse what is there
    python scripts/build_app.py --output build/frozen

The result is a one-directory bundle, not a single file: the bundled ffmpeg and
deno stay real files for the lifetime of the process, start-up does not unpack
anything, and antivirus heuristics treat a plain directory far more kindly.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SPEC = ROOT / 'packaging' / 'yt-dlp-gui.spec'
BUILD_DIR = ROOT / 'build'
BUILD_INFO = ROOT / 'app' / '_build_info.py'


def log(message: str) -> None:
    print(f'[build] {message}', flush=True)


def fail(message: str) -> None:
    raise SystemExit(f'[build] error: {message}')


def app_version() -> str:
    from app import __version__

    return __version__


def git_commit() -> str:
    """The commit this build came from.

    A container build runs as root over a bind mount, where git refuses to
    answer because of its dubious-ownership check, so the host passes the
    commit in instead of the build losing it.
    """
    from_environment = os.environ.get('YTDLP_GUI_COMMIT', '').strip()
    if from_environment:
        return from_environment
    try:
        completed = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True,
            text=True, check=False)
    except OSError:
        return ''
    return completed.stdout.strip()


def git_is_dirty() -> bool:
    """Whether the working tree has uncommitted changes.

    `YTDLP_GUI_TREE_STATE` lets a container build inherit the answer from the
    host, where git can actually read the repository; inside the container the
    bind mount trips git's dubious-ownership check.
    """
    inherited = os.environ.get('YTDLP_GUI_TREE_STATE', '').strip()
    if inherited:
        return inherited != 'clean'
    try:
        completed = subprocess.run(
            ['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True,
            text=True, check=False)
    except OSError:
        return False
    return bool(completed.stdout.strip())


def package_version(name: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return ''


def require_tool(module: str, hint: str) -> None:
    try:
        __import__(module)
    except ImportError:
        fail(f'{module} is not installed.\n  {hint}')


def build_translations() -> None:
    """Compile the .qm catalogues the bundle ships."""
    log('compiling translations')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'build_translations.py')],
                            cwd=ROOT, check=False)
    if result.returncode != 0:
        fail('translation compilation failed')
    catalogues = sorted((ROOT / 'translations').glob('*.qm'))
    if not catalogues:
        fail('no .qm catalogues were produced')
    for path in catalogues:
        log(f'  {path.name}')


def runtime_dependencies(platform_name: str, skip: bool) -> Path:
    """Make sure the pinned ffmpeg/ffprobe/deno are unpacked and executable."""
    output = BUILD_DIR / f'runtime-{platform_name}'
    if skip:
        log(f'reusing runtime binaries in {output}')
    else:
        log('fetching pinned runtime binaries')
        from scripts.runtime_deps import provision

        provision(platform_name, output, BUILD_DIR / 'runtime-cache')

    suffix = '.exe' if platform_name == 'windows' else ''
    for name in ('ffmpeg', 'ffprobe', 'deno'):
        binary = output / f'{name}{suffix}'
        if not binary.is_file():
            fail(f'{binary} is missing; run scripts/runtime_deps.py')
        if platform_name != 'windows' and not os.access(binary, os.X_OK):
            fail(f'{binary} is not executable')
    log(f'runtime binaries ready in {output}')
    return output


def write_build_info(runtime_dir: Path, platform_name: str) -> dict:
    """Record what this build is made of, for diagnostics and the manifest.

    Written into the package as `app/_build_info.py` so the frozen application
    can report it, and removed again once PyInstaller has run.
    """
    from scripts.runtime_deps import versions as pinned_versions

    pins = pinned_versions()
    info = {
        'commit': git_commit(),
        'built_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'build_platform': platform_name,
        'build_python': platform.python_version(),
        # Recorded here rather than when the manifest is written: a container
        # build has a different libc from the host that starts it, and the
        # container's is the one the artifact is linked against
        'build_libc': ' '.join(platform.libc_ver()).strip() or 'n/a',
        'pyside6': package_version('PySide6'),
        'yt_dlp': package_version('yt-dlp'),
        'pyinstaller': package_version('pyinstaller'),
        'ffmpeg': pins['ffmpeg'],
        'deno': pins['deno'],
        # Set by the container build; empty for a build straight on the host
        'container_image': os.environ.get('YTDLP_GUI_BUILD_IMAGE', ''),
        'container_image_id': os.environ.get('YTDLP_GUI_BUILD_IMAGE_ID', ''),
        'tree_state': os.environ.get('YTDLP_GUI_TREE_STATE', '')
        or ('dirty' if git_is_dirty() else 'clean'),
    }
    lines = ['"""Written by scripts/build_app.py; absent in a source checkout."""', '']
    lines += [f'{key} = {value!r}' for key, value in info.items()]
    BUILD_INFO.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    log(f'build info: commit {info["commit"] or "unknown"}, yt-dlp {info["yt_dlp"]}')
    return info


def run_pyinstaller(runtime_dir: Path, output: Path, version_file: Path | None) -> Path:
    log('running PyInstaller')
    environment = dict(os.environ)
    environment['YTDLP_GUI_RUNTIME_DIR'] = str(runtime_dir)
    if version_file is not None:
        environment['YTDLP_GUI_WIN_VERSION_FILE'] = str(version_file)

    command = [
        sys.executable, '-m', 'PyInstaller', str(SPEC), '--noconfirm', '--clean',
        '--distpath', str(output), '--workpath', str(BUILD_DIR / 'pyinstaller'),
    ]
    result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if result.returncode != 0:
        fail('PyInstaller failed')

    bundle = output / 'yt-dlp-gui'
    if not bundle.is_dir():
        fail(f'expected bundle at {bundle}')
    return bundle


def verify_bundle(bundle: Path, platform_name: str) -> None:
    """Catch the mistakes that only show up on someone else's machine."""
    suffix = '.exe' if platform_name == 'windows' else ''
    executable = bundle / f'yt-dlp-gui{suffix}'
    if not executable.is_file():
        fail(f'{executable} is missing')
    if platform_name != 'windows' and not os.access(executable, os.X_OK):
        fail(f'{executable} is not executable')

    internal = bundle / '_internal'
    required = [
        internal / 'assets' / 'styles' / 'main.qss',
        internal / 'assets' / 'icons' / 'app_logo.svg',
        internal / 'translations' / 'yt_dlp_gui_pl.qm',
        internal / 'translations' / 'yt_dlp_gui_en.qm',
        internal / 'runtime' / f'ffmpeg{suffix}',
        internal / 'runtime' / f'ffprobe{suffix}',
        internal / 'runtime' / f'deno{suffix}',
    ]
    for path in required:
        if not path.exists():
            fail(f'the bundle is missing {path.relative_to(bundle)}')

    if platform_name != 'windows':
        for name in ('ffmpeg', 'ffprobe', 'deno'):
            binary = internal / 'runtime' / name
            if not os.access(binary, os.X_OK):
                fail(f'{binary.relative_to(bundle)} lost its executable bit')

    # A release must never carry the developer's yt-dlp checkout, the tests, or
    # the helper binaries a source checkout fetched for itself
    from app.resources import DEV_RUNTIME_DIR_NAME

    for unwanted in ('tests', 'mockup', '.git', DEV_RUNTIME_DIR_NAME):
        if (internal / unwanted).exists() or (bundle / unwanted).exists():
            fail(f'the bundle unexpectedly contains {unwanted}')

    log(f'bundle verified: {bundle}')


def bundle_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob('*') if item.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=BUILD_DIR / 'frozen',
                        help='where the one-directory bundle is written')
    parser.add_argument('--skip-runtime-deps', action='store_true',
                        help='reuse already downloaded ffmpeg/ffprobe/deno')
    parser.add_argument('--windows-version-file', type=Path,
                        help='PyInstaller version resource for the Windows executable')
    parser.add_argument('--allow-dirty', action='store_true',
                        help='build even though the working tree has changes')
    args = parser.parse_args(argv)

    require_tool('PyInstaller', 'install it with: pip install "pyinstaller>=6.16"')
    require_tool('PySide6', 'install the application dependencies first')
    require_tool('yt_dlp', 'install the application dependencies first')

    if git_is_dirty() and not args.allow_dirty:
        fail('the working tree has uncommitted changes.\n'
             '  commit them, or pass --allow-dirty for a development build')

    platform_name = 'windows' if os.name == 'nt' else 'linux'
    log(f'yt-dlp GUI {app_version()} for {platform_name}')

    build_translations()
    runtime_dir = runtime_dependencies(platform_name, args.skip_runtime_deps)
    info = write_build_info(runtime_dir, platform_name)
    try:
        bundle = run_pyinstaller(runtime_dir, args.output, args.windows_version_file)
    finally:
        BUILD_INFO.unlink(missing_ok=True)

    verify_bundle(bundle, platform_name)
    size = bundle_size(bundle)
    log(f'bundle size: {size / 1024 / 1024:.0f} MB')

    summary = {'version': app_version(), 'bundle': str(bundle), 'size_bytes': size, **info}
    (args.output / 'build-summary.json').write_text(
        json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
