# Developing yt-dlp GUI

## Setup

Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
./scripts/bootstrap_dev_runtime.sh # pinned FFmpeg, ffprobe and Deno into .runtime/
                                   # Windows: python scripts/runtime_deps.py --development
./run.sh                           # or: python main.py [URL ...]
```

`bootstrap_dev_runtime.sh` fetches the same FFmpeg and Deno a release bundles,
verified against the same checksums, into the gitignored `.runtime/`.
`--only deno` fetches just the JavaScript runtime. `--diagnostics` then reports
them as *development runtime*.

### Against a local yt-dlp checkout

If a clone of yt-dlp sits one directory up, install it editable instead of the
PyPI package, so `git pull` there updates the application's yt-dlp:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
uv pip install --python .venv/bin/python -e "..[default]"   # .. is the yt-dlp clone
```

The application never requires a checkout; `pip install yt-dlp` is enough.

## Tests and lint

```bash
python -m pytest
python -m ruff check .
```

The suite needs neither a display (`conftest.py` sets
`QT_QPA_PLATFORM=offscreen`) nor network access. It includes a check that a
real `YoutubeDL` accepts every format selector the application generates.

One check uses the network and is kept out of the suite. It drives the pinned
FFmpeg and Deno through a real download:

```bash
python scripts/integration_check.py --runtime .runtime/linux-x86_64   # Windows: .runtime\windows-x86_64
```

## Command-line flags

| Flag | What it does |
| --- | --- |
| `--version` | prints the version and exits |
| `--diagnostics` | prints versions and where FFmpeg and Deno were found |
| `--self-test` | builds the whole interface once, checks it and exits |
| `--check-url URL` | analyses a URL without a window |
| `--check-download URL --output DIR` | downloads without a window |

## Translations

Source strings are English. Polish lives in `translations/pl.py`; the English
catalogue (`en.py`) carries only plural forms.

```bash
python scripts/build_translations.py --update    # refresh .ts from the sources
python scripts/apply_translations.py             # fill in the translations
python scripts/build_translations.py             # compile .qm
```

Tests require every `tr()` / `translate()` literal to have a translation,
contexts to be named, and Polish plurals to have all three forms.

## README screenshots

```bash
python scripts/readme_screenshots.py
```

Renders the real windows offscreen, against a throw-away profile filled with
demo items, into `assets/readme/screenshots/`. Nothing is downloaded and your
own settings and history are not read. Re-run it after visible interface
changes.

## Releases

See [RELEASE.md](RELEASE.md).
