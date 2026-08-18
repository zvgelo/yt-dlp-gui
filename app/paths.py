"""Application data locations.

The only place where the data layer meets Qt: `app/core/history.py` receives a
ready `Path` and stays independent of the GUI.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths

from . import APP_NAME

HISTORY_FILENAME = 'history.db'


def app_data_dir() -> Path:
    """`~/.local/share/yt-dlp-gui` on Linux, `%APPDATA%/yt-dlp-gui` on Windows.

    `GenericDataLocation` is used deliberately instead of `AppDataLocation`:
    the latter appends both the organisation and the application name, and
    since both are identical the path would be duplicated. Renaming the
    organisation would move the user's existing QSettings.
    """
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericDataLocation)
    root = Path(location) if location else Path.home() / '.local' / 'share'
    directory = root / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def history_path() -> Path:
    return app_data_dir() / HISTORY_FILENAME
