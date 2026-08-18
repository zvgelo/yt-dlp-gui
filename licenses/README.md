# Third-party components in the binary releases

The AppImage and the Windows bundle are self-contained, so they redistribute
software written by other people. This file records what is inside them and
under which terms, and the release scripts copy it next to the artifacts.

The application itself is released into the public domain under the Unlicense;
see [`LICENSE`](../LICENSE) at the repository root. Bundling does not change
the terms of anything listed below - each component keeps its own licence.

Every entry here was read from the package metadata or the licence file that
the component ships. Nothing is reproduced from memory.

## Executables shipped in `runtime/`

| Component | Version | Licence | Where it comes from |
| --- | --- | --- | --- |
| FFmpeg (`ffmpeg`, `ffprobe`) | n8.1.2 | LGPL-3.0-or-later | [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), `linux64-lgpl` / `win64-lgpl` |
| Deno | 2.9.5 | MIT | [denoland/deno](https://github.com/denoland/deno) release binaries |

**FFmpeg.** The LGPL build is used rather than the GPL one. The binary reports
"GNU Lesser General Public License version 3 or later", matching its
`--enable-version3` configuration, and the full licence text ships as
`FFMPEG-LICENSE.txt` beside the binaries. The application runs FFmpeg as a
separate program and does not link against it. Sources for the exact build are
available from the FFmpeg project and from the build repository linked above.

**Deno.** Redistributed unmodified under the MIT licence.

Both are fetched at build time by `scripts/runtime_deps.py`, pinned to an exact
release and verified against the SHA256 checksums recorded in
`scripts/runtime_deps_checksums.txt`.

## Python packages inside the bundle

Frozen into the application by PyInstaller.

| Package | Licence |
| --- | --- |
| yt-dlp | Unlicense |
| yt-dlp-ejs | Unlicense AND MIT AND ISC |
| PySide6 (Qt for Python, includes Qt) | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| certifi | MPL-2.0 |
| requests | Apache-2.0 |
| urllib3 | MIT |
| websockets | BSD-3-Clause |
| mutagen | GPL-2.0-or-later |
| pycryptodomex | BSD-2-Clause AND Public Domain |
| brotli | MIT |
| CPython runtime | PSF-2.0 |

**PySide6 and Qt.** Used under the LGPL. The libraries are shipped unmodified
as separate shared objects inside the bundle, which is what the LGPL requires
for dynamic linking; replacing them is possible by swapping the files in
`_internal/PySide6/`. The full licence texts ship inside the PySide6
distribution in the bundle.

**mutagen** is GPL-2.0-or-later and is an optional dependency of yt-dlp, used
for writing audio tags. It is a separate Python module inside the bundle.

## Not bundled

* The graphics stack (`libGL`, `libEGL`, `libX11`, fontconfig, freetype) is
  deliberately taken from the host on Linux; those have to match the driver.
* No fonts are redistributed. The interface uses whatever the desktop provides.
* The yt-dlp *source repository* is not bundled. Releases contain the yt-dlp
  Python package from PyPI, pinned in `packaging/requirements-build.txt`.

## Updating this file

When `scripts/runtime_deps.py` or `packaging/requirements-build.txt` change,
re-check the versions and licence expressions here:

    python scripts/runtime_deps.py --print-versions
    .venv-build/bin/python -c "import importlib.metadata as m; print(m.metadata('yt-dlp')['License-Expression'])"
