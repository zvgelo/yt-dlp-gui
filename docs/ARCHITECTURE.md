# How yt-dlp GUI works

This is the map of the code and the rules it follows. For using the
application see the [README](../README.md); for working on it see
[DEVELOPMENT.md](DEVELOPMENT.md).

## Layers

```
PySide6 (app/gui)          views, card delegate, dialogs - no yt-dlp logic
        | signals
DownloadController         queue, states, retries, history, duplicates
        |
YtDlpService               ydl_opts construction, extract_info, download
        |
yt_dlp.YoutubeDL           downloading and post-processing
```

URL analysis and thumbnail fetching run in a `QThreadPool`; the download
itself runs in a dedicated `QThread`. The Qt main loop does no blocking work,
and everything crosses thread boundaries through signals and slots.

`app/core` has no Qt widgets and knows nothing about the interface language.
It works with enums and error codes. `app/gui/labels.py` is the only place that
turns them into words, which is what makes switching language at runtime
possible. A raw `info_dict` never reaches the widgets: it is converted into the
models in `app/core/models.py` by `ytdlp_service.build_media_info()`.

## Project layout

```
yt-dlp-gui/
├── main.py                        entry point
├── app/
│   ├── application.py             QApplication, command-line flags, wiring
│   ├── settings.py                AppSettings + SettingsStore (QSettings)
│   ├── state.py                   AppState / TaskState
│   ├── paths.py                   application data locations
│   ├── resources.py               source tree vs frozen bundle
│   ├── logs.py                    rotating log file for release builds
│   ├── selfcheck.py               --check-url / --check-download
│   ├── core/
│   │   ├── models.py              MediaInfo, FormatInfo, DownloadRequest, ...
│   │   ├── format_service.py      format discovery, `-f` selectors
│   │   ├── output_template.py     output filename templates
│   │   ├── urls.py                URL intent and canonical single-media URLs
│   │   ├── ytdlp_service.py       the only module touching YoutubeDL
│   │   ├── download_controller.py queue, playlists, retries, persistence
│   │   ├── duplicates.py          media and artifact identity
│   │   ├── history.py             SQLite store
│   │   ├── history_mapper.py      task <-> record conversion
│   │   ├── runtime_tools.py       finding FFmpeg and the JS runtime
│   │   ├── diagnostics.py         what this build is made of
│   │   └── errors.py              yt-dlp messages -> stable error codes
│   ├── workers/                   extract / thumbnail / download
│   ├── gui/                       main window, top bar, cards, dialogs
│   ├── theme/                     theme model, manager, palettes
│   ├── i18n/                      languages and the translation manager
│   └── utils/formatting.py
├── assets/
│   ├── styles/main.qss            one template for every theme
│   ├── icons/                     token-coloured SVG icons
│   └── readme/                    README hero and screenshots
├── translations/                  .py catalogues, .ts sources, .qm output
├── packaging/                     PyInstaller spec, pinned build requirements,
│                                  AppImage and Inno Setup files
├── scripts/                       build, translation and screenshot tooling
├── licenses/                      notices for the bundled components
├── docs/                          this file, development and release guides
└── tests/
```

## Design rules

- **No downloader of our own.** Everything goes through the yt-dlp Python API:
  `extract_info`, `progress_hooks`, `postprocessor_hooks`, `logger` and the
  native postprocessors. The CLI is never invoked and terminal text is never
  parsed.
- **No hard-coded `format_id`.** Selectors are built from the syntax yt-dlp
  documents, for example
  `bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/...`.
  `test_every_selector_is_understood_by_yt_dlp` runs every generated
  combination through the real yt-dlp parser.
- **Postprocessor order** mirrors `yt_dlp/__init__.py::get_postprocessors`:
  `ModifyChapters` before `FFmpegMetadata`, `EmbedThumbnail` last.
- **Cancellation is cooperative.** The GUI thread sets a `threading.Event`, and
  the next progress or postprocessor hook raises `DownloadCancelled`, which
  `YoutubeDL` handles natively. `QThread.terminate()` is never called. If the
  worker ignores a cancel at shutdown for 15 seconds, the process exits
  instead, because every history transaction is already committed.
- **A finished worker is not a success.** `DownloadResult.classify()` decides
  the outcome from the exception, the errors collected by the logger and how
  many items were actually downloaded.
- **Styling lives in `assets/styles/main.qss`** only, selected by `objectName`
  and dynamic properties. Colours needed for manual painting come from
  `app.theme.active_theme()`.
- **Clearing the history never deletes downloaded files.**

## Errors and retries

yt-dlp reports most failures by raising `DownloadError` from `extract_info`
after passing the same text to the logger. `YtDlpService.download()` catches
it and returns a `DownloadResult` with status `ERROR` and the collected
messages. The controller treats that result exactly like a failed attempt:

1. `errors.describe_messages()` matches the messages against known yt-dlp
   phrasing and returns an `AppErrorCode` (private, age-restricted,
   geo-blocked, removed, network, FFmpeg missing, ...) plus the original text.
2. The attempt is recorded with its code and message.
3. Transient codes (network, TLS, proxy, unknown) are retried automatically up
   to `job_retries` times, with `job_retry_delay` between attempts. A private
   video or a missing FFmpeg will not fix itself, so no attempts are spent on
   it.
4. When the attempts run out, the item moves to **Failed** and the status bar
   says so.

There are two retry layers. `retries` and `fragment_retries` go straight to
yt-dlp and apply *within* one attempt. `job_retries` repeats the whole job.
A manual retry is always available, because the user may have logged in,
fixed the network or installed FFmpeg in the meantime. It restarts the
automatic policy but keeps the attempt history.

The original yt-dlp message is shown in the error details dialog and the log
and is deliberately never translated.

## Playlists

Playlists are read as a stream. `extract_info(process=False)` returns an entry
generator that the application consumes itself, and downloads set
`lazy_playlist=True`. This matters because `YoutubeDL.__process_playlist`
materialises `list(entries)` before processing anything, so one pagination
failure (an HTTP 403 on page 3, say) would otherwise discard every entry found
earlier.

When enumeration breaks part-way, the entries collected so far are kept and the
result is marked incomplete. The interface then reports how many items it
downloaded rather than a fabricated "37 of 37". Analysis stops at 1000 entries.

Each entry is downloaded through a **canonical single-media URL**
(`app/core/urls.py`): playlist parameters such as `list=` and `index=` are
stripped and `noplaylist=True` is set. Without that, every child of a YouTube
Mix would re-enumerate the whole parent playlist. The same classification makes
a watch link that carries playlist context (`youtu.be/<id>?list=…`) download
one video, while a real playlist link downloads the playlist.

A playlist is one parent record (`PlaylistJob`) whose counters are computed
from its children, so they cannot drift apart from the queue. Its title can
become a folder name; it never becomes part of a filename. Numbering files
(`001 - Title.mp4`) is a separate option.

## Duplicates and the review queue

Duplicate detection separates two identities:

- `MediaIdentity`: *what* the media is at the provider (extractor + media id);
- `ArtifactIdentity`: *what the user wants out of it* (media kind, output
  format, quality).

The same video fetched once as MP4 1080p and once as MP3 is therefore not a
duplicate.

- The same artifact in the same folder is skipped automatically.
- The same artifact elsewhere goes to **Needs review**, where the user approves
  or skips it, one at a time or for the whole batch. A pending decision never
  blocks the rest of the queue.
- Items being downloaded reserve their artifact, so two jobs cannot race to
  produce the same file. `check_and_reserve` is one operation under one lock.
- A history record is not proof that a file still exists; the disk is checked
  before a conflict is reported.

## History

Downloads are stored in SQLite with WAL journalling, one connection per thread
and additive schema migrations driven by `PRAGMA user_version`.

The history is application state, not a dump of the GUI: it feeds duplicate
detection and restores the playlist-to-item relation after a restart. Records
left as downloading or post-processing by a previous session come back as
`INTERRUPTED`, so nothing poses as active and nothing starts downloading on its
own at start-up. A failed history write is reported in the log and the status
bar; it never stops a download.

## Themes

Light, Dark and Steel switch at runtime. One template,
`assets/styles/main.qss`, serves all of them. Tokens in double braces match the
fields of `app/theme/theme.py::Theme` (`surface_secondary` fills
`SURFACE_SECONDARY`) and are substituted by `ThemeManager.render()`. A token the
theme does not define is reported as an error instead of being rendered
literally.

Colours also go into a `QPalette`, because QSS does not reach native dialogs
(`QFileDialog`, `QMessageBox`). Icons are single SVG files whose `{{FG}}` and
`{{ACCENT}}` tokens are substituted before rendering, so there are no
per-theme bitmaps.

Tests check contrast: primary text meets WCAG AA (4.5:1) on both surfaces of
every theme, and secondary text, statuses and borders clear their own
thresholds.

## Languages

English and Polish switch at runtime through `QEvent.LanguageChange`; every
widget implements `retranslate_ui()`. Source strings are English and wrapped in
`tr()` / `translate()`. Catalogues live in `translations/`; see
[DEVELOPMENT.md](DEVELOPMENT.md#translations) for the workflow. A missing `.qm`
file never breaks the application; the interface simply stays in English.

## Helper binaries

`app/core/runtime_tools.py` resolves FFmpeg, ffprobe and Deno in one order,
used by every caller:

1. the copy bundled with a release,
2. the copy a source checkout fetched into `.runtime/`,
3. a path configured in Preferences,
4. whatever is on `PATH`,
5. nothing: the feature degrades and the interface says so.

yt-dlp is then told explicitly where they are (`ffmpeg_location`,
`js_runtimes`). A pinned binary wins over the system on purpose: a release
ships the versions it was tested with.
