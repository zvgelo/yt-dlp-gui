"""What this build is made of, for the About box, the log and bug reports.

Everything here is derived from the running program - the bundled yt-dlp, the
resolved helper binaries, the interpreter - never from parsing yt-dlp's log
output. Probing happens once and is cached, so the report is cheap to ask for
again.
"""

from __future__ import annotations

import dataclasses
import platform
import sys

from .. import APP_NAME, APP_TITLE, __version__
from ..resources import is_frozen
from .runtime_tools import RuntimeTools, ToolInfo, ToolSource, ToolState, default_tools


def yt_dlp_version() -> str:
    """The version of the yt-dlp package this build actually imports."""
    try:
        from yt_dlp.version import __version__ as version
    except Exception:  # noqa: BLE001 - diagnostics must never be the thing that fails
        return ''
    return str(version)


def yt_dlp_location() -> str:
    """Where that package was imported from, which is what catches shadowing."""
    try:
        import yt_dlp
    except Exception:  # noqa: BLE001
        return ''
    return str(getattr(yt_dlp, '__file__', '') or '')


def pyside_version() -> str:
    try:
        import PySide6
    except Exception:  # noqa: BLE001
        return ''
    return str(PySide6.__version__)


def qt_version() -> str:
    try:
        from PySide6.QtCore import qVersion
    except Exception:  # noqa: BLE001
        return ''
    return str(qVersion())


def build_metadata() -> dict[str, str]:
    """Details written at build time, if this is a packaged build.

    The build scripts drop an `app/_build_info.py` into the bundle. A source
    checkout has no such file and simply reports nothing.
    """
    try:
        from .. import _build_info
    except ImportError:
        return {}
    return {key: str(value) for key, value in vars(_build_info).items()
            if not key.startswith('_')}


@dataclasses.dataclass(frozen=True)
class Diagnostics:
    """A snapshot of the application and everything it depends on."""

    app_version: str
    app_name: str
    frozen: bool
    python_version: str
    platform_name: str
    architecture: str
    pyside_version: str
    qt_version: str
    yt_dlp_version: str
    yt_dlp_location: str
    tools: dict[str, ToolInfo]
    build: dict[str, str]

    @property
    def ffmpeg(self) -> ToolInfo:
        return self.tools['ffmpeg']

    @property
    def ffprobe(self) -> ToolInfo:
        return self.tools['ffprobe']

    @property
    def js_runtime(self) -> ToolInfo:
        return self.tools['deno']

    def as_dict(self) -> dict:
        data = {
            'app': {'name': self.app_name, 'version': self.app_version,
                    'frozen': self.frozen},
            'runtime': {'python': self.python_version, 'pyside6': self.pyside_version,
                        'qt': self.qt_version, 'platform': self.platform_name,
                        'architecture': self.architecture},
            'yt_dlp': {'version': self.yt_dlp_version, 'location': self.yt_dlp_location},
            'tools': {name: {'state': info.state.value, 'source': info.source.value,
                             'version': info.version, 'path': info.path}
                      for name, info in self.tools.items()},
        }
        if self.build:
            data['build'] = self.build
        return data

    def as_text(self) -> str:
        """A block a user can paste into a bug report."""
        lines = [
            f'{APP_TITLE} {self.app_version}'
            + (' (packaged build)' if self.frozen else ' (from source)'),
            f'Platform:  {self.platform_name} ({self.architecture})',
            f'Python:    {self.python_version}',
            f'PySide6:   {self.pyside_version} (Qt {self.qt_version})',
            f'yt-dlp:    {self.yt_dlp_version or "not available"}',
        ]
        for name in ('ffmpeg', 'ffprobe', 'deno'):
            lines.append(f'{name + ":":10} {describe_tool(self.tools[name])}')
        for key, value in self.build.items():
            lines.append(f'{key + ":":10} {value}')
        return '\n'.join(lines)


def describe_tool(info: ToolInfo) -> str:
    """`8.1.2 - bundled` or the reason there is no version to show.

    Deliberately untranslated: this string goes into logs and bug reports.
    """
    if info.state is ToolState.MISSING:
        return 'not found'
    source = {ToolSource.BUNDLED: 'bundled',
              ToolSource.DEVELOPMENT: 'development runtime',
              ToolSource.CONFIGURED: 'configured',
              ToolSource.SYSTEM: 'system',
              ToolSource.NONE: ''}[info.source]
    if info.state is ToolState.INVALID:
        return f'found but unusable ({info.path})'
    suffix = ' - too old for yt-dlp' if info.state is ToolState.UNSUPPORTED else ''
    return f'{info.version} - {source}{suffix} ({info.path})'


def collect(tools: RuntimeTools | None = None) -> Diagnostics:
    """Gather everything worth reporting. Cheap after the first call."""
    resolved = tools if tools is not None else default_tools()
    return Diagnostics(
        app_version=__version__,
        app_name=APP_NAME,
        frozen=is_frozen(),
        python_version=sys.version.split()[0],
        platform_name=platform.platform(),
        architecture=platform.machine(),
        pyside_version=pyside_version(),
        qt_version=qt_version(),
        yt_dlp_version=yt_dlp_version(),
        yt_dlp_location=yt_dlp_location(),
        tools=resolved.summary(),
        build=build_metadata(),
    )
