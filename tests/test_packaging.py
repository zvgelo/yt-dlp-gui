"""Resource paths, runtime tool resolution and release metadata.

The packaging layer is the part of the application that behaves differently
depending on how it was started, which is exactly the part that is easiest to
get wrong and hardest to notice: a path that works from a source checkout and
breaks in a bundle only fails on someone else's machine.

Real binaries are never executed here. The tools are mocked, because a unit
test cannot rely on FFmpeg or Deno being installed - and the point is the
resolution order, not the programs themselves.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from app import APP_NAME, APP_TITLE, ORG_NAME, __version__, resources
from app.core import runtime_tools
from app.core.diagnostics import collect, describe_tool
from app.core.runtime_tools import RuntimeTools, ToolSource, ToolState
from app.core.ytdlp_service import YtDlpService
from app.settings import AppSettings

ROOT = Path(__file__).resolve().parents[1]


def _fake_tool(directory: Path, name: str, output: str) -> Path:
    """An executable that prints a version banner, standing in for the real one."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f'#!/bin/sh\necho "{output}"\n', encoding='utf-8')
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


FFMPEG_BANNER = 'ffmpeg version 8.1.2 Copyright (c) 2000-2026 the FFmpeg developers'
FFPROBE_BANNER = 'ffprobe version 8.1.2 Copyright (c) 2007-2026 the FFmpeg developers'
DENO_BANNER = 'deno 2.9.5 (stable, release, x86_64-unknown-linux-gnu)'

pytestmark = pytest.mark.skipif(
    os.name == 'nt', reason='the fake tools are shell scripts, which Windows cannot run')


@pytest.fixture(autouse=True)
def isolated_tools(tmp_path, monkeypatch):
    """Start every test with no helper binaries anywhere.

    Otherwise the result would depend on whether the developer running the
    suite has bootstrapped `.runtime/` or has FFmpeg installed, and each test
    would be testing the machine instead of the resolution order.
    """
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'no-bundle')
    monkeypatch.setattr(runtime_tools, 'dev_runtime_dir', lambda: tmp_path / 'no-dev')
    monkeypatch.setenv('PATH', str(tmp_path / 'empty-path'))


# ------------------------------------------------------------ resource paths


def test_source_mode_finds_the_shipped_resources():
    """`./run.sh` has to keep working after all the packaging changes."""
    assert not resources.is_frozen()
    assert resources.resource_root() == ROOT
    assert (resources.styles_dir() / 'main.qss').is_file()
    assert (resources.icons_dir() / 'app_logo.svg').is_file()
    assert sorted(resources.translations_dir().glob('*.qm'))


def test_frozen_mode_reads_from_the_bundle(tmp_path, monkeypatch):
    """PyInstaller unpacks somewhere new on every run; nothing may assume a path."""
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    resources.resource_root.cache_clear()

    assert resources.is_frozen()
    assert resources.resource_root() == tmp_path.resolve()
    assert resources.styles_dir() == tmp_path.resolve() / 'assets' / 'styles'
    assert resources.runtime_dir() == tmp_path.resolve() / 'runtime'

    resources.resource_root.cache_clear()


def test_only_one_module_knows_about_the_bundle():
    """`sys._MEIPASS` checks scattered around the code are how bundles rot."""
    offenders = []
    for path in sorted((ROOT / 'app').rglob('*.py')):
        if path.name == 'resources.py':
            continue
        text = path.read_text(encoding='utf-8')
        if '_MEIPASS' in text or re.search(r"getattr\(sys,\s*['\"]frozen", text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_user_data_never_lives_next_to_the_executable():
    """An AppImage mounts read-only at a new path each launch."""
    from app.logs import log_dir
    from app.paths import app_data_dir, history_path

    data = app_data_dir()
    assert history_path().parent == data
    assert log_dir().parent == data
    assert resources.resource_root() not in data.parents
    assert data != resources.resource_root()


# -------------------------------------------------------- tool resolution order


def test_a_bundled_tool_wins_over_the_system_one(tmp_path, monkeypatch):
    """A release ships versions tested against the yt-dlp it also ships."""
    bundled = tmp_path / 'runtime'
    _fake_tool(bundled, 'ffmpeg', FFMPEG_BANNER)
    system = tmp_path / 'system'
    _fake_tool(system, 'ffmpeg', 'ffmpeg version 4.2.7 old')

    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: bundled)
    monkeypatch.setenv('PATH', str(system))

    info = RuntimeTools().ffmpeg
    assert info.source is ToolSource.BUNDLED
    assert info.version == '8.1.2'
    assert info.path == str(bundled / 'ffmpeg')


def test_a_configured_path_wins_over_the_system_one(tmp_path, monkeypatch):
    configured = tmp_path / 'chosen'
    _fake_tool(configured, 'ffmpeg', FFMPEG_BANNER)
    system = tmp_path / 'system'
    _fake_tool(system, 'ffmpeg', 'ffmpeg version 4.2.7 old')

    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setenv('PATH', str(system))

    info = RuntimeTools({'ffmpeg': str(configured)}).ffmpeg
    assert info.source is ToolSource.CONFIGURED
    assert info.version == '8.1.2'


def test_a_configured_directory_or_binary_both_work(tmp_path, monkeypatch):
    configured = tmp_path / 'chosen'
    binary = _fake_tool(configured, 'ffmpeg', FFMPEG_BANNER)
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setenv('PATH', '')

    assert RuntimeTools({'ffmpeg': str(configured)}).ffmpeg.available
    assert RuntimeTools({'ffmpeg': str(binary)}).ffmpeg.available


def test_the_system_tool_is_the_last_resort(tmp_path, monkeypatch):
    system = tmp_path / 'system'
    _fake_tool(system, 'ffmpeg', FFMPEG_BANNER)
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setenv('PATH', str(system))

    info = RuntimeTools().ffmpeg
    assert info.source is ToolSource.SYSTEM
    assert info.available


def test_a_missing_tool_is_reported_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))

    tools = RuntimeTools()
    assert tools.ffmpeg.state is ToolState.MISSING
    assert tools.deno.state is ToolState.MISSING
    assert tools.ffmpeg_location == ''
    assert tools.js_runtimes == {}
    assert describe_tool(tools.ffmpeg) == 'not found'


def test_a_tool_that_cannot_be_run_is_invalid(tmp_path, monkeypatch):
    """Present but broken is a different state from absent."""
    bundled = tmp_path / 'runtime'
    _fake_tool(bundled, 'ffmpeg', 'this is not a version banner')
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: bundled)
    monkeypatch.setenv('PATH', '')

    assert RuntimeTools().ffmpeg.state is ToolState.INVALID


def test_a_deno_below_the_minimum_is_unsupported(tmp_path, monkeypatch):
    """yt-dlp refuses anything older than 2.3.0."""
    bundled = tmp_path / 'runtime'
    _fake_tool(bundled, 'deno', 'deno 2.1.0 (stable, release)')
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: bundled)
    monkeypatch.setenv('PATH', '')

    info = RuntimeTools().deno
    assert info.state is ToolState.UNSUPPORTED
    assert info.version == '2.1.0'
    assert 'too old' in describe_tool(info)


# ---------------------------------------------------------- handing over to yt-dlp


def test_yt_dlp_is_told_where_the_tools_are(tmp_path, monkeypatch):
    """A packaged build must not depend on what the machine has on PATH."""
    bundled = tmp_path / 'runtime'
    _fake_tool(bundled, 'ffmpeg', FFMPEG_BANNER)
    _fake_tool(bundled, 'ffprobe', FFPROBE_BANNER)
    _fake_tool(bundled, 'deno', DENO_BANNER)
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: bundled)
    monkeypatch.setenv('PATH', '')

    tools = RuntimeTools()
    options = YtDlpService(AppSettings(output_dir=str(tmp_path)), tools).base_options()

    # A directory, so yt-dlp finds ffprobe beside ffmpeg
    assert options['ffmpeg_location'] == str(bundled)
    # The shape documented on YoutubeDL: {'deno': {'path': ...}}
    assert options['js_runtimes'] == {'deno': {'path': str(bundled / 'deno')}}


def test_no_js_runtime_option_when_there_is_no_runtime(tmp_path, monkeypatch):
    """Passing an empty mapping would disable yt-dlp's own search."""
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setenv('PATH', '')

    options = YtDlpService(AppSettings(output_dir=str(tmp_path)), RuntimeTools()).base_options()
    assert 'js_runtimes' not in options
    assert 'ffmpeg_location' not in options


def test_the_service_reports_what_the_locator_found(tmp_path, monkeypatch):
    bundled = tmp_path / 'runtime'
    _fake_tool(bundled, 'ffmpeg', FFMPEG_BANNER)
    _fake_tool(bundled, 'ffprobe', FFPROBE_BANNER)
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: bundled)
    monkeypatch.setenv('PATH', '')

    status = YtDlpService(AppSettings(output_dir=str(tmp_path)), RuntimeTools()).ffmpeg_status()
    assert status.available and status.probe_available
    assert status.bundled
    assert status.version == '8.1.2'


def test_changing_the_configured_path_re_resolves(tmp_path, monkeypatch):
    """The probes are cached, so a new setting has to invalidate them."""
    first = tmp_path / 'first'
    _fake_tool(first, 'ffmpeg', FFMPEG_BANNER)
    second = tmp_path / 'second'
    _fake_tool(second, 'ffmpeg', 'ffmpeg version 7.0.1 other')
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setenv('PATH', '')

    settings = AppSettings(output_dir=str(tmp_path), ffmpeg_location=str(first))
    service = YtDlpService(settings)
    assert service.ffmpeg_status().version == '8.1.2'

    service.update_settings(settings.replace(ffmpeg_location=str(second)))
    assert service.ffmpeg_status().version == '7.0.1'


# -------------------------------------------------------------- diagnostics


def test_diagnostics_report_versions_and_sources(tmp_path, monkeypatch):
    bundled = tmp_path / 'runtime'
    _fake_tool(bundled, 'ffmpeg', FFMPEG_BANNER)
    _fake_tool(bundled, 'ffprobe', FFPROBE_BANNER)
    _fake_tool(bundled, 'deno', DENO_BANNER)
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: bundled)
    monkeypatch.setenv('PATH', '')

    report = collect(RuntimeTools())
    assert report.app_version == __version__
    assert report.yt_dlp_version
    assert report.pyside_version
    assert report.ffmpeg.source is ToolSource.BUNDLED
    assert report.js_runtime.version == '2.9.5'

    text = report.as_text()
    assert __version__ in text
    assert 'bundled' in text
    assert 'deno' in text

    data = report.as_dict()
    assert data['tools']['deno']['state'] == 'available'
    assert data['app']['version'] == __version__


def test_diagnostics_state_is_structural_not_scraped_text():
    """Dependency state comes from probing, never from yt-dlp's log output."""
    source = (ROOT / 'app' / 'core' / 'runtime_tools.py').read_text(encoding='utf-8')
    assert 'No supported JavaScript runtime' not in source


# ------------------------------------------------------------ version metadata


def test_the_version_has_one_source_of_truth():
    # tomllib arrived in 3.11; the application supports 3.10, and this check
    # is about a file, not about the interpreter running it
    tomllib = pytest.importorskip('tomllib')

    data = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    assert 'version' not in data['project'], 'the version must not be duplicated'
    assert data['project']['dynamic'] == ['version']
    assert data['tool']['hatch']['version']['path'] == 'app/__init__.py'


def test_the_version_looks_like_a_release():
    assert re.fullmatch(r'\d+\.\d+\.\d+(?:[.-]?(?:a|b|rc|dev)\d*)?', __version__), __version__


def test_the_application_identity_is_stable():
    """Changing these would strand the user's existing settings and history."""
    assert APP_NAME == 'yt-dlp-gui'
    assert ORG_NAME == 'yt-dlp-gui'
    assert APP_TITLE == 'yt-dlp GUI'


def test_the_command_line_reports_the_version():
    completed = subprocess.run(
        [sys.executable, str(ROOT / 'main.py'), '--version'],
        capture_output=True, text=True, check=False, cwd=ROOT,
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert completed.returncode == 0
    assert __version__ in completed.stdout


def test_the_command_line_reports_diagnostics():
    completed = subprocess.run(
        [sys.executable, str(ROOT / 'main.py'), '--diagnostics'],
        capture_output=True, text=True, check=False, cwd=ROOT,
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert completed.returncode == 0
    assert 'yt-dlp:' in completed.stdout
    assert 'ffmpeg:' in completed.stdout


# --------------------------------------------------------------- packaging files


def test_the_artifact_names_carry_the_version():
    build_script = (ROOT / 'scripts' / 'build_linux_appimage.sh').read_text(encoding='utf-8')
    assert 'yt-dlp-gui-${VERSION}-x86_64.AppImage' in build_script

    windows_script = (ROOT / 'scripts' / 'build_windows.ps1').read_text(encoding='utf-8')
    assert 'yt-dlp-gui-$Version-windows-x86_64.zip' in windows_script


def test_the_runtime_pins_are_exact_and_checksummed():
    from scripts.runtime_deps import PINS, load_checksums, versions

    recorded = load_checksums()
    assert recorded, 'no checksums have been recorded'
    for platform_name, downloads in PINS.items():
        for download in downloads:
            assert download.url.startswith('https://'), download.url
            assert 'latest' not in download.url, f'{platform_name}: unpinned download'
            assert download.url in recorded, f'{download.url} has no checksum'
            assert len(recorded[download.url]) == 64

    pinned = versions()
    assert re.fullmatch(r'\d+\.\d+(\.\d+)?', pinned['ffmpeg'])
    assert re.fullmatch(r'\d+\.\d+\.\d+', pinned['deno'])


def test_the_release_manifest_describes_the_artifacts(tmp_path):
    from scripts.release_manifest import collect as collect_manifest

    artifact = tmp_path / f'yt-dlp-gui-{__version__}-x86_64.AppImage'
    artifact.write_bytes(b'not really an AppImage')

    manifest = collect_manifest(tmp_path, 'linux', tmp_path / 'missing')
    assert manifest['version'] == __version__
    assert manifest['platform'] == 'linux'
    assert manifest['architecture'] == 'x86_64'
    assert manifest['bundled']['ffmpeg']
    assert manifest['bundled']['deno']

    entry = manifest['artifacts'][0]
    assert entry['name'] == artifact.name
    assert len(entry['sha256']) == 64
    assert entry['size_bytes'] == artifact.stat().st_size

    # It has to survive a round trip through JSON, and carry no local paths
    text = json.dumps(manifest)
    assert str(ROOT) not in text
    assert str(Path.home()) not in text


def test_the_spec_excludes_development_files():
    spec = (ROOT / 'packaging' / 'yt-dlp-gui.spec').read_text(encoding='utf-8')
    for unwanted in ('pytest', 'tkinter', 'setuptools'):
        assert unwanted in spec, f'{unwanted} should be excluded from the bundle'
    # onefile would unpack ffmpeg and deno to a temporary path on every start
    assert 'COLLECT(' in spec
    assert 'upx=False' in spec


def test_the_desktop_entry_is_complete():
    entry = (ROOT / 'packaging' / 'linux' / 'yt-dlp-gui.desktop').read_text(encoding='utf-8')
    for key in ('Type=Application', 'Name=', 'Exec=', 'Icon=', 'Terminal=false',
                'Categories=', 'Comment='):
        assert key in entry, f'the desktop entry is missing {key}'
    # Nothing is registered that the application does not actually handle
    assert 'MimeType=' not in entry


def test_the_icons_exist_at_the_sizes_the_desktop_wants():
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        assert (ROOT / 'assets' / 'icons' / 'app' / f'{size}.png').is_file()
    ico = ROOT / 'assets' / 'icons' / 'app.ico'
    assert ico.is_file()
    # A multi-resolution ICO starts with the reserved word, type 1 and a count
    header = ico.read_bytes()[:6]
    assert header[:4] == b'\x00\x00\x01\x00'
    assert int.from_bytes(header[4:6], 'little') >= 5


def test_the_build_scripts_carry_no_developer_paths():
    """A path to somebody's home makes a build reproducible only for them.

    The pattern needs a name after `/home/`: the scripts legitimately mention
    the bare prefix when they check an artifact for leaked build paths.
    """
    home_path = re.compile(r'/(?:home|Users)/[A-Za-z0-9._-]+/')
    for path in sorted((ROOT / 'scripts').iterdir()) + sorted((ROOT / 'packaging').rglob('*')):
        if not path.is_file() or path.suffix in ('.txt',):
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        found = home_path.search(text)
        assert found is None, f'{path.name} contains {found.group() if found else ""}'


# ------------------------------------------------- the development runtime


def test_a_source_checkout_looks_in_its_own_runtime_directory():
    """`./run.sh` had no JavaScript runtime while the AppImage had one."""
    directory = resources.dev_runtime_dir()
    assert directory is not None
    assert directory.parent.name == resources.DEV_RUNTIME_DIR_NAME
    assert directory.name == resources.platform_tag()
    assert directory.parent.parent == ROOT


def test_a_frozen_build_has_no_development_directory(tmp_path, monkeypatch):
    """A release must never reach into somebody's checkout."""
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    resources.resource_root.cache_clear()

    assert resources.dev_runtime_dir() is None

    resources.resource_root.cache_clear()


def test_the_platform_tag_names_what_a_binary_was_built_for():
    tag = resources.platform_tag()
    assert tag.startswith(('linux-', 'windows-'))
    assert 'amd64' not in tag, 'amd64 and x86_64 must not both appear'


def test_the_development_runtime_is_used_when_running_from_source(tmp_path, monkeypatch):
    development = tmp_path / 'dev'
    _fake_tool(development, 'deno', DENO_BANNER)
    system = tmp_path / 'system'
    _fake_tool(system, 'deno', 'deno 2.4.0 (stable, release)')

    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setattr(runtime_tools, 'dev_runtime_dir', lambda: development)
    monkeypatch.setenv('PATH', str(system))

    info = RuntimeTools().deno
    assert info.source is ToolSource.DEVELOPMENT
    assert info.version == '2.9.5'
    assert 'development runtime' in describe_tool(info)


def test_the_development_runtime_loses_to_a_bundled_one(tmp_path, monkeypatch):
    """Packaging must not pick up a checkout that happens to be lying around."""
    bundled = tmp_path / 'bundle'
    _fake_tool(bundled, 'deno', DENO_BANNER)
    development = tmp_path / 'dev'
    _fake_tool(development, 'deno', 'deno 2.4.0 (stable, release)')

    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: bundled)
    monkeypatch.setattr(runtime_tools, 'dev_runtime_dir', lambda: development)
    monkeypatch.setenv('PATH', '')

    info = RuntimeTools().deno
    assert info.source is ToolSource.BUNDLED
    assert info.version == '2.9.5'


def test_a_configured_path_loses_to_the_development_runtime(tmp_path, monkeypatch):
    """The fetched copy is the source-mode equivalent of a bundled one."""
    development = tmp_path / 'dev'
    _fake_tool(development, 'ffmpeg', FFMPEG_BANNER)
    configured = tmp_path / 'chosen'
    _fake_tool(configured, 'ffmpeg', 'ffmpeg version 7.0.1 other')

    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setattr(runtime_tools, 'dev_runtime_dir', lambda: development)
    monkeypatch.setenv('PATH', '')

    assert RuntimeTools({'ffmpeg': str(configured)}).ffmpeg.source is ToolSource.DEVELOPMENT


def test_a_configured_path_still_works_without_a_development_runtime(tmp_path, monkeypatch):
    configured = tmp_path / 'chosen'
    _fake_tool(configured, 'ffmpeg', FFMPEG_BANNER)
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setattr(runtime_tools, 'dev_runtime_dir', lambda: tmp_path / 'no-dev')
    monkeypatch.setenv('PATH', '')

    assert RuntimeTools({'ffmpeg': str(configured)}).ffmpeg.source is ToolSource.CONFIGURED


def test_path_is_still_the_last_resort_in_source_mode(tmp_path, monkeypatch):
    """A developer with Deno installed globally keeps working."""
    system = tmp_path / 'system'
    _fake_tool(system, 'deno', DENO_BANNER)
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setattr(runtime_tools, 'dev_runtime_dir', lambda: tmp_path / 'no-dev')
    monkeypatch.setenv('PATH', str(system))

    assert RuntimeTools().deno.source is ToolSource.SYSTEM


def test_nothing_anywhere_is_still_only_a_warning(tmp_path, monkeypatch):
    """A missing runtime degrades YouTube extraction; it does not fail a job."""
    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')
    monkeypatch.setattr(runtime_tools, 'dev_runtime_dir', lambda: tmp_path / 'no-dev')
    monkeypatch.setenv('PATH', '')

    tools = RuntimeTools()
    assert tools.deno.state is ToolState.MISSING
    assert tools.js_runtimes == {}
    # yt-dlp is simply not told about a runtime, and still runs
    options = YtDlpService(AppSettings(output_dir=str(tmp_path)), tools).base_options()
    assert 'js_runtimes' not in options


def test_the_development_runtime_gets_the_pinned_version(tmp_path, monkeypatch):
    """Source and release use the same Deno, from the same single pin."""
    from scripts.runtime_deps import development_output, versions

    monkeypatch.setattr(runtime_tools, 'runtime_dir', lambda: tmp_path / 'absent')

    output = development_output('linux')
    assert output.name.startswith('linux-')
    assert output.parent.name == resources.DEV_RUNTIME_DIR_NAME
    # One place decides the version; nothing repeats it
    assert versions()['deno'] == '2.9.5'


def test_the_development_runtime_is_not_packaged(tmp_path):
    """The spec ships build/runtime-<platform>, never a developer's checkout."""
    spec = (ROOT / 'packaging' / 'yt-dlp-gui.spec').read_text(encoding='utf-8')
    assert resources.DEV_RUNTIME_DIR_NAME not in spec
    assert 'YTDLP_GUI_RUNTIME_DIR' in spec


def test_the_development_runtime_is_gitignored():
    ignored = (ROOT / '.gitignore').read_text(encoding='utf-8')
    assert f'{resources.DEV_RUNTIME_DIR_NAME}/' in ignored


def test_run_sh_points_at_the_bootstrap_instead_of_downloading():
    """A hundreds-of-megabytes fetch must not hide inside every launch."""
    script = (ROOT / 'run.sh').read_text(encoding='utf-8')
    assert 'bootstrap_dev_runtime.sh' in script
    for downloader in ('curl', 'wget', 'runtime_deps.py'):
        assert downloader not in script, f'run.sh should not invoke {downloader}'


# ------------------------------------------------------- the release pipeline


def _script(name: str) -> str:
    return (ROOT / 'scripts' / name).read_text(encoding='utf-8')


def _code(name: str) -> str:
    """A shell script without its comments.

    The comments explain what the script deliberately avoids, so scanning them
    for those very words would flag the explanation instead of a mistake.
    """
    return '\n'.join(line for line in _script(name).splitlines()
                     if not line.lstrip().startswith('#'))


def _build_script() -> str:
    return _script('build_linux_appimage.sh')


def _container_script() -> str:
    return _script('build_linux_appimage_container.sh')


def test_the_manifest_is_written_after_the_artifact():
    """A manifest describing a previous build is worse than none at all."""
    script = _build_script()
    artifact_line = script.index('appimagetool')
    manifest_line = script.index('release_manifest.py')
    publish_line = script.index('mv "$STAGING_DIR" "$DIST_DIR"')
    assert artifact_line < manifest_line < publish_line


def test_the_release_directory_is_replaced_atomically():
    """A half-finished build must never look like the current release."""
    script = _build_script()
    assert 'STAGING_DIR=' in script
    assert 'rm -rf "$DIST_DIR"' in script
    assert 'mv "$STAGING_DIR" "$DIST_DIR"' in script


def test_the_build_verifies_its_own_checksums():
    script = _build_script()
    assert 'sha256sum --quiet -c SHA256SUMS.txt' in script


def test_the_packaging_tool_is_pinned_and_verified():
    """"continuous" tooling would change a release without anyone deciding to."""
    script = _build_script()
    assert 'APPIMAGETOOL_VERSION="1.9.1"' in script
    assert re.search(r'APPIMAGETOOL_SHA256="[0-9a-f]{64}"', script)
    assert 'continuous' not in _code('build_linux_appimage.sh')
    assert 'checksum mismatch' in script


def test_no_long_producer_is_piped_into_an_early_exiting_reader():
    """`set -o pipefail` turns a closed pipe into a failed build.

    `ldconfig -p | awk '… {exit}'` killed a release build with SIGPIPE at
    the point the AppDir was being assembled, and only sometimes - it depends
    on how much output the producer had already buffered.
    """
    for name in ('build_linux_appimage.sh', 'build_linux_appimage_container.sh',
                 'validate_appimage.sh', 'bootstrap_dev_runtime.sh'):
        code = _code(name)
        assert 'set -euo pipefail' in code, name
        for line in code.splitlines():
            if '|' not in line or '<<<' in line:
                continue
            piped_into_awk = re.search(r'\|\s*awk\b', line)
            if piped_into_awk and 'exit}' in line.replace(' ', ''):
                raise AssertionError(f'{name}: producer piped into an awk that '
                                     f'exits early: {line.strip()}')


def test_the_build_checks_the_desktop_entry_and_dependencies():
    script = _build_script()
    assert 'desktop-file-validate' in script
    assert 'scanning dependencies' in script
    assert 'not found' in script


def test_the_desktop_entry_declares_one_main_category():
    """More than one makes the application appear twice in a menu."""
    entry = (ROOT / 'packaging' / 'linux' / 'yt-dlp-gui.desktop').read_text(encoding='utf-8')
    categories = [line for line in entry.splitlines() if line.startswith('Categories=')]
    assert len(categories) == 1
    values = [value for value in categories[0].split('=', 1)[1].split(';') if value]

    # From the XDG menu spec; Audio and Video are subcategories when AudioVideo leads
    main = {'AudioVideo', 'Development', 'Education', 'Game', 'Graphics', 'Network',
            'Office', 'Science', 'Settings', 'System', 'Utility'}
    assert len([value for value in values if value in main]) == 1, values
    assert values[0] == 'AudioVideo'


def test_the_container_never_writes_to_the_checkout():
    """A build must not be able to remove a developer's tracked files."""
    script = _container_script()
    assert '-v "$ROOT:/src:ro"' in script
    assert ':z' not in _code('build_linux_appimage_container.sh'), \
        'relabelling the whole checkout is not acceptable'
    assert 'security-opt label=disable' in script
    # The build works on a copy, and only artifacts travel back
    assert 'tar -C /src' in script
    assert '/work' in script


def test_the_container_excludes_the_development_runtime():
    script = _container_script()
    for excluded in ('./.git', './.venv', './.runtime', './build', './dist'):
        assert f'--exclude={excluded}' in script


def test_artifacts_end_up_owned_by_the_person_who_built_them():
    script = _container_script()
    assert 'Rootless' in script, 'rootless podman remaps ownership and needs handling'
    assert 'podman unshare chown' in script


def test_the_spec_drops_the_plugin_it_cannot_use():
    """Qt's GTK platform theme needs libraries the bundle does not carry."""
    spec = (ROOT / 'packaging' / 'yt-dlp-gui.spec').read_text(encoding='utf-8')
    assert 'platformthemes/libqgtk3' in spec
    assert 'drop_unused_plugins' in spec


def test_the_validator_offers_offline_and_network_modes():
    script = (ROOT / 'scripts' / 'validate_appimage.sh').read_text(encoding='utf-8')
    for flag in ('--network', '--integration', '--host'):
        assert flag in script
    # Structural validation must not need the internet
    assert '--network=none' in script
    # And it must check the release directory, not just the binary
    assert 'sha256sum --quiet -c SHA256SUMS.txt' in script
    assert 'release-manifest.json' in script


def test_the_self_checks_reach_the_application():
    """The validator drives real checks; they have to exist."""
    from app.application import CHECK_DOWNLOAD_FLAG, CHECK_URL_FLAG

    script = (ROOT / 'scripts' / 'validate_appimage.sh').read_text(encoding='utf-8')
    assert CHECK_URL_FLAG in script
    assert CHECK_DOWNLOAD_FLAG in script

    from app import selfcheck

    assert callable(selfcheck.check_url)
    assert callable(selfcheck.check_download)


def test_the_certificate_source_is_reported():
    """A frozen build must not depend on the machine that built it."""
    from app.selfcheck import certificate_source

    source = certificate_source()
    assert source != 'none found'
    assert source.startswith(('certifi', 'system'))
