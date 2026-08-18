"""Where a packaged build writes what went wrong.

A released GUI has no console, so an exception that only reaches stderr is an
exception nobody will ever see. Everything the application logs goes to a
rotating file under the user's log directory, and uncaught exceptions - in the
main thread or in a Qt slot - are routed there too.

The log is deliberately quiet: a start-up banner with the versions that matter,
then warnings and errors. Verbose yt-dlp output stays in the in-app log panel
unless the user turns on the verbose setting.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

from .paths import app_data_dir

LOG_FILENAME = 'yt-dlp-gui.log'

#: One megabyte per file, two files kept: enough for a bug report, not a leak
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 2

_configured = False


def log_dir() -> Path:
    """`~/.local/share/yt-dlp-gui/logs`, beside the history database.

    `app_data_dir()` is reused rather than `AppDataLocation`: the latter
    appends the organisation and the application name, which are identical
    here, and the log would end up in a doubled path of its own.
    """
    directory = app_data_dir() / 'logs'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def log_path() -> Path:
    return log_dir() / LOG_FILENAME


def setup(verbose: bool = False) -> Path | None:
    """Install the file handler. Safe to call more than once.

    Returns the log path, or None when the log directory cannot be written -
    which must never stop the application from starting.
    """
    global _configured
    if _configured:
        return log_path()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter('%(asctime)s %(levelname)-7s %(name)s: %(message)s')

    try:
        path = log_path()
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding='utf-8')
    except OSError:
        path = None
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # A console is only there when someone started the program from one
    if sys.stderr is not None and sys.stderr.isatty():
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)

    _configured = True
    return path


def install_excepthook() -> None:
    """Send uncaught exceptions to the log instead of a vanished stderr.

    PySide6 prints a traceback for an exception raised inside a slot and keeps
    the event loop running; without this the trace would go nowhere in a
    windowed build.
    """
    previous = sys.excepthook

    def handler(kind, value, tb) -> None:
        logging.getLogger('app').critical(
            'Uncaught exception\n%s', ''.join(traceback.format_exception(kind, value, tb)))
        previous(kind, value, tb)

    sys.excepthook = handler


def log_startup(diagnostics) -> None:
    """One banner per run, so a log excerpt always says what produced it."""
    log = logging.getLogger('app')
    for line in diagnostics.as_text().splitlines():
        log.info('%s', line)
    log.info('Log file: %s', log_path())
