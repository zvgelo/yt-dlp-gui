#!/usr/bin/env bash
# Build the Linux AppImage.
#
#   scripts/build_linux_appimage.sh              # release build, clean tree required
#   scripts/build_linux_appimage.sh --allow-dirty
#   scripts/build_linux_appimage.sh --skip-runtime-deps
#
# The AppImage is the primary release artifact: one file, no Python, no
# PySide6, no yt-dlp, no FFmpeg and no Deno needed on the target machine.
#
# The release directory is written atomically. Everything is assembled in a
# staging directory and only moved into dist/linux/ once the artifact has been
# built, checked and hashed, so a half-finished release never looks like the
# current one - and the manifest and checksums can only ever describe the
# artifact sitting next to them.
#
# Everything is written under build/ and dist/ inside the repository. Nothing
# outside it is created or removed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT/build"
APPDIR="$BUILD_DIR/AppDir"
FROZEN_DIR="$BUILD_DIR/frozen"
DIST_DIR="$ROOT/dist/linux"
STAGING_DIR="$BUILD_DIR/dist-staging/linux"
TOOLS_DIR="$BUILD_DIR/tools"

# Pinned, not "continuous": a release must not silently change because the
# packaging tool rebuilt itself overnight. The checksum is verified on every
# download, so a corrupted or substituted tool fails the build rather than
# producing a subtly different artifact.
APPIMAGETOOL_VERSION="1.9.1"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"

PYTHON="${PYTHON:-$ROOT/.venv-build/bin/python}"
BUILD_ARGS=()

for argument in "$@"; do
    case "$argument" in
        --allow-dirty|--skip-runtime-deps) BUILD_ARGS+=("$argument") ;;
        *) echo "unknown option: $argument" >&2; exit 2 ;;
    esac
done

step() { printf '\n[appimage] %s\n' "$1"; }
note() { printf '  %s\n' "$1"; }
fail() { printf '[appimage] error: %s\n' "$1" >&2; exit 1; }

#: Collected as the build goes and printed at the end, so nothing important
#: hides in a thousand lines of PyInstaller output
WARNINGS=()
warn() { WARNINGS+=("$1"); printf '  warning: %s\n' "$1" >&2; }

step 'checking prerequisites'
[ -x "$PYTHON" ] || fail "no build interpreter at $PYTHON
  create one with:
    python3 -m venv .venv-build
    .venv-build/bin/pip install -r packaging/requirements-build.txt"
"$PYTHON" -c 'import PyInstaller' 2>/dev/null || fail "PyInstaller is not installed in $PYTHON
  install it with: $PYTHON -m pip install -r packaging/requirements-build.txt"
command -v desktop-file-validate >/dev/null 2>&1 \
    || warn 'desktop-file-validate is not installed; the .desktop entry will not be checked'

VERSION="$("$PYTHON" -c 'import sys; sys.path.insert(0, "'"$ROOT"'"); from app import __version__; print(__version__)')"
ARTIFACT="yt-dlp-gui-${VERSION}-x86_64.AppImage"
note "version   $VERSION"
note "artifact  $ARTIFACT"

step 'fetching appimagetool'
mkdir -p "$TOOLS_DIR"
APPIMAGETOOL="$TOOLS_DIR/appimagetool-${APPIMAGETOOL_VERSION}-x86_64.AppImage"
if [ ! -f "$APPIMAGETOOL" ]; then
    curl -fsSL --proto '=https' --tlsv1.2 -o "$APPIMAGETOOL.part" "$APPIMAGETOOL_URL" \
        || fail "could not download appimagetool from $APPIMAGETOOL_URL"
    mv "$APPIMAGETOOL.part" "$APPIMAGETOOL"
fi
ACTUAL_SHA="$(sha256sum "$APPIMAGETOOL" | cut -d' ' -f1)"
[ "$ACTUAL_SHA" = "$APPIMAGETOOL_SHA256" ] || fail "appimagetool checksum mismatch
  expected $APPIMAGETOOL_SHA256
  actual   $ACTUAL_SHA
  refusing to build a release with unverified tooling"
chmod +x "$APPIMAGETOOL"
note "appimagetool $APPIMAGETOOL_VERSION (sha256 verified)"

step 'building the application bundle'
"$PYTHON" "$ROOT/scripts/build_app.py" --output "$FROZEN_DIR" "${BUILD_ARGS[@]}"

step 'assembling the AppDir'
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor"
cp -a "$FROZEN_DIR/yt-dlp-gui/." "$APPDIR/usr/bin/"

install -m 755 "$ROOT/packaging/linux/AppRun" "$APPDIR/AppRun"
install -m 644 "$ROOT/packaging/linux/yt-dlp-gui.desktop" \
    "$APPDIR/usr/share/applications/yt-dlp-gui.desktop"
# appimagetool looks for the desktop entry and the icon at the AppDir root
cp "$APPDIR/usr/share/applications/yt-dlp-gui.desktop" "$APPDIR/yt-dlp-gui.desktop"

for size in 16 24 32 48 64 128 256 512; do
    target="$APPDIR/usr/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$target"
    install -m 644 "$ROOT/assets/icons/app/${size}.png" "$target/yt-dlp-gui.png"
done
install -m 644 "$ROOT/assets/icons/app/256.png" "$APPDIR/yt-dlp-gui.png"
install -m 644 "$ROOT/assets/icons/app/256.png" "$APPDIR/.DirIcon"

step 'validating the desktop entry'
if command -v desktop-file-validate >/dev/null 2>&1; then
    if OUTPUT="$(desktop-file-validate "$APPDIR/yt-dlp-gui.desktop" 2>&1)" && [ -z "$OUTPUT" ]; then
        note 'desktop-file-validate: clean'
    else
        echo "$OUTPUT" | sed 's/^/  /'
        fail 'the .desktop entry does not validate'
    fi
fi

step 'bundling X client libraries'
# Qt's xcb platform plugin links against helper libraries that minimal systems
# often lack - libxcb-cursor above all, which Ubuntu stopped installing by
# default and which Qt 6 refuses to start without. They are small, pure client
# libraries with no coupling to the graphics driver, so bundling them is safe.
# Deliberately NOT bundled: libGL/libEGL/libX11/libglib/libfontconfig/libdbus,
# which have to match the host's driver and desktop session.
mkdir -p "$APPDIR/usr/lib"
BUNDLED_LIBS=0
# Read the cache once. Piping `ldconfig -p` into an awk that exits on the first
# match closes the pipe early; ldconfig then dies of SIGPIPE and, under
# `pipefail`, takes the whole build with it - intermittently, depending on how
# much of the output had already been buffered.
LDCONFIG_CACHE="$(ldconfig -p 2>/dev/null || true)"
for library in libxcb-cursor.so.0 libxcb-icccm.so.4 libxcb-image.so.0 \
               libxcb-keysyms.so.1 libxcb-randr.so.0 libxcb-render-util.so.0 \
               libxcb-shape.so.0 libxcb-util.so.1 libxcb-xkb.so.1 \
               libxkbcommon.so.0 libxkbcommon-x11.so.0; do
    source_path="$(awk -v lib="$library" \
        '$1 == lib && /x86-64/ && !found {print $NF; found = 1}' <<<"$LDCONFIG_CACHE")"
    if [ -n "$source_path" ] && [ -f "$source_path" ]; then
        install -m 644 "$source_path" "$APPDIR/usr/lib/$library"
        BUNDLED_LIBS=$((BUNDLED_LIBS + 1))
    else
        warn "$library is not on the build machine and will not be bundled"
    fi
done
note "bundled $BUNDLED_LIBS X client libraries"

step 'scanning dependencies'
# PyInstaller reports libraries it chose not to collect; that only matters if
# they are still missing once the AppDir is assembled. This is where the
# question is actually answered.
SCAN_TARGETS=(
    "$APPDIR/usr/bin/yt-dlp-gui"
    "$APPDIR/usr/bin/_internal/PySide6/Qt/plugins/platforms/libqxcb.so"
    "$APPDIR/usr/bin/_internal/PySide6/Qt/lib/libQt6XcbQpa.so.6"
    "$APPDIR/usr/bin/_internal/PySide6/Qt/lib/libQt6Gui.so.6"
    "$APPDIR/usr/bin/_internal/PySide6/Qt/lib/libQt6Network.so.6"
    "$APPDIR/usr/bin/_internal/PySide6/Qt/lib/libQt6Widgets.so.6"
    "$APPDIR/usr/bin/_internal/PySide6/Qt/lib/libQt6Svg.so.6"
    "$APPDIR/usr/bin/_internal/runtime/ffmpeg"
    "$APPDIR/usr/bin/_internal/runtime/deno"
)
for plugin in "$APPDIR/usr/bin/_internal/PySide6/Qt/plugins/imageformats"/*.so \
              "$APPDIR/usr/bin/_internal/PySide6/Qt/plugins/xcbglintegrations"/*.so \
              "$APPDIR/usr/bin/_internal/PySide6/Qt/plugins/tls"/*.so; do
    [ -f "$plugin" ] && SCAN_TARGETS+=("$plugin")
done

# Libraries the host is expected to provide; anything else missing is a bug.
# These are the graphics and session libraries every desktop has and that an
# AppImage must not carry, because they have to match the running driver.
EXPECTED_FROM_HOST='libGL|libEGL|libGLX|libGLdispatch|libX11|libxcb\.|libXau|libXdmcp|libglib|libgobject|libgio|libgmodule|libgthread|libdbus|libfontconfig|libfreetype|libexpat|libz\.|libbz2|libpng|libbrotli|libuuid|libsystemd|liblzma|libzstd|libcap|libgcrypt|libgpg-error'

MISSING=0
for target in "${SCAN_TARGETS[@]}"; do
    [ -f "$target" ] || { warn "not present, so not scanned: ${target#"$APPDIR/"}"; continue; }
    while read -r missing; do
        [ -z "$missing" ] && continue
        if echo "$missing" | grep -qE "$EXPECTED_FROM_HOST"; then
            continue
        fi
        warn "missing library ${missing} needed by ${target#"$APPDIR/"}"
        MISSING=$((MISSING + 1))
    done < <(LD_LIBRARY_PATH="$APPDIR/usr/lib:$APPDIR/usr/bin/_internal:$APPDIR/usr/bin/_internal/PySide6/Qt/lib" \
                 ldd "$target" 2>/dev/null | awk '/not found/ {print $1}')
done
[ "$MISSING" -eq 0 ] || fail "$MISSING library dependencies cannot be resolved"
note "scanned ${#SCAN_TARGETS[@]} binaries, no unresolved dependencies"

step 'copying third-party licences'
LICENSE_DIR="$APPDIR/usr/share/licenses/yt-dlp-gui"
mkdir -p "$LICENSE_DIR"
install -m 644 "$ROOT/LICENSE" "$LICENSE_DIR/LICENSE"
if [ -d "$ROOT/licenses" ]; then
    cp -a "$ROOT/licenses/." "$LICENSE_DIR/"
fi
if [ -f "$BUILD_DIR/runtime-linux/FFMPEG-LICENSE.txt" ]; then
    install -m 644 "$BUILD_DIR/runtime-linux/FFMPEG-LICENSE.txt" \
        "$LICENSE_DIR/FFMPEG-LICENSE.txt"
fi
note "$(find "$LICENSE_DIR" -type f | wc -l) licence files"

step 'checking permissions'
for binary in AppRun usr/bin/yt-dlp-gui usr/bin/_internal/runtime/ffmpeg \
              usr/bin/_internal/runtime/ffprobe usr/bin/_internal/runtime/deno; do
    [ -x "$APPDIR/$binary" ] || fail "$binary is not executable inside the AppDir"
done
note 'AppRun, application and runtime binaries are executable'

step 'building the AppImage'
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
ARCH=x86_64 "$APPIMAGETOOL" --no-appstream "$APPDIR" "$STAGING_DIR/$ARTIFACT" \
    || fail 'appimagetool failed'
chmod +x "$STAGING_DIR/$ARTIFACT"

step 'checking the artifact'
REPORTED="$("$STAGING_DIR/$ARTIFACT" --version)" || fail 'the AppImage does not report its version'
[ "$REPORTED" = "yt-dlp GUI $VERSION" ] \
    || fail "the AppImage reports '$REPORTED', expected 'yt-dlp GUI $VERSION'"
note "$REPORTED"

DIAGNOSTICS="$("$STAGING_DIR/$ARTIFACT" --diagnostics)" || fail 'the AppImage cannot report diagnostics'
for tool in ffmpeg ffprobe deno; do
    echo "$DIAGNOSTICS" | grep -qE "^${tool}: .*- bundled" \
        || fail "the AppImage does not use its bundled ${tool}:
$(echo "$DIAGNOSTICS" | grep "^${tool}:")"
done
note 'ffmpeg, ffprobe and deno all resolve to the bundle'

QT_QPA_PLATFORM=offscreen "$STAGING_DIR/$ARTIFACT" --self-test >/dev/null \
    || fail 'the self-test failed'
note 'self-test passed'

step 'hashing and describing the release'
( cd "$STAGING_DIR" && sha256sum "$ARTIFACT" > "$ARTIFACT.sha256" )
YTDLP_GUI_APPIMAGETOOL="$APPIMAGETOOL_VERSION" \
    "$PYTHON" "$ROOT/scripts/release_manifest.py" --platform linux \
    --dist "$STAGING_DIR" --build-dir "$FROZEN_DIR" >/dev/null \
    || fail 'the release manifest could not be written'
( cd "$STAGING_DIR" && sha256sum --quiet -c SHA256SUMS.txt ) \
    || fail 'the checksums do not match the artifact that was just built'
note 'manifest and checksums describe this build'

step 'publishing'
# Only now does the release directory change, and it changes all at once
rm -rf "$DIST_DIR"
mkdir -p "$(dirname "$DIST_DIR")"
mv "$STAGING_DIR" "$DIST_DIR"
rmdir "$(dirname "$STAGING_DIR")" 2>/dev/null || true

SIZE_BYTES="$(stat -c '%s' "$DIST_DIR/$ARTIFACT")"
SHA="$(cut -d' ' -f1 < "$DIST_DIR/$ARTIFACT.sha256")"
COMMIT="$("$PYTHON" -c "
import json, pathlib
data = json.loads(pathlib.Path('$DIST_DIR/release-manifest.json').read_text())
print(data['git']['commit'])")"

step 'done'
printf '  %-14s %s\n' 'version' "$VERSION"
printf '  %-14s %s\n' 'commit' "$COMMIT"
printf '  %-14s %s\n' 'artifact' "dist/linux/$ARTIFACT"
printf '  %-14s %s MB (%s bytes)\n' 'size' "$((SIZE_BYTES / 1024 / 1024))" "$SIZE_BYTES"
printf '  %-14s %s\n' 'sha256' "$SHA"
printf '  %-14s %s\n' 'ffmpeg' "$(awk '/^ffmpeg:/ {print $2; exit}' <<<"$DIAGNOSTICS")"
printf '  %-14s %s\n' 'deno' "$(awk '/^deno:/ {print $2; exit}' <<<"$DIAGNOSTICS")"
printf '  %-14s %s\n' 'yt-dlp' "$(awk '/^yt-dlp:/ {print $2; exit}' <<<"$DIAGNOSTICS")"
printf '  %-14s %s\n' 'validation' 'version, bundled tools and self-test passed'
printf '  %-14s %s\n' 'manifest' 'dist/linux/release-manifest.json'
printf '  %-14s %s\n' 'checksums' 'dist/linux/SHA256SUMS.txt'

if [ ${#WARNINGS[@]} -eq 0 ]; then
    printf '  %-14s none\n' 'warnings'
else
    printf '  %-14s %d\n' 'warnings' "${#WARNINGS[@]}"
    for warning in "${WARNINGS[@]}"; do
        printf '      - %s\n' "$warning"
    done
fi

echo
echo '  run it with:'
echo "    dist/linux/$ARTIFACT"
echo '  validate it with:'
echo '    ./scripts/validate_appimage.sh'
