"""Where the application finds the files it ships with.

Running from a source checkout and running from a frozen bundle put the assets
in different places, and that difference is confined to this module. Everything
else asks for `styles_dir()`, `icons_dir()` or `translations_dir()` and never
looks at `sys._MEIPASS` or `__file__` itself.

Read-only application resources live here. Writable user data - the history
database, settings, caches - belongs in `app/paths.py` and never next to the
executable, because an AppImage is mounted read-only at a path that changes on
every launch.
"""

from __future__ import annotations

import functools
import os
import platform
import sys
from pathlib import Path

#: Directory holding the bundled helper binaries (ffmpeg, ffprobe, deno)
RUNTIME_DIR_NAME = 'runtime'

#: Where a source checkout keeps the same helper binaries a release bundles.
#: Populated by `scripts/runtime_deps.py --development`, never committed.
DEV_RUNTIME_DIR_NAME = '.runtime'


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than the sources."""
    return bool(getattr(sys, 'frozen', False)) and hasattr(sys, '_MEIPASS')


@functools.cache
def resource_root() -> Path:
    """The directory the shipped resources are rooted at.

    Frozen: the bundle directory PyInstaller unpacks or points at. From source:
    the repository root, two levels above this file.
    """
    if is_frozen():
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parents[1]


def resource_path(*parts: str) -> Path:
    """A path inside the shipped resources, wherever they happen to live."""
    return resource_root().joinpath(*parts)


def assets_dir() -> Path:
    return resource_path('assets')


def icons_dir() -> Path:
    return resource_path('assets', 'icons')


def styles_dir() -> Path:
    return resource_path('assets', 'styles')


def translations_dir() -> Path:
    return resource_path('translations')


def runtime_dir() -> Path:
    """Where bundled helper binaries live, if this build ships any."""
    return resource_path(RUNTIME_DIR_NAME)


def license_file() -> Path | None:
    """The application's own licence text, if this build ships it.

    A release bundles it so the About box can show it without a network
    connection; a source checkout reads the file at the repository root.
    """
    path = resource_path('LICENSE')
    return path if path.is_file() else None


def platform_tag() -> str:
    """`linux-x86_64` or `windows-x86_64`: what a downloaded binary was built for."""
    system = 'windows' if os.name == 'nt' else 'linux'
    machine = platform.machine().lower() or 'unknown'
    if machine in ('amd64', 'x64'):
        machine = 'x86_64'
    return f'{system}-{machine}'


def dev_runtime_dir() -> Path | None:
    """The repository-local helper binaries used when running from source.

    A release bundles ffmpeg and deno; a source checkout has nothing, which
    left `./run.sh` without a JavaScript runtime and YouTube extraction
    degraded. The same fetcher fills this directory with the same pinned
    versions, so development and release behave alike.

    None when frozen: a packaged build must never look outside its bundle,
    least of all at a developer's checkout.
    """
    if is_frozen():
        return None
    return resource_root() / DEV_RUNTIME_DIR_NAME / platform_tag()


def executable_dir() -> Path:
    """The directory the running program was started from.

    Useful for diagnostics only. Never derive storage from it: an AppImage
    mounts somewhere under /tmp and a Windows install may be read-only.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else Path.cwd()


def exe_suffix() -> str:
    """`.exe` on Windows, nothing elsewhere."""
    return '.exe' if os.name == 'nt' else ''
