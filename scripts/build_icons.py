#!/usr/bin/env python3
"""Render the brand mark into the icon formats the platforms want.

`assets/icons/app_logo.svg` is the single source. The desktop environments and
Windows cannot read it directly at the moment they need it - a `.desktop` entry
points at PNGs in `hicolor`, and a Windows executable embeds an `.ico` - so
both are generated here rather than hand-drawn and kept in sync by hope.

    python scripts/build_icons.py

The SVG carries `{{FG}}` and `{{ACCENT}}` tokens so it can follow the active
theme inside the application. A launcher icon has no theme, so it is rendered
with the brand colours from the Dark palette, which reads well on both light
and dark desktop panels.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: Sizes a Linux desktop looks for under `hicolor`
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

#: Sizes Windows Explorer picks between
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int):
    """One square pixmap of the brand mark at the given size."""
    from app.gui import icons

    return icons.app_logo(size)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=ROOT / 'assets' / 'icons',
                        help='where to write app.ico and the PNG set')
    args = parser.parse_args(argv)

    # Rendering needs a QGuiApplication but no display
    import os

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtGui import QGuiApplication

    # No theme is applied: `active_theme()` already reports the default palette,
    # and a launcher icon has to look right on any desktop anyway
    application = QGuiApplication.instance() or QGuiApplication([])

    png_dir = args.output / 'app'
    png_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for size in PNG_SIZES:
        pixmap = render(size)
        target = png_dir / f'{size}.png'
        if not pixmap.save(str(target), 'PNG'):
            raise SystemExit(f'could not write {target}')
        written.append(target)

    ico_path = args.output / 'app.ico'
    frames = [render(size) for size in ICO_SIZES]
    if not _write_ico(frames, ico_path):
        raise SystemExit(f'could not write {ico_path}')
    written.append(ico_path)

    for path in written:
        print(f'  {path.relative_to(ROOT)}  ({path.stat().st_size} bytes)')
    del application
    return 0


def _write_ico(frames, path: Path) -> bool:
    """Write a multi-resolution .ico.

    Qt's ICO handler writes a single image, and a one-resolution icon looks
    coarse everywhere Explorer scales it, so the container is assembled here
    from PNG-compressed frames - which the ICO format has allowed since Vista.
    """
    import struct
    from io import BytesIO

    from PySide6.QtCore import QBuffer, QByteArray

    images: list[bytes] = []
    for pixmap in frames:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        if not pixmap.save(buffer, 'PNG'):
            return False
        buffer.close()
        images.append(bytes(data))

    out = BytesIO()
    out.write(struct.pack('<HHH', 0, 1, len(images)))
    offset = 6 + 16 * len(images)
    for pixmap, payload in zip(frames, images, strict=True):
        side = pixmap.width()
        out.write(struct.pack(
            '<BBBBHHII',
            0 if side >= 256 else side,   # 0 means 256 in the ICO header
            0 if side >= 256 else side,
            0, 0, 1, 32, len(payload), offset))
        offset += len(payload)
    for payload in images:
        out.write(payload)

    path.write_bytes(out.getvalue())
    return True


if __name__ == '__main__':
    sys.exit(main())
