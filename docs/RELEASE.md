# Making a release

Everything needed to turn a commit into downloadable artifacts. The Linux
AppImage is the primary artifact; the Windows bundle is built on Windows.

## What a release contains

Both artifacts are self-contained. A user needs no Python, no PySide6, no
yt-dlp, no FFmpeg and no JavaScript runtime.

| Component | Version | Pinned in |
| --- | --- | --- |
| yt-dlp | 2026.8.17 nightly | `packaging/requirements-build.txt` |
| PySide6 / Qt | 6.9.3 | `packaging/requirements-build.txt` |
| PyInstaller | 6.22.1 | `packaging/requirements-build.txt` |
| FFmpeg / ffprobe | 8.1.2 (LGPL build) | `scripts/runtime_deps.py` |
| Deno | 2.9.5 | `scripts/runtime_deps.py` |

Licences of everything redistributed: [`licenses/README.md`](../licenses/README.md).

**yt-dlp is pinned to a nightly on purpose.** The newest stable, 2026.7.4, no
longer downloads from YouTube - its media requests come back as HTTP 403, which
was reproduced side by side with a nightly succeeding on the same video from
the same machine. `--integration` validation is what catches this, and it is
the reason that step is not optional before tagging. Move back to a stable pin
as soon as one passes it.

## Build machine prerequisites

End users need none of this.

**Linux**

* Python 3.10 or newer, and `python3-venv`
* `curl`, `git`
* Docker or Podman for the portable build (recommended)
* FUSE is *not* required: the container build sets `APPIMAGE_EXTRACT_AND_RUN`

**Windows**

* Python 3.10 or newer (from python.org)
* Optional: [Inno Setup 6](https://jrsoftware.org/isdl.php) for the installer.
  Without it the portable ZIP is still produced and is a complete artifact.

The same fetcher fills a source checkout, so development and release run the
same versions:

```bash
./scripts/bootstrap_dev_runtime.sh
```

## Before building

```bash
# 1. the working tree must be clean; the build refuses otherwise
git status --porcelain

# 2. the version lives in exactly one place
grep __version__ app/__init__.py

# 3. tests and lint
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

## Linux: the AppImage

Two commands produce and check a complete release. There is no third step to
remember; the manifest and checksums are written by the build itself and always
describe the artifact next to them.

```bash
./scripts/build_linux_appimage_container.sh
./scripts/validate_appimage.sh --integration
```

The build runs inside Debian 11 (glibc 2.31), so the artifact starts on Debian
11, Ubuntu 20.04, RHEL 9, Fedora 34 and anything newer. Building straight on a
current distribution produces a file that only runs on machines at least as new
as the one that built it:

```bash
# faster, for development; not portable to older distributions
python3 -m venv .venv-build
.venv-build/bin/pip install -r packaging/requirements-build.txt
./scripts/build_linux_appimage.sh --allow-dirty
```

The release directory ends up holding exactly four files, all from the same
build:

```
dist/linux/
  yt-dlp-gui-<version>-x86_64.AppImage
  yt-dlp-gui-<version>-x86_64.AppImage.sha256
  SHA256SUMS.txt
  release-manifest.json
```

The build refuses to continue if the working tree is dirty (`--allow-dirty`
overrides it for development builds), if the appimagetool checksum does not
match, if the `.desktop` entry does not validate, if any bundled library is
unresolved, if the artifact reports the wrong version, if a helper binary does
not come from the bundle, or if the self-test fails.

### Validation modes

```bash
./scripts/validate_appimage.sh                # structural, no network needed
./scripts/validate_appimage.sh --network      # + real HTTPS extraction
./scripts/validate_appimage.sh --integration  # + real download through FFmpeg
./scripts/validate_appimage.sh --host         # on this machine, not a container
```

Everything runs in a clean Debian 12 container with no Python, FFmpeg, Deno or
yt-dlp, under a throw-away `HOME`, so a validation run never touches the real
history or downloads. The offline mode prepares its container image once and is
genuinely offline afterwards.

Checked, in order: the release directory is complete; `SHA256SUMS.txt` and the
per-artifact `.sha256` both verify; the manifest's hash and size match the file
and carry no build paths; the reported version is exact; ffmpeg, ffprobe and
deno all resolve to the bundle; the self-test passes; the shipped resources are
present and nothing unwanted is; user data lands outside the mount; the
application runs from an unrelated directory; and a deliberately stale system
`ffmpeg` earlier on `PATH` does not win. With `--network`, a real extraction
over verified HTTPS, a watch link with playlist context staying one video, and
a playlist enumerating into canonical children. With `--integration`, an audio
extraction and a video+audio merge, both confirmed by ffprobe.

### Warnings this build is known to emit

Classified once so nobody has to wonder again.

| Warning | Where | Verdict |
| --- | --- | --- |
| `qt.tlsbackend.ossl: Incompatible version of OpenSSL` | PyInstaller analysis inside Debian 11 | Build environment only. Qt was built against OpenSSL 3, Debian 11 ships 1.1. The application never uses Qt networking - HTTPS goes through Python and yt-dlp with certifi - so nothing depends on Qt's TLS backend, and the final artifact does not emit it. |
| `Failed to collect submodules for 'urllib3.contrib.emscripten'` | PyInstaller | Optional browser/WASM support that needs the `js` module, which only exists inside Pyodide. Irrelevant on desktop Linux. |
| `skipping data collection for module 'curl_cffi'` | PyInstaller | `curl_cffi` is an optional alternative HTTP backend for yt-dlp. It is not installed and not bundled; real extraction and download are verified without it. |
| `missing module named _winapi / winreg / msvcrt / _scproxy` | PyInstaller | Windows and macOS imports, guarded at runtime. |

The build prints its own summary at the end. `warnings none` means nothing was
found that the pipeline could not resolve; anything else is listed explicitly.

## Windows: the portable bundle and the installer

Run on Windows; there is no supported way to produce this from Linux.

```powershell
python -m venv .venv-build
.venv-build\Scripts\pip install -r packaging\requirements-build.txt

powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

Results in `dist\windows\`:

* `yt-dlp-gui-<version>-windows-x86_64.zip` - portable, always produced
* `yt-dlp-gui-<version>-setup-x86_64.exe` - only when Inno Setup is installed

Verify it:

```powershell
Expand-Archive dist\windows\yt-dlp-gui-*-windows-x86_64.zip -DestinationPath $env:TEMP\ytg
& $env:TEMP\ytg\yt-dlp-gui\yt-dlp-gui.exe --version
& $env:TEMP\ytg\yt-dlp-gui\yt-dlp-gui.exe --diagnostics
& $env:TEMP\ytg\yt-dlp-gui\yt-dlp-gui.exe --self-test
Get-FileHash dist\windows\*.zip -Algorithm SHA256
```

## Manifest and checksums

The Linux build writes both itself. Only the Windows build still needs the step
explicitly:

```bash
python scripts/release_manifest.py --platform windows   # on Windows
```

They record the commit and whether its tree was clean, the build container and
its image id, appimagetool, Python, glibc, and every bundled version, plus the
size and SHA256 of each artifact.

## Clean-machine validation

The point is to catch what only fails on a machine that is not the developer's.

**Linux** - a container with no Python, no FFmpeg and no Deno:

```bash
docker run --rm -it -v "$PWD/dist/linux:/artifacts:ro" debian:12-slim bash -c '
  apt-get -qq update && apt-get -qq install -y --no-install-recommends \
      libgl1 libegl1 libfontconfig1 libdbus-1-3 libx11-6 libxkbcommon0 >/dev/null
  cd /tmp && cp /artifacts/*.AppImage app.AppImage && chmod +x app.AppImage
  ./app.AppImage --appimage-extract >/dev/null
  QT_QPA_PLATFORM=offscreen ./squashfs-root/AppRun --diagnostics
  QT_QPA_PLATFORM=offscreen ./squashfs-root/AppRun --self-test
'
```

**Windows** - a VM with no Python, no yt-dlp, no FFmpeg and no Deno. Extract
the ZIP or run the installer, start the application and check the Diagnostics
tab in Preferences: FFmpeg and Deno must both say *bundled*.

Also worth doing on both platforms:

* run from an unrelated working directory
* run with a system FFmpeg of a different version earlier on `PATH` - the
  bundled one must still win
* download one short video and one audio-only item, so FFmpeg really runs
* switch theme and language, close and reopen: both must persist
* analyse `https://youtu.be/NPmRmfodJmk?list=RDLkCFJjB64pY` - it must be
  treated as a single video, not a playlist

An end-to-end check of the bundled binaries, including a real download:

```bash
python scripts/integration_check.py --runtime build/runtime-linux
```

## Tagging

Only after the artifacts have been validated.

```bash
git tag -a v1.0.0 -m 'yt-dlp GUI 1.0.0'
git push origin v1.0.0
```

Attach to the release: the artifacts, `SHA256SUMS.txt`,
`release-manifest.json` and the notes from `CHANGELOG.md`.

Pushing a `v*` tag starts the `release` workflow. It builds and uploads the
artifacts to the workflow run; it does not create a GitHub release and
publishes nothing on its own.

## Checklist

**Linux**

1. [ ] version bumped in `app/__init__.py`, `CHANGELOG.md` updated - the
       artifact name, the manifest, `--version` and the About box all read it
       from there
2. [ ] `git status` clean, `pytest` green, `ruff check .` clean
3. [ ] `./scripts/build_linux_appimage_container.sh` - ends with `warnings none`
4. [ ] `./scripts/validate_appimage.sh` - structural checks, offline
5. [ ] `./scripts/validate_appimage.sh --integration` - real extraction and download
6. [ ] `cd dist/linux && sha256sum -c SHA256SUMS.txt` reports `OK`
7. [ ] `release-manifest.json` shows the expected commit and a clean tree
8. [ ] open the AppImage once by hand: themes, language, About, a download
9. [ ] tag and publish

**Windows**

- [ ] ZIP built and smoke-tested on Windows
- [ ] clean-VM validation
- [ ] `release_manifest.py --platform windows`
- [ ] artifacts and notes attached to the release

## Updating the bundled dependencies

```bash
# yt-dlp, Qt or PyInstaller
$EDITOR packaging/requirements-build.txt

# FFmpeg or Deno
$EDITOR scripts/runtime_deps.py          # change the pinned versions
python scripts/runtime_deps.py --refresh-checksums
git add scripts/runtime_deps_checksums.txt

# then re-check the licence table
$EDITOR licenses/README.md
```

Rebuild and re-validate afterwards. The application does not update yt-dlp by
itself: a frozen bundle cannot safely rewrite its own package files, so a newer
yt-dlp means a new application release.
