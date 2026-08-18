# yt-dlp GUI

A native desktop application (Qt / PySide6) that puts a comfortable interface on
top of [yt-dlp](https://github.com/yt-dlp/yt-dlp): paste a link, pick a quality
and a format, and the program downloads the media together with its cover art,
tags and subtitles.

It runs on Linux and Windows. A binary release is self-contained: Python, Qt,
yt-dlp, FFmpeg and a JavaScript runtime all travel with the application, so
nothing has to be installed first. Version 1.0.0 is released as a Linux
AppImage; the Windows packaging pipeline is prepared but has not been validated
on a native Windows machine yet.

The interface is available in English and Polish, ships with three themes
(Light, Dark, Steel) and keeps a persistent download history.

---

## Table of contents

- [Download](#download)
- [Running from source](#running-from-source)
- [Features](#features)
- [How it works](#how-it-works)
- [Project layout](#project-layout)
- [Design rules](#design-rules)
- [Playlists](#playlists)
- [Duplicates and the review queue](#duplicates-and-the-review-queue)
- [Failures and retries](#failures-and-retries)
- [History](#history)
- [Themes](#themes)
- [Languages](#languages)
- [Settings and data locations](#settings-and-data-locations)
- [Testing](#testing)
- [Building a release](#building-a-release)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Download

A release bundles everything it needs - **no Python, no pip, no yt-dlp, no
FFmpeg and no JavaScript runtime have to be installed**. Artifacts are not
published yet; both are produced by the build commands in
[Building a release](#building-a-release), and the Linux one is what 1.0.0 was
validated as.

### Linux (AppImage)

```bash
chmod +x yt-dlp-gui-1.0.0-x86_64.AppImage
./yt-dlp-gui-1.0.0-x86_64.AppImage
```

One file, nothing to install. It runs on Debian 11, Ubuntu 20.04, RHEL 9,
Fedora 34 and anything newer; the build is linked against glibc 2.31. The
graphics stack comes from your system, as it must - only `libGL`, `libEGL`,
fontconfig, D-Bus and core X11, all of which any desktop already has.

If your system has no FUSE, AppImages can run without it:

```bash
./yt-dlp-gui-1.0.0-x86_64.AppImage --appimage-extract-and-run
```

Downloads, settings and the history database are kept under your home
directory, never inside the AppImage.

### Windows (portable ZIP) - pipeline prepared, not yet validated

The Windows packaging pipeline exists and runs in CI - PyInstaller bundle,
portable ZIP, and an Inno Setup installer when Inno Setup is present - but
**1.0.0 has not been validated on a native Windows machine**, so no Windows
artifact is offered as released. Running from source works on Windows today.

When a bundle is built: extract the ZIP anywhere and run `yt-dlp-gui.exe` from
the extracted folder, keeping the folder together - the executable needs the
files beside it. Windows 10 or newer, 64-bit. The builds are unsigned, so
SmartScreen may warn on first run ("More info" -> "Run anyway").

### Verifying a download

```bash
cd <download folder>
sha256sum -c SHA256SUMS.txt
```

`release-manifest.json` beside the artifacts records the commit it was built
from, the build container, and the version of every bundled component.

### Checking what a build contains

```bash
./yt-dlp-gui-1.0.0-x86_64.AppImage --version
./yt-dlp-gui-1.0.0-x86_64.AppImage --diagnostics
```

The same information is in **Preferences → Diagnostics**, with a button that
copies it for a bug report. **About** (the `⋯` menu, or F1) shows the short
version: what this build is, what it is made of, and under what licence.

## Running from source

For development, or to run against your own Python environment. FFmpeg and Deno
are then taken from your system rather than bundled.

```bash
git clone https://github.com/zvgelo/yt-dlp-gui.git
cd yt-dlp-gui
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install PySide6 yt-dlp
python main.py
```

A source checkout has none of the helper binaries a release bundles, so fetch
them once - the same pinned FFmpeg and Deno, verified against the same
checksums:

```bash
./scripts/bootstrap_dev_runtime.sh          # FFmpeg, ffprobe and Deno
./scripts/bootstrap_dev_runtime.sh --only deno
```

They land in the gitignored `.runtime/` directory and are picked up
automatically; `--diagnostics` then reports them as *development runtime*.

This is optional. A system-wide [FFmpeg](https://ffmpeg.org/) and
[Deno](https://deno.com/) 2.3+ work just as well, and without either the
application still runs and says clearly what is unavailable - though YouTube
extraction without a JavaScript runtime is degraded and some formats go
missing.

URLs can also be passed straight on the command line:

```bash
python main.py "https://www.youtube.com/watch?v=..."
```

Convenience launchers are provided: `./run.sh` on Linux and `run.bat` on
Windows. Both use `.venv` when it exists and fall back to the system Python
otherwise.

### Development setup against a local yt-dlp checkout

If a cloned `yt-dlp` repository sits next to this project, install it as an
editable dependency instead of copying its sources:

```bash
uv venv .venv
uv pip install --python .venv/bin/python PySide6
uv pip install --python .venv/bin/python -e "..[default]"   # .. is the yt-dlp repo
.venv/bin/python main.py
```

The application never requires a local checkout; a plain `pip install yt-dlp`
is entirely sufficient. The local repository is used only as documentation —
its sources are never modified.

---

## Features

**Analysis**

- URL analysis without downloading (`extract_info(download=False)`): title,
  uploader, duration, thumbnail, extractor, format list and available
  subtitles.

**Format selection**

- A **simple quality picker** restricted to the resolutions the media actually
  has: if a video tops out at 1080p, 4K never appears in the list.
- An **advanced view** listing concrete streams (`1080p - 60 FPS - VP9 - WEBM`)
  with estimated sizes.
- Video containers Auto / MP4 / MKV / WebM, obtained through merging and
  lossless remuxing rather than needless transcoding.
- Audio-only mode: MP3, M4A, AAC, Opus, FLAC, WAV.

**Media enrichment**

- Metadata, chapters, embedded cover art, `.info.json` and description files.
- Subtitles, both regular and automatic, with the language list taken from the
  media itself rather than a hard-coded table.
- SponsorBlock chapter removal.

**Queue and jobs**

- A queue with progress bars, speed, ETA, post-processing stages, cancellation
  and retries.
- Playlists handled as parent entities: one playlist is one row, not one row
  per file.
- Duplicate detection with a dedicated review tab.
- A "Failed" tab with per-attempt history and manual retries.
- A persistent SQLite history that survives restarts.

**Interface**

- Three themes (Light, Dark, Steel) switchable at runtime.
- English and Polish, switchable at runtime without a restart.
- A log panel carrying the yt-dlp logger messages.
- Rate limiting, proxy support and cookies from a browser profile or a file.

---

## How it works

```
PySide6 (app/gui)          views, card delegate, dialogs - no yt-dlp logic
        | signals
DownloadController         queue, states, job pumping
        |
YtDlpService               ydl_opts construction, extract_info, download
        |
yt_dlp.YoutubeDL           downloading and post-processing
```

Threading: URL analysis and thumbnail fetching run in a `QThreadPool`, the
download itself in a dedicated `QThread`. The Qt main loop performs no blocking
work; everything crosses thread boundaries through signals and slots.

`app/core` is free of Qt widgets and knows nothing about the interface
language. It works with enums and error codes, and `app/gui/labels.py` is the
only place that turns them into words — which is what makes runtime language
switching possible.

---

## Project layout

```
yt-dlp-gui/
├── main.py                        entry point
├── app/
│   ├── application.py             QApplication, style, dependency wiring
│   ├── settings.py                AppSettings + SettingsStore (QSettings)
│   ├── state.py                   AppState / TaskState
│   ├── paths.py                   application data locations
│   ├── resources.py               source tree vs frozen bundle
│   ├── logs.py                    rotating log file for release builds
│   ├── core/
│   │   ├── models.py              MediaInfo, FormatInfo, DownloadRequest, ...
│   │   ├── format_service.py      format discovery, `-f` selectors
│   │   ├── output_template.py     output filename templates
│   │   ├── urls.py                canonical single-media URLs
│   │   ├── ytdlp_service.py       the only module touching YoutubeDL
│   │   ├── download_controller.py queue, playlists, retries, persistence
│   │   ├── duplicates.py          media and artifact identity
│   │   ├── history.py             SQLite store
│   │   ├── history_mapper.py      task <-> record conversion
│   │   ├── runtime_tools.py       finding FFmpeg and the JS runtime
│   │   ├── diagnostics.py         what this build is made of
│   │   └── errors.py              exceptions -> stable error codes
│   ├── workers/                   extract / thumbnail / download
│   ├── gui/                       main window, top bar, cards, dialogs
│   ├── theme/                     theme model, manager, palettes
│   ├── i18n/                      languages and the translation manager
│   └── utils/formatting.py
├── assets/
│   ├── styles/main.qss            one template for every theme
│   └── icons/                     token-coloured SVG icons
├── translations/                  .py catalogues, .ts sources, .qm output
├── packaging/
│   ├── yt-dlp-gui.spec            PyInstaller specification
│   ├── requirements-build.txt     pinned versions a release is built from
│   ├── linux/                     AppRun and the .desktop entry
│   └── windows/                   Inno Setup script
├── scripts/                       translation and build tooling
├── licenses/                      notices for the bundled components
├── docs/RELEASE.md                the release procedure
├── tests/
└── mockup/                        interface designs
```

The models in `app/core/models.py` do not depend on PySide6. A raw `info_dict`
never reaches the widgets; it is translated into models inside
`ytdlp_service.build_media_info()`.

---

## Design rules

- **No downloader of our own.** Everything goes through the yt-dlp Python API:
  `extract_info`, `progress_hooks`, `postprocessor_hooks`, `logger` and the
  native postprocessors. The CLI is never invoked and terminal text is never
  parsed.
- **No hard-coded `format_id`.** Selectors are built dynamically from the
  syntax documented by yt-dlp, for example
  `bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/...`. The
  test `test_every_selector_is_understood_by_yt_dlp` validates every generated
  combination against the real yt-dlp parser.
- **Postprocessor order** mirrors `yt_dlp/__init__.py::get_postprocessors`
  (`ModifyChapters` before `Metadata`, `EmbedThumbnail` last).
- **Cancellation is cooperative**: a `threading.Event` is set from the GUI
  thread and the progress hook raises `DownloadCancelled`, which `YoutubeDL`
  handles natively. `QThread.terminate()` is never called outside an emergency
  shutdown timeout.
- **A finished worker is not a success.** The outcome of a job is decided by
  `DownloadResult.classify()` from the exception, the errors collected by the
  logger and how many items were actually downloaded. Log text is never
  grepped for `[ERROR]`.
- **Styling lives in `assets/styles/main.qss`** only, selected by `objectName`
  and dynamic properties. Colours needed for manual painting come from the
  active theme through `app.theme.active_theme()`.
- **Clearing the history never deletes downloaded files.** Only records are
  removed.

---

## Playlists

Playlists are read as a stream: `extract_info(process=False)` returns an entry
generator that the application consumes itself, with `lazy_playlist=True` set
for downloads. This matters because `YoutubeDL.__process_playlist` materialises
`list(entries)` before any processing, so a single pagination failure (an HTTP
403 on page 3, say) would otherwise discard every entry found earlier.

When enumeration breaks part-way the entries collected so far are kept and the
result is marked incomplete: the interface then reports the number of items it
downloaded rather than a fabricated "37 of 37".

Each playlist entry is downloaded through a **canonical single-media URL**
(`app/core/urls.py`), with playlist query parameters such as `list=` and
`index=` stripped and `noplaylist=True` set. Without that, a child of a YouTube
Mix would re-enumerate the whole parent playlist for every single item.

A playlist appears in the queue as one parent record (`PlaylistJob`) whose
counters are computed from its children, so they can never drift apart from the
queue. Its title becomes a folder name when the corresponding option is on;
it never becomes part of a filename. Numbering item files (`001 - Title.mp4`)
is a separate, optional setting.

---

## Duplicates and the review queue

Duplicate detection rests on telling two identities apart:

- `MediaIdentity` — *what* the media is at the provider (extractor + media id);
- `ArtifactIdentity` — *what the user wants out of it* (media kind, output
  format, quality).

The same video fetched once as MP4 1080p and once as MP3 is therefore not a
duplicate, even though the media id is identical.

- The same artifact in the same target folder is skipped automatically.
- The same artifact somewhere else moves the item to **Needs review**, where
  the user can approve or skip it — individually or for the whole batch. A
  pending decision never blocks the rest of the queue.
- Items being downloaded reserve their artifact, so two jobs can never race to
  produce the same file. `check_and_reserve` is a single operation under one
  lock.
- A history record is not proof that the file still exists; the disk is checked
  before a conflict is reported.

---

## Failures and retries

There are two independent retry layers:

- `retries` / `fragment_retries` are passed straight to yt-dlp and apply
  *within* a single attempt;
- `job_retries` retries the whole job, and only exhausting it moves the item to
  the **Failed** tab.

Only transient errors are retried automatically. A private video or a missing
FFmpeg will not fix itself, so no attempts are wasted on it. A manual retry is
always available, because the user may have logged in, fixed the network or
installed FFmpeg in the meantime; it restarts the automatic policy but leaves
the attempt history intact.

Every attempt is recorded with its number, timestamps and short error, and the
error details dialog shows the full original yt-dlp message. That message is
deliberately never translated.

---

## History

Downloads are stored in an SQLite database with WAL journalling, one connection
per thread and additive schema migrations driven by `PRAGMA user_version`.

The history is part of the application logic rather than a serialisation of GUI
cards: it feeds duplicate detection and restores the playlist-to-item relation
after a restart. Records left as downloading or post-processing by a previous
session are recovered as `INTERRUPTED`, so nothing poses as active and the
application never starts downloading on its own at start-up.

Clearing the history removes records only. Downloaded files are never touched.

---

## Themes

Three themes ship with the application: **Light**, **Dark** and **Steel**.
Switching happens at runtime with no restart.

A single template, `assets/styles/main.qss`, serves all of them. Tokens in
double braces correspond to the fields of `app/theme/theme.py::Theme` — the
`surface_secondary` field fills the `SURFACE_SECONDARY` placeholder — and are
substituted by `ThemeManager.render()`. Adding a colour therefore never
requires updating a mapping table, and a token the theme does not define is
reported as an error rather than rendered literally.

Colours also land in a `QPalette`, because QSS does not reach native dialogs
drawn by the style (`QFileDialog`, `QMessageBox`, internal view elements).
Icons are single SVG files whose `{{FG}}` and `{{ACCENT}}` tokens are
substituted before rendering, so no per-theme bitmaps exist.

Contrast is covered by tests: primary text must meet WCAG AA (4.5:1) on both
surfaces of every theme, and secondary text, statuses and borders must clear
their own thresholds.

---

## Languages

The interface speaks English and Polish and switches at runtime through
`QEvent.LanguageChange`; every widget implements `retranslate_ui()`.

Source strings in the code are English and wrapped in `tr()` / `translate()`.
Translations live in `translations/pl.py` and `translations/en.py` (the English
catalogue carries only the plural forms), are written into the `.ts` files and
compiled to `.qm`:

```bash
python scripts/build_translations.py --update    # refresh .ts from the sources
python scripts/apply_translations.py             # fill in the translations
python scripts/build_translations.py             # compile .qm
```

Missing `.qm` files never break the application; the interface simply stays in
the source language. Tests guard the catalogue: every `tr()` / `translate()`
literal in the code must have a translation, contexts must be named, and Polish
plurals must have all three forms.

---

## Settings and data locations

Settings are kept in `QSettings`. On Linux that is
`~/.config/yt-dlp-gui/yt-dlp-gui.conf`. Stored values include the target
folder, media kind, quality, container, audio format, metadata and cover-art
options, subtitles, network settings, the chosen theme and language, and the
window geometry.

| What            | Linux                                  | Windows                             |
| --------------- | -------------------------------------- | ----------------------------------- |
| Settings        | `~/.config/yt-dlp-gui/yt-dlp-gui.conf` | registry / `%APPDATA%`              |
| History         | `~/.local/share/yt-dlp-gui/history.db` | `%APPDATA%/yt-dlp-gui/history.db`   |
| Thumbnail cache | `~/.cache/yt-dlp-gui/thumbnails`       | `%LOCALAPPDATA%` cache              |
| Log file        | `~/.local/share/yt-dlp-gui/logs/`      | `%APPDATA%/yt-dlp-gui/logs/`        |

All of it lives under your home directory. Nothing is written next to the
AppImage or inside the installation folder, so a portable and an installed
Windows build share the same history and settings, and updating the application
keeps both.

---

## Testing

```bash
pip install pytest ruff
python -m pytest tests
python -m ruff check .
```

The tests need neither an X server (`conftest.py` sets
`QT_QPA_PLATFORM=offscreen`) nor network access. The single exception is the
check that a real `YoutubeDL` accepts every generated format selector, which
runs entirely locally.

One check does use the network and is therefore not part of the suite: it
drives the bundled FFmpeg and Deno through a real download.

```bash
python scripts/integration_check.py --runtime build/runtime-linux
```

---

## Building a release

The full procedure, including clean-machine validation, is in
[`docs/RELEASE.md`](docs/RELEASE.md). In short:

```bash
# Linux: portable AppImage, built inside Debian 11 for glibc compatibility
./scripts/build_linux_appimage_container.sh
# -> dist/linux/yt-dlp-gui-<version>-x86_64.AppImage
```

```powershell
# Windows: portable ZIP, and an installer when Inno Setup is present
python -m venv .venv-build
.venv-build\Scripts\pip install -r packaging\requirements-build.txt
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
# -> dist\windows\yt-dlp-gui-<version>-windows-x86_64.zip
```

Windows artifacts are built on Windows: PySide6 and the PyInstaller bootloader
are native, so there is no supported way to cross-compile them from Linux.

The bundled FFmpeg and Deno are downloaded at build time from pinned releases
and verified against recorded SHA256 checksums; they are not committed to the
repository. Licence notices for everything redistributed are in
[`licenses/README.md`](licenses/README.md).

---

## Troubleshooting

**"FFmpeg was not found"** — only happens when running from source; the binary
releases bundle it. Install FFmpeg or point at it explicitly with the *FFmpeg
location* setting. Merging, audio conversion and cover-art or subtitle
embedding stay disabled until then.

**"No supported JavaScript runtime was found"** — again a source-run situation,
since the releases bundle Deno. YouTube extraction still works but some formats
may be missing. Install [Deno](https://deno.com/) 2.3 or newer to fix it.
Preferences → Diagnostics shows which runtime was found and where.

**Checking which FFmpeg or Deno is in use** — Preferences → Diagnostics, or
`--diagnostics` on the command line. Each tool is listed as *bundled*,
*configured* or *system*. A packaged build should say *bundled*; if it does
not, the download is incomplete.

**A playlist shows fewer items than expected** — the extractor could not read a
further page. The items found so far are kept and the count is reported as
partial on purpose; retrying the job re-runs the enumeration.

**A download finished with "completed with errors"** — some items succeeded and
some did not, or the playlist enumeration was incomplete. The log panel and the
error details dialog carry the original yt-dlp messages.

**An item sits in "Needs review"** — the same artifact already exists somewhere
else on disk. Approve it to download anyway, or skip it.

**Something crashed and the window closed** — packaged builds have no console,
so look in the log file listed in the table above. It opens with the versions
of everything involved, which is what a bug report needs.

**Windows SmartScreen warns about the download** — the builds are unsigned.
Check the SHA256 against `SHA256SUMS.txt` from the release, then choose "More
info" → "Run anyway".

---

## License

Unlicense (public domain), the same as yt-dlp. See [`LICENSE`](LICENSE).

The binary releases redistribute other people's software - FFmpeg under the
LGPL, Deno under the MIT licence, Qt through PySide6 under the LGPL, and the
Python packages yt-dlp depends on. Bundling changes none of their terms; each
component and its licence is listed in
[`licenses/README.md`](licenses/README.md), and the notices ship with the
artifacts.

This project is an independent front-end and is not affiliated with the yt-dlp
team, and it uses neither YouTube's nor yt-dlp's branding.

### Known limitations

- x86_64 only. No ARM64 build is published, because none has been tested.
- The Linux build is validated on Debian 11 and newer; older distributions are
  out of reach of the glibc it links against.
- The minimum usable window width is about 1040 pixels.
- The bundled yt-dlp is fixed per release. YouTube changes independently of
  this application, so an extraction that worked yesterday can fail today; a
  newer yt-dlp arrives with a new release.
- The Windows builds are unsigned, and 1.0.0 was not validated on a native
  Windows machine - only the packaging pipeline and the source run were.
- The AppImage is not bit-for-bit reproducible; squashfs and PyInstaller embed
  timestamps. The release manifest records the commit and every bundled
  version instead.
