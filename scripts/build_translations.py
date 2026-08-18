#!/usr/bin/env python3
"""Updating and compiling the translation catalogues.

    python scripts/build_translations.py            # .ts -> .qm
    python scripts/build_translations.py --update   # refresh .ts from sources first

Requires the PySide6 tools `pyside6-lupdate` and `pyside6-lrelease`.
Missing `.qm` files do not break the application; the interface simply stays
in English.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted(str(path.relative_to(ROOT)) for path in (ROOT / 'app').rglob('*.py'))
TRANSLATIONS = ROOT / 'translations'
LANGUAGES = ('en', 'pl')
CATALOG_PREFIX = 'yt_dlp_gui'


def _tool(name: str) -> str | None:
    return shutil.which(name) or shutil.which(str(Path(sys.executable).parent / name))


def update_catalogs() -> int:
    """Extract the source strings from the code into the .ts files."""
    lupdate = _tool('pyside6-lupdate')
    if lupdate is None:
        print('pyside6-lupdate not found; skipping the .ts update', file=sys.stderr)
        return 1

    targets = [str(TRANSLATIONS / f'{CATALOG_PREFIX}_{code}.ts') for code in LANGUAGES]
    command = [lupdate, *SOURCES, '-ts', *targets, '-noobsolete']
    print('$', ' '.join(command[:3]), '…')
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def release_catalogs() -> int:
    """Compile the .ts files into the binary .qm files QTranslator loads."""
    lrelease = _tool('pyside6-lrelease')
    if lrelease is None:
        print('pyside6-lrelease not found; the .qm files will not be built', file=sys.stderr)
        return 1

    failures = 0
    for source in sorted(TRANSLATIONS.glob(f'{CATALOG_PREFIX}_*.ts')):
        target = source.with_suffix('.qm')
        result = subprocess.run([lrelease, str(source), '-qm', str(target)], check=False)
        failures += result.returncode != 0
        print(f'{source.name} -> {target.name}')
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update', action='store_true',
                        help='refresh the .ts files from the code before compiling')
    args = parser.parse_args()

    TRANSLATIONS.mkdir(exist_ok=True)
    if args.update:
        update_catalogs()
    return release_catalogs()


if __name__ == '__main__':
    raise SystemExit(main())
