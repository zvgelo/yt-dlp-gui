"""Tests for recognising yt-dlp errors and mapping them onto messages."""

from __future__ import annotations

import errno

import pytest

from app.core.errors import AppErrorCode, describe, shorten


@pytest.fixture(scope='module')
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(('message', 'expected'), [
    ('ERROR: Private video. Sign in if you have been granted access', AppErrorCode.PRIVATE_VIDEO),
    ('ERROR: Sign in to confirm your age', AppErrorCode.AGE_RESTRICTED),
    ('ERROR: Video unavailable', AppErrorCode.UNAVAILABLE),
    ('ERROR: The uploader has not made this video available in your country',
     AppErrorCode.GEO_RESTRICTED),
    ('ERROR: Unsupported URL: https://example.com/x', AppErrorCode.UNSUPPORTED_URL),
    ('ERROR: Requested format is not available', AppErrorCode.FORMAT_UNAVAILABLE),
    ('ERROR: No video formats found!', AppErrorCode.NO_FORMATS),
    ('ffmpeg not found. Please install or provide the path using --ffmpeg-location',
     AppErrorCode.FFMPEG_MISSING),
    ('ERROR: Unable to download webpage: <urlopen error timed out>', AppErrorCode.NETWORK_ERROR),
])
def test_common_errors_get_the_right_code(message, expected):
    assert describe(Exception(message)).code is expected


def test_details_are_kept_for_the_log():
    result = describe(Exception('ERROR: Private video. Sign in'))
    assert 'Private video' in result.details
    # The yt-dlp prefix goes away, the text stays original (logs are not translated)
    assert not result.details.startswith('ERROR: ')


def test_disk_full():
    assert describe(OSError(errno.ENOSPC, 'No space left on device')).code \
        is AppErrorCode.NO_DISK_SPACE


def test_permission_denied():
    assert describe(OSError(errno.EACCES, 'Permission denied')).code \
        is AppErrorCode.PERMISSION_DENIED


def test_unknown_error_keeps_its_text():
    result = describe(ValueError('something went wrong'))
    assert result.code is AppErrorCode.UNKNOWN
    assert result.details == 'something went wrong'
    assert result.is_known is False


def test_exception_without_a_message():
    assert describe(RuntimeError()).details == 'RuntimeError'


def test_shortening_a_long_message():
    assert len(shorten('x' * 500)) <= 160
    assert shorten('A short sentence.') == 'A short sentence.'


def test_the_gui_turns_a_code_into_a_sentence(qapp):
    """The user-facing text is composed only in the GUI layer."""
    from app.core.errors import FriendlyError
    from app.gui import labels

    text = labels.error_text(FriendlyError(AppErrorCode.FFMPEG_MISSING, 'ffmpeg not found'))
    assert 'FFmpeg' in text
    # An unrecognised error shows the original yt-dlp message
    raw = labels.error_text(FriendlyError(AppErrorCode.UNKNOWN, 'a strange error'))
    assert raw == 'a strange error'
