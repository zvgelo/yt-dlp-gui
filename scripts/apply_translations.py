#!/usr/bin/env python3
"""Fill a .ts file with the translations from the `translations/pl.py` catalogue.

`pyside6-lupdate` refreshes the list of source strings, but it knows nothing
about our translations and, for Python, does not mark plural messages as
`numerus`. This script does both, so `.ts` files can be regenerated without
retyping the translations by hand.

    python scripts/apply_translations.py       # fill in the .ts files
    python scripts/build_translations.py       # compile the .qm files
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = ROOT / 'translations'
sys.path.insert(0, str(TRANSLATIONS))


def apply_catalog(code: str) -> int:
    """Write the translations into `yt_dlp_gui_<code>.ts`. Returns the miss count."""
    try:
        module = __import__(code)
    except ImportError:
        print(f'No translations/{code}.py catalogue; skipping', file=sys.stderr)
        return 0

    entries: dict[str, str] = getattr(module, 'TRANSLATIONS', {})
    plurals: dict[str, list[str]] = getattr(module, 'PLURALS', {})

    path = TRANSLATIONS / f'yt_dlp_gui_{code}.ts'
    tree = ET.parse(path)
    missing = []

    for context in tree.getroot().findall('context'):
        for message in context.findall('message'):
            source = message.findtext('source')
            node = message.find('translation')

            if source in plurals:
                # lupdate does not set numerus for Python; we do it ourselves
                message.set('numerus', 'yes')
                for child in list(node):
                    node.remove(child)
                node.text = None
                for form in plurals[source]:
                    ET.SubElement(node, 'numerusform').text = form
                node.attrib.pop('type', None)
                continue

            if not entries:
                # A catalogue holding plurals only (English, for instance):
                # the remaining texts deliberately keep their source wording
                continue
            value = entries.get(source)
            if value is None:
                missing.append((context.findtext('name'), source))
                continue
            node.text = value
            node.attrib.pop('type', None)

    tree.write(path, encoding='utf-8', xml_declaration=True)
    print(f'{path.name}: filled in, {len(missing)} missing')
    for context_name, source in missing:
        print(f'  [{context_name}] {source!r}')
    return len(missing)


def _available_codes() -> list[str]:
    """Every catalogue that has both a `.py` source and a `.ts` file."""
    return sorted(path.stem for path in TRANSLATIONS.glob('*.py')
                  if (TRANSLATIONS / f'yt_dlp_gui_{path.stem}.ts').exists())


def main() -> int:
    codes = sys.argv[1:] or _available_codes()
    return 1 if sum(apply_catalog(code) for code in codes) else 0


if __name__ == '__main__':
    raise SystemExit(main())
