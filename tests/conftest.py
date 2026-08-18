"""Shared test configuration."""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

import pytest

# The tests run without installing the package, so the project directory must be
# on the import path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Qt has to work without an X server (CI, remote console)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='session', autouse=True)
def qt_application():
    """One QApplication for the whole run, torn down before the interpreter is.

    Every GUI test asks for `QApplication.instance() or QApplication([])`, so
    they all share this one. What matters is the teardown: a widget that
    outlives the application is destroyed after the C++ application object has
    gone, and PySide segfaults on the way out - all tests reported as passed,
    the process exiting 139. Closing and deleting what is left while the
    application is still alive keeps the exit status honest.
    """
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application

    _destroy_widgets(application)
    gc.collect()
    application.processEvents()


@pytest.fixture(autouse=True)
def close_widgets_after_each_test(qt_application):
    """Leave no window behind.

    `TranslationManager.apply()` walks `topLevelWidgets()` to deliver a
    LanguageChange event, and a later test crashed inside that loop on CI:
    widgets left over from earlier tests, freed on the Python side but still
    listed by Qt. Closing and deleting them at the end of the test that made
    them keeps the list honest - and keeps a failure in the test that caused
    it, rather than in whichever test runs when the collector wakes up.
    """
    yield
    _destroy_widgets(qt_application)


def _destroy_widgets(application) -> None:
    from PySide6.QtCore import QEvent

    for widget in application.topLevelWidgets():
        widget.close()
        widget.setParent(None)
        widget.deleteLater()
    application.processEvents()
    # deleteLater only schedules; this is what actually frees them
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
