# PyInstaller specification for yt-dlp GUI.
#
# One spec serves Linux and Windows. It is deliberately explicit: the datas are
# listed by hand rather than collected wholesale, and the Qt modules the
# application never imports are excluded, which keeps the bundle to the four
# modules `grep -o 'from PySide6\.\w*'` actually finds.
#
# Built through `scripts/build_app.py`, which passes the runtime directory and
# the output paths; running PyInstaller on this file directly also works.
#
#     pyinstaller packaging/yt-dlp-gui.spec --noconfirm
#
# onedir, not onefile, on purpose: the bundled ffmpeg and deno stay real files
# on disk for the lifetime of the process, start-up skips an unpack step, and
# antivirus heuristics are markedly friendlier to a plain directory.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent

sys.path.insert(0, str(ROOT))
from app import APP_NAME  # noqa: E402

#: Set by the build script; empty means "this build ships no helper binaries"
RUNTIME_DIR = os.environ.get('YTDLP_GUI_RUNTIME_DIR', '')

IS_WINDOWS = os.name == 'nt'


def resource_datas() -> list[tuple[str, str]]:
    """Everything the application reads at runtime, in the layout it expects.

    `app/resources.py` looks for `assets/` and `translations/` directly under
    the bundle root, so the destinations here mirror the source tree.
    """
    datas = [
        (str(ROOT / 'assets' / 'icons'), 'assets/icons'),
        (str(ROOT / 'assets' / 'styles'), 'assets/styles'),
        # The About box shows this without reaching for the network
        (str(ROOT / 'LICENSE'), '.'),
    ]
    # Compiled catalogues only: the .ts sources are build inputs, not resources
    for catalogue in sorted((ROOT / 'translations').glob('*.qm')):
        datas.append((str(catalogue), 'translations'))
    if RUNTIME_DIR and Path(RUNTIME_DIR).is_dir():
        datas.append((RUNTIME_DIR, 'runtime'))
    return datas


# yt-dlp resolves its extractors lazily, so nothing statically references them
# and PyInstaller cannot see them from the import graph.
hidden_imports = collect_submodules('yt_dlp.extractor')
hidden_imports += [
    # Registered by yt_dlp/__init__.py at import time, but reached by name
    'yt_dlp.utils._jsruntime',
    'yt_dlp.postprocessor.ffmpeg',
    # Certificate bundle used by yt-dlp's HTTPS requests
    'certifi',
]

# Qt ships far more than this application uses. Dropping the rest removes
# hundreds of megabytes without touching anything that is imported.
excluded_qt = [
    'PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras',
    'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender',
    'PySide6.QtBluetooth', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
    'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets', 'PySide6.QtNfc', 'PySide6.QtOpenGL',
    'PySide6.QtOpenGLWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtPositioning', 'PySide6.QtQml', 'PySide6.QtQuick',
    'PySide6.QtQuick3D', 'PySide6.QtQuickControls2', 'PySide6.QtQuickWidgets',
    'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtSensors',
    'PySide6.QtSerialBus', 'PySide6.QtSerialPort', 'PySide6.QtSpatialAudio',
    'PySide6.QtSql', 'PySide6.QtStateMachine', 'PySide6.QtTest',
    'PySide6.QtTextToSpeech', 'PySide6.QtUiTools', 'PySide6.QtWebChannel',
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineQuick', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebSockets', 'PySide6.QtXml',
]

excludes = [
    *excluded_qt,
    'tkinter', 'test', 'unittest', 'pydoc_data',
    # yt-dlp's own bundle script excludes these; cffi drags them in otherwise
    'setuptools', 'packaging', 'pkg_resources', 'pip',
    # Development-only dependencies that must never reach a release
    'pytest', '_pytest', 'ruff',
]


analysis = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=resource_datas(),
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# Qt plugins the application never loads but PyInstaller collects anyway. The
# GTK platform theme is the notable one: it links against libgtk-3, libatk and
# libgdk, none of which are bundled, so PyInstaller reports them as missing on
# every build and the plugin could never load. The application draws its own
# Light/Dark/Steel palettes through QSS and asks Qt for no platform theme, so
# dropping it removes three build warnings and a plugin that cannot work.
UNUSED_PLUGINS = ('platformthemes/libqgtk3',)


def drop_unused_plugins(entries):
    kept = []
    for entry in entries:
        destination = entry[0].replace('\\', '/')
        if any(pattern in destination for pattern in UNUSED_PLUGINS):
            print(f'Excluding unused Qt plugin: {destination}')
            continue
        kept.append(entry)
    return kept


analysis.binaries = drop_unused_plugins(analysis.binaries)
analysis.datas = drop_unused_plugins(analysis.datas)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,          # stripping bundled Qt libraries has broken builds before
    upx=False,            # UPX raises antivirus false positives for no real gain
    console=False,        # a released GUI opens no console; failures go to the log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'assets' / 'icons' / 'app.ico') if IS_WINDOWS else None,
    version=os.environ.get('YTDLP_GUI_WIN_VERSION_FILE') or None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
