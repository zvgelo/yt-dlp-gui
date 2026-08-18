# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-08-18

First release. Everything below works in the released Linux artifact and was
checked on a machine with no Python, FFmpeg, Deno or yt-dlp installed.

### Added

- **Downloading video or audio** through the yt-dlp Python API, with quality
  and format choices driven by what the media actually offers rather than by a
  fixed list.
- **Playlists as parent entities**, enumerated lazily, so a failure part-way
  through pagination keeps the items already found instead of losing the lot.
- **A queue** with progress, speed, ETA, post-processing stages, pausing,
  cancellation and per-item retries, split into in-progress, review, failed and
  completed tabs.
- **Duplicate detection** that separates what a media item *is* from what the
  user wants out of it, with a review queue and thread-safe reservations, so
  the same video in two qualities is not mistaken for the same download.
- **Two retry layers**: yt-dlp's own, and an application-level job retry that
  keeps a per-attempt history and a readable reason for each failure.
- **A persistent SQLite history** that survives restarts, recovers interrupted
  downloads and never deletes a downloaded file when records are cleared.
- **URL intent classification**, so a watch link that carries playlist context
  (`youtu.be/<id>?list=…`) downloads one video, and a playlist link downloads a
  playlist - with canonical single-media addresses stored in history.
- **Three themes** (Light, Dark, Steel) and **English and Polish** interfaces,
  all switchable at runtime.
- **Keyboard navigation** with accessible names on every focusable control and
  a tab order that follows the visible layout.
- **An About box** (`⋯` → About, F1, or Preferences → Diagnostics) showing the
  version, the components the build is made of, the project address and the
  licence.
- **A Diagnostics tab** in Preferences listing the application, yt-dlp, FFmpeg,
  Deno, Python and Qt versions with the path each tool was resolved from, and a
  button that copies the block for a bug report.
- **`--version`, `--diagnostics`, `--self-test`, `--check-url` and
  `--check-download`** on the command line, so a packaged artifact can be
  checked without opening a window.
- **A log file** under the user's data directory, with a start-up banner and
  uncaught exceptions, since a released GUI has no console to print to.

### Packaging

- **A Linux AppImage** that carries Python, Qt, yt-dlp, FFmpeg and Deno.
  Nothing has to be installed first, and the bundled JavaScript runtime means
  YouTube extraction offers the full set of formats rather than a reduced one.
- **A Windows packaging pipeline** - PyInstaller bundle, portable ZIP and an
  Inno Setup installer - prepared and exercised in CI, but not yet validated on
  a native Windows machine.
- **Helper binaries resolved in one place**, preferring a pinned copy (bundled
  in a release, fetched into `.runtime/` from source) over a configured path
  over `PATH`; yt-dlp is then told explicitly where they are.
- **`scripts/bootstrap_dev_runtime.sh`**, which gives a source checkout the
  same pinned FFmpeg and Deno a release bundles, so running from source is not
  quietly worse than running the release.
- **A release pipeline that finishes what it starts**: the build writes the
  manifest and checksums itself, after the artifact and only if it validates,
  and swaps the release directory into place in one move, so the files in
  `dist/linux/` always describe the same build.
- **`scripts/validate_appimage.sh`** with offline, `--network` and
  `--integration` modes, all run in a clean container under a throw-away
  profile; `--integration` downloads and merges real media and checks the
  result with ffprobe.

### Fixed

- The Linux build could die of SIGPIPE while assembling the AppDir: a producer
  piped into an `awk` that exits on its first match, under `set -o pipefail`.
  It failed only sometimes, depending on how much output had been buffered.
- A `DownloadController` that was never shut down destroyed a running QThread,
  which aborts the process wherever the garbage collector happens to run. It
  now closes itself, and shutdown unhooks the worker before the thread stops
  and can be called twice.

### Notes

- The bundled yt-dlp is fixed per release. A frozen bundle cannot safely
  rewrite its own package files, so a newer yt-dlp means a new release.
- The AppImage is not bit-for-bit reproducible: squashfs and PyInstaller embed
  timestamps. The manifest records the commit, the container image and every
  bundled version instead.
