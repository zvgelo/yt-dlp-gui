"""Finding the helper binaries the application drives: FFmpeg and a JS runtime.

One resolution order, used by every caller:

1. the copy bundled with this build,
2. the repository-local copy a source checkout fetched,
3. a path the user configured in preferences,
4. whatever is on `PATH`,
5. nothing - the feature degrades and says so.

Steps 1 and 2 never both apply: a frozen build has a bundle and no checkout, a
source run has a checkout and no bundle. Together they mean the same pinned
FFmpeg and Deno are used whether the application was started by `./run.sh` or
by double-clicking an AppImage.

A pinned binary wins over the system on purpose. A release ships versions
tested against the yt-dlp it also ships; an older FFmpeg or a Deno below
yt-dlp's minimum sitting earlier in `PATH` would silently change behaviour.

The layer knows nothing about Qt. Version probes run the binary once and the
answer is cached, so nothing here is called repeatedly from a paint handler.
"""

from __future__ import annotations

import dataclasses
import enum
import functools
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ..resources import dev_runtime_dir, exe_suffix, runtime_dir

#: yt-dlp refuses to use an older Deno; see `yt_dlp/utils/_jsruntime.py`
MIN_DENO_VERSION = (2, 3, 0)

#: How long a `--version` probe may take before it is treated as unavailable
PROBE_TIMEOUT = 10


class ToolState(enum.Enum):
    """What is known about a helper binary."""

    AVAILABLE = 'available'
    MISSING = 'missing'
    #: Found, but it could not be run or did not answer as expected
    INVALID = 'invalid'
    #: Found and runnable, but older than the version yt-dlp requires
    UNSUPPORTED = 'unsupported'


class ToolSource(enum.Enum):
    """Which of the search steps produced the binary."""

    #: Shipped inside a packaged build
    BUNDLED = 'bundled'
    #: Fetched into the checkout by `scripts/runtime_deps.py --development`
    DEVELOPMENT = 'development'
    #: An explicit path from preferences
    CONFIGURED = 'configured'
    #: Found on PATH
    SYSTEM = 'system'
    NONE = 'none'


@dataclasses.dataclass(frozen=True)
class ToolInfo:
    """A resolved helper binary, or the reason there is not one."""

    name: str
    state: ToolState = ToolState.MISSING
    source: ToolSource = ToolSource.NONE
    path: str = ''
    version: str = ''

    @property
    def available(self) -> bool:
        return self.state is ToolState.AVAILABLE

    @property
    def usable(self) -> bool:
        """Runnable at all, even if older than we would like."""
        return self.state in (ToolState.AVAILABLE, ToolState.UNSUPPORTED)


def _no_window() -> dict:
    """Keep helper binaries from flashing a console window on Windows."""
    if os.name != 'nt':
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {'startupinfo': startupinfo,
            'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}


def _run_version(path: str, argument: str = '-version') -> str:
    """First line of the binary's version output, or an empty string."""
    try:
        # The path comes from our own resolver, never from user text
        completed = subprocess.run(
            [path, argument], capture_output=True, text=True, timeout=PROBE_TIMEOUT,
            check=False, **_no_window())
    except (OSError, subprocess.SubprocessError):
        return ''
    output = (completed.stdout or completed.stderr or '').strip()
    return output.splitlines()[0] if output else ''


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


class RuntimeTools:
    """Resolves the helper binaries once and remembers the answer.

    `configured` holds explicit paths from the preferences, keyed by tool name;
    an empty value means the user has not set one.
    """

    def __init__(self, configured: dict[str, str] | None = None):
        self._configured = {name: (value or '').strip()
                            for name, value in (configured or {}).items()}

    # ------------------------------------------------------------- lookup

    def bundled_path(self, name: str) -> Path | None:
        """The copy shipped with this build, if there is one."""
        candidate = runtime_dir() / f'{name}{exe_suffix()}'
        return candidate if _executable(candidate) else None

    def development_path(self, name: str) -> Path | None:
        """The copy a source checkout fetched, if the developer ran the bootstrap."""
        directory = dev_runtime_dir()
        if directory is None:
            return None
        candidate = directory / f'{name}{exe_suffix()}'
        return candidate if _executable(candidate) else None

    def configured_path(self, name: str) -> Path | None:
        """An explicit path from preferences, which may name a directory."""
        raw = self._configured.get(name, '')
        if not raw:
            return None
        path = Path(raw).expanduser()
        if path.is_dir():
            path = path / f'{name}{exe_suffix()}'
        return path if _executable(path) else None

    def system_path(self, name: str) -> Path | None:
        found = shutil.which(name)
        return Path(found) if found else None

    def locate(self, name: str) -> tuple[Path | None, ToolSource]:
        """Walk the resolution order and report which step answered."""
        for finder, source in ((self.bundled_path, ToolSource.BUNDLED),
                               (self.development_path, ToolSource.DEVELOPMENT),
                               (self.configured_path, ToolSource.CONFIGURED),
                               (self.system_path, ToolSource.SYSTEM)):
            path = finder(name)
            if path is not None:
                return path, source
        return None, ToolSource.NONE

    # -------------------------------------------------------------- tools

    @functools.cached_property
    def ffmpeg(self) -> ToolInfo:
        return self._probe_ffmpeg('ffmpeg')

    @functools.cached_property
    def ffprobe(self) -> ToolInfo:
        return self._probe_ffmpeg('ffprobe')

    @functools.cached_property
    def deno(self) -> ToolInfo:
        path, source = self.locate('deno')
        if path is None:
            return ToolInfo('deno')

        output = _run_version(str(path), '--version')
        match = re.search(r'deno\s+(\S+)', output)
        if not match:
            return ToolInfo('deno', ToolState.INVALID, source, str(path))

        version = match.group(1)
        state = (ToolState.AVAILABLE if _version_tuple(version) >= MIN_DENO_VERSION
                 else ToolState.UNSUPPORTED)
        return ToolInfo('deno', state, source, str(path), version)

    def _probe_ffmpeg(self, name: str) -> ToolInfo:
        path, source = self.locate(name)
        if path is None:
            return ToolInfo(name)

        output = _run_version(str(path), '-version')
        match = re.search(rf'{name} version (\S+)', output)
        if not match:
            return ToolInfo(name, ToolState.INVALID, source, str(path))
        return ToolInfo(name, ToolState.AVAILABLE, source, str(path), match.group(1))

    # ------------------------------------------------- yt-dlp integration

    @property
    def ffmpeg_location(self) -> str:
        """Value for the yt-dlp `ffmpeg_location` option.

        yt-dlp accepts a directory or a binary path; the directory is handed
        over so it picks up ffprobe from the same place.
        """
        if not self.ffmpeg.usable:
            return ''
        return str(Path(self.ffmpeg.path).parent)

    @property
    def js_runtimes(self) -> dict[str, dict[str, str]]:
        """Value for the yt-dlp `js_runtimes` option.

        The shape comes from `YoutubeDL`'s documented parameter:
        `{'deno': {'path': '/path/to/deno'}}`. Without an explicit path yt-dlp
        searches `PATH` itself, which is exactly what a packaged build must not
        depend on.
        """
        if not self.deno.usable:
            return {}
        return {'deno': {'path': self.deno.path}}

    def summary(self) -> dict[str, ToolInfo]:
        return {'ffmpeg': self.ffmpeg, 'ffprobe': self.ffprobe, 'deno': self.deno}


def _version_tuple(version: str) -> tuple[int, ...]:
    """`'2.5.3'` -> `(2, 5, 3)`, ignoring anything that is not a number."""
    parts = []
    for chunk in re.split(r'[.\-+]', version):
        digits = re.match(r'\d+', chunk)
        if digits is None:
            break
        parts.append(int(digits.group()))
    return tuple(parts) or (0,)


@functools.cache
def _default_tools() -> RuntimeTools:
    return RuntimeTools()


def default_tools() -> RuntimeTools:
    """Shared instance for callers with no preferences to hand over."""
    return _default_tools()


def python_version() -> str:
    return sys.version.split()[0]
