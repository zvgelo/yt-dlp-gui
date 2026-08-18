"""Output template (`outtmpl`) construction for yt-dlp.

The single place that assembles the template, so the rule "a playlist name is
a folder, never part of a file name" holds everywhere.
"""

from __future__ import annotations

PLAYLIST_FOLDER = '%(playlist_title)s/'
PLAYLIST_INDEX = '%(playlist_index)03d - '


def build_output_template(base: str, *, is_playlist: bool = False,
                          create_folder: bool = True, numbered: bool = True) -> str:
    """Combine the base file name with the playlist options.

    A single item gets `base` unchanged. A playlist item may additionally get a
    folder and a position prefix; the playlist name never reaches the file name.
    """
    base = (base or '%(title)s.%(ext)s').strip()
    if not is_playlist:
        return base

    prefix = PLAYLIST_FOLDER if create_folder else ''
    index = PLAYLIST_INDEX if numbered else ''
    return f'{prefix}{index}{base}'
