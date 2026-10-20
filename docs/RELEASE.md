# Making a release

Everything needed to turn a commit into downloadable artifacts. The Linux
AppImage is the primary artifact; the Windows bundle is built on Windows.

## What a release contains

Both artifacts are self-contained. A user needs no Python, no PySide6, no
yt-dlp, no FFmpeg and no JavaScript runtime.

| Component | Version | Pinned in |
| --- | --- | --- |
| yt-dlp | 2026.8.19 | `packaging/requirements-build.txt` |
| PySide6 / Qt | 6.9.3 | `packaging/requirements-build.txt` |
| PyInstaller | 6.22.1 | `packaging/requirements-build.txt` |
| FFmpeg / ffprobe | 8.1.2 (LGPL build) | `scripts/runtime_deps.py` |
| Deno | 2.9.5 | `scripts/runtime_deps.py` |

Licences of everything redistributed: [`licenses/README.md`](../licenses/README.md).

**Validate yt-dlp before tagging.** YouTube changes independently of any pin:
the stable 2026.7.4 already answered media requests with HTTP 403 while a
nightly worked. `--integration` validation is what catches this,
which is why that step is not optional. If the newest stable fails it, pin the
nightly that passes and say so in the changelog.

**The build container reads a Debian snapshot.** Debian 11 left LTS in August
2026 and its live security archive is being dismantled, so the container build
pins `snapshot.debian.org` to `YTDLP_GUI_DEBIAN_SNAPSHOT` (default in
`scripts/build_linux_appimage_container.sh`). The snapshot holds every security
update up to the end of LTS. Moving the build to a newer base image raises the
minimum glibc for users, so do it deliberately.

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
$exe = "$env:TEMP\ytg\yt-dlp-gui\yt-dlp-gui.exe"
# A windowed program: wait for it explicitly and read its exit code
(Start-Process $exe -ArgumentList '--self-test' -Wait -PassThru -NoNewWindow).ExitCode   # 0 = ok
Get-FileHash dist\windows\*.zip -Algorithm SHA256
```

A windowed executable has no console, so `--version` and `--diagnostics`
print nothing there; open the application and check **Preferences →
Diagnostics** instead. `build_windows.ps1` runs the same self-test against a
throw-away profile.

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
./scripts/bootstrap_dev_runtime.sh       # the same pinned binaries, into .runtime/
python scripts/integration_check.py --runtime .runtime/linux-x86_64
```

A host build (`build_linux_appimage.sh`) also leaves them in
`build/runtime-linux`; the container build does not.

## Tagging and publishing

Only after the artifacts have been validated.

```bash
git tag -a v1.0.0 -m 'yt-dlp GUI 1.0.0'
git push origin main v1.0.0
```

Pushing a `v*` tag starts the `release` workflow. It builds both platforms
and, once they succeed, creates a **draft** GitHub release named after the
tag, with the Linux AppImage, `SHA256SUMS.txt` and `release-manifest.json`
attached and the matching `CHANGELOG.md` section as the notes. The job fails
if the changelog has no section for the version.

Review the draft, then publish it from the Releases page or with:

```bash
gh release edit v1.0.0 --draft=false --latest
```

The Windows bundle stays a workflow artifact until it has been validated on a
Windows machine; attach it by hand when it has.

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
9. [ ] tag, push, review the draft release, publish it

**Windows**

- [ ] ZIP built and smoke-tested on Windows
- [ ] clean-VM validation
- [ ] `release_manifest.py --platform windows`
- [ ] ZIP attached to the release by hand

## Updating the bundled dependencies

```bash
# yt-dlp, Qt or PyInstaller
$EDITOR packaging/requirements-build.txt

# FFmpeg: BtbN deletes dated builds after a few weeks, so mirror the new
# archives into the `runtime-deps` release before pinning them
gh release upload runtime-deps <ffmpeg-...-linux64-lgpl-8.1.tar.xz> <ffmpeg-...-win64-lgpl-8.1.zip>

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
