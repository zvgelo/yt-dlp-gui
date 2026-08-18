#!/usr/bin/env bash
# Check a built AppImage the way a user's machine would.
#
#   scripts/validate_appimage.sh                 # structural checks, no network
#   scripts/validate_appimage.sh --network       # + a real HTTPS extraction
#   scripts/validate_appimage.sh --integration   # + a real download through FFmpeg
#   scripts/validate_appimage.sh --host          # run on this machine, not a container
#
# The developer's machine already has Python, FFmpeg and half the Qt stack, so
# it cannot answer the only question that matters: does this file work for
# somebody who has none of that? A clean container can, and by default that is
# where everything runs.
#
# Every check uses a throw-away HOME, so a validation run never touches the
# real download history, settings or cache.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${YTDLP_GUI_TEST_IMAGE:-debian:12-slim}"

#: Analysed only, so its length does not matter
NETWORK_URL="${YTDLP_GUI_TEST_URL:-https://www.youtube.com/watch?v=wqAT6GfHsVc}"
#: Actually downloaded, so it is deliberately tiny - about a minute of a
#: Creative Commons clip. A validation run is not a bandwidth test, and a
#: popular video invites the rate limiting that YouTube answers with 403.
DOWNLOAD_URL="${YTDLP_GUI_DOWNLOAD_URL:-https://www.youtube.com/watch?v=iONbUvOhrlU}"
#: A watch link carrying playlist context; must stay a single video
MIX_URL='https://youtu.be/NPmRmfodJmk?list=RDLkCFJjB64pY'
#: A real, small playlist
PLAYLIST_URL='https://www.youtube.com/playlist?list=PL2qgrgXsNUG5ig9cat4ohreBjYLAPC0J5'

MODE=offline
ON_HOST=0
ARTIFACT=''

while [ $# -gt 0 ]; do
    case "$1" in
        --network) MODE=network ;;
        --integration) MODE=integration ;;
        --host) ON_HOST=1 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) ARTIFACT="$1" ;;
    esac
    shift
done

if [ -z "$ARTIFACT" ]; then
    ARTIFACT="$(ls -1 "$ROOT"/dist/linux/*.AppImage 2>/dev/null | head -1 || true)"
fi
[ -n "$ARTIFACT" ] && [ -f "$ARTIFACT" ] || {
    echo "error: no AppImage found; build one first or pass a path" >&2
    exit 1
}
ARTIFACT="$(cd "$(dirname "$ARTIFACT")" && pwd)/$(basename "$ARTIFACT")"
DIST_DIR="$(dirname "$ARTIFACT")"

printf '[validate] artifact %s\n' "$(basename "$ARTIFACT")"
printf '[validate] mode     %s\n' "$MODE"

# ---------------------------------------------------------------- host checks
# Hashes and the manifest describe the release directory, so they are checked
# here rather than inside the container that only sees the AppImage.

printf '\n[host] release directory\n'
for required in "$(basename "$ARTIFACT").sha256" SHA256SUMS.txt release-manifest.json; do
    [ -f "$DIST_DIR/$required" ] || {
        echo "  !! $required is missing from the release directory" >&2
        exit 1
    }
    printf '  %s\n' "$required"
done

printf '\n[host] checksums\n'
( cd "$DIST_DIR" && sha256sum --quiet -c SHA256SUMS.txt ) || {
    echo '  !! SHA256SUMS.txt does not match the artifact' >&2; exit 1; }
( cd "$DIST_DIR" && sha256sum --quiet -c "$(basename "$ARTIFACT").sha256" ) || {
    echo '  !! the per-artifact checksum does not match' >&2; exit 1; }
echo '  SHA256SUMS.txt and the per-artifact checksum both verify'

printf '\n[host] manifest\n'
python3 - "$DIST_DIR" "$(basename "$ARTIFACT")" <<'PYTHON' || exit 1
import hashlib
import json
import pathlib
import sys

dist = pathlib.Path(sys.argv[1])
name = sys.argv[2]
manifest = json.loads((dist / 'release-manifest.json').read_text())

artifacts = {item['name']: item for item in manifest['artifacts']}
if name not in artifacts:
    print(f'  !! the manifest does not mention {name}', file=sys.stderr)
    print(f'     it lists: {sorted(artifacts)}', file=sys.stderr)
    raise SystemExit(1)

entry = artifacts[name]
path = dist / name
digest = hashlib.sha256()
with path.open('rb') as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
        digest.update(chunk)

if entry['sha256'] != digest.hexdigest():
    print('  !! the manifest records a different SHA256 - it is stale', file=sys.stderr)
    print(f"     manifest {entry['sha256']}", file=sys.stderr)
    print(f'     actual   {digest.hexdigest()}', file=sys.stderr)
    raise SystemExit(1)
if entry['size_bytes'] != path.stat().st_size:
    print('  !! the manifest records a different size - it is stale', file=sys.stderr)
    raise SystemExit(1)

bundled = manifest['bundled']
for key in ('yt_dlp', 'pyside6', 'ffmpeg', 'deno'):
    if not bundled.get(key):
        print(f'  !! the manifest does not say which {key} was bundled', file=sys.stderr)
        raise SystemExit(1)

text = json.dumps(manifest)
for leak in ('/home/', '/root/', '/work/', '/src/'):
    if leak in text:
        print(f'  !! the manifest contains a build path: {leak}', file=sys.stderr)
        raise SystemExit(1)

print(f"  version {manifest['version']}, commit {manifest['git']['commit']}"
      f" ({manifest['git'].get('tree_state') or 'unknown tree'})")
print(f"  yt-dlp {bundled['yt_dlp']}, PySide6 {bundled['pyside6']},"
      f" FFmpeg {bundled['ffmpeg']}, Deno {bundled['deno']}")
print('  sha256 and size match the artifact, no developer paths')
PYTHON

# ------------------------------------------------------------ container checks

run_checks() {
    cat <<'SCRIPT'
set -euo pipefail

APP="${APPRUN:?}"
PROFILE="$(mktemp -d)"
export HOME="$PROFILE"
export XDG_DATA_HOME="$PROFILE/data"
export XDG_CONFIG_HOME="$PROFILE/config"
export XDG_CACHE_HOME="$PROFILE/cache"
export QT_QPA_PLATFORM=offscreen
cleanup() { rm -rf "$PROFILE"; }
trap cleanup EXIT

fail() { echo "  !! $1" >&2; exit 1; }

echo
echo "[app] version"
REPORTED="$("$APP" --version)"
echo "  $REPORTED"
[ "$REPORTED" = "yt-dlp GUI $EXPECTED_VERSION" ] \
    || fail "expected 'yt-dlp GUI $EXPECTED_VERSION'"

echo
echo "[app] diagnostics"
"$APP" --diagnostics > "$PROFILE/diagnostics.txt"
sed 's/^/  /' "$PROFILE/diagnostics.txt"
for tool in ffmpeg ffprobe deno; do
    grep -qE "^${tool}: .*- bundled" "$PROFILE/diagnostics.txt" \
        || fail "${tool} does not come from the bundle"
done

echo
echo "[app] self-test"
"$APP" --self-test | sed 's/^/  /'

echo
echo "[app] bundled resources"
ROOT_DIR="$(dirname "$APP")"
for resource in \
    usr/bin/_internal/assets/styles/main.qss \
    usr/bin/_internal/assets/icons/app_logo.svg \
    usr/bin/_internal/translations/yt_dlp_gui_pl.qm \
    usr/bin/_internal/translations/yt_dlp_gui_en.qm \
    usr/bin/_internal/PySide6/Qt/plugins/platforms/libqxcb.so \
    usr/bin/_internal/PySide6/Qt/plugins/imageformats/libqsvg.so \
    usr/bin/_internal/PySide6/Qt/plugins/imageformats/libqjpeg.so \
    usr/bin/_internal/PySide6/Qt/plugins/imageformats/libqwebp.so \
    usr/share/licenses/yt-dlp-gui/FFMPEG-LICENSE.txt; do
    [ -e "$ROOT_DIR/$resource" ] || fail "missing from the bundle: $resource"
done
echo "  stylesheet, icons, catalogues, Qt platform and image plugins, licences"

echo
echo "[app] nothing that should not be there"
for unwanted in usr/bin/_internal/tests usr/bin/_internal/.runtime \
                usr/bin/_internal/mockup usr/bin/warn-yt-dlp-gui.txt \
                usr/bin/xref-yt-dlp-gui.html; do
    if [ -e "$ROOT_DIR/$unwanted" ]; then
        fail "the bundle contains $unwanted"
    fi
done
STRAY="$(find "$ROOT_DIR" \( -name '*.db' -o -name '__pycache__' \) -print -quit)"
if [ -n "$STRAY" ]; then
    fail "the bundle contains $STRAY"
fi
echo "  no tests, no development runtime, no caches, no PyInstaller reports"

echo
echo "[app] user data lands outside the mount"
test -f "$XDG_DATA_HOME/yt-dlp-gui/history.db" || fail "no history database was created"
test -f "$XDG_DATA_HOME/yt-dlp-gui/logs/yt-dlp-gui.log" || fail "no log file was written"
case "$XDG_DATA_HOME" in
    "$ROOT_DIR"*) fail "user data landed inside the mount" ;;
esac
echo "  history.db and the log are under the throw-away HOME"

echo
echo "[app] started from an unrelated directory"
( cd / && "$APP" --version >/dev/null ) || fail "the application depends on its working directory"
echo "  works from /"

echo
echo "[app] a stale system ffmpeg does not win"
mkdir -p "$PROFILE/fakebin"
printf '#!/bin/sh\necho "ffmpeg version 4.0.0 fake"\n' > "$PROFILE/fakebin/ffmpeg"
printf '#!/bin/sh\necho "deno 1.0.0"\n' > "$PROFILE/fakebin/deno"
chmod +x "$PROFILE/fakebin/ffmpeg" "$PROFILE/fakebin/deno"
PATH="$PROFILE/fakebin:$PATH" "$APP" --diagnostics > "$PROFILE/conflict.txt"
for tool in ffmpeg deno; do
    grep -qE "^${tool}: .*- bundled" "$PROFILE/conflict.txt" \
        || fail "a system ${tool} won over the bundled one"
done
echo "  bundled ffmpeg and deno still win"

if [ "${MODE:-offline}" = offline ]; then
    echo
    echo "[app] all structural checks passed"
    exit 0
fi

echo
echo "[network] HTTPS, certificates and a real extraction"
"$APP" --check-url "$NETWORK_URL" | sed 's/^/  /'

echo
echo "[network] a watch link carrying playlist context stays one video"
"$APP" --check-url "$MIX_URL" | sed 's/^/  /'

echo
echo "[network] a real playlist still enumerates"
"$APP" --check-url "$PLAYLIST_URL" | sed 's/^/  /'

if [ "${MODE:-offline}" = network ]; then
    echo
    echo "[network] all checks passed"
    exit 0
fi

echo
echo "[integration] downloading through the bundled FFmpeg"
"$APP" --check-download "$DOWNLOAD_URL" --output "$PROFILE/downloads" | sed 's/^/  /'

echo
echo "[integration] all checks passed"
SCRIPT
}

EXPECTED_VERSION="$(python3 -c "
import json, pathlib
print(json.loads(pathlib.Path('$DIST_DIR/release-manifest.json').read_text())['version'])")"

if [ "$ON_HOST" = 1 ]; then
    printf '\n[host] running the application checks on this machine\n'
    WORK="$(mktemp -d)"
    trap 'rm -rf "$WORK"' EXIT
    ( cd "$WORK" && cp "$ARTIFACT" app.AppImage && chmod +x app.AppImage \
      && ./app.AppImage --appimage-extract >/dev/null )
    run_checks | APPRUN="$WORK/squashfs-root/AppRun" \
        EXPECTED_VERSION="$EXPECTED_VERSION" MODE="$MODE" \
        NETWORK_URL="$NETWORK_URL" DOWNLOAD_URL="$DOWNLOAD_URL" \
        MIX_URL="$MIX_URL" PLAYLIST_URL="$PLAYLIST_URL" bash
    printf '\n[validate] the AppImage passes on this host\n'
    exit 0
fi

ENGINE="${CONTAINER_ENGINE:-}"
if [ -z "$ENGINE" ]; then
    if command -v podman >/dev/null 2>&1; then ENGINE=podman
    elif command -v docker >/dev/null 2>&1; then ENGINE=docker
    else echo "error: neither podman nor docker is available" >&2; exit 1
    fi
fi
printf '[validate] clean image %s via %s\n' "$IMAGE" "$ENGINE"

# A clean machine still has the graphics libraries any desktop ships, and
# installing them needs the network. Doing that once into a local image keeps
# the offline mode genuinely offline: after the first run, no validation
# touches the network unless it was asked to.
TEST_IMAGE="localhost/yt-dlp-gui-validate:$(echo "$IMAGE" | tr ':/' '--')"
if ! "$ENGINE" image exists "$TEST_IMAGE" 2>/dev/null \
   && ! "$ENGINE" image inspect "$TEST_IMAGE" >/dev/null 2>&1; then
    printf '[validate] preparing %s (once)\n' "$TEST_IMAGE"
    "$ENGINE" run --name yt-dlp-gui-validate-prep --security-opt label=disable "$IMAGE" \
        bash -euo pipefail -c '
            export DEBIAN_FRONTEND=noninteractive
            apt-get -qq update >/dev/null
            apt-get -qq install -y --no-install-recommends \
                libgl1 libegl1 libfontconfig1 libdbus-1-3 libx11-6 libglib2.0-0 \
                ca-certificates >/dev/null
            apt-get -qq clean
        ' >/dev/null
    "$ENGINE" commit yt-dlp-gui-validate-prep "$TEST_IMAGE" >/dev/null
    "$ENGINE" rm yt-dlp-gui-validate-prep >/dev/null
fi

NETWORK_ARGS=()
[ "$MODE" = offline ] && NETWORK_ARGS+=(--network=none)

CHECKS="$(run_checks)"

"$ENGINE" run --rm \
    --security-opt label=disable \
    "${NETWORK_ARGS[@]}" \
    -v "$DIST_DIR:/artifacts:ro" \
    -e ARTIFACT_NAME="$(basename "$ARTIFACT")" \
    -e EXPECTED_VERSION="$EXPECTED_VERSION" \
    -e MODE="$MODE" \
    -e NETWORK_URL="$NETWORK_URL" \
    -e DOWNLOAD_URL="$DOWNLOAD_URL" \
    -e MIX_URL="$MIX_URL" \
    -e PLAYLIST_URL="$PLAYLIST_URL" \
    -e CHECKS="$CHECKS" \
    "$TEST_IMAGE" \
    bash -euo pipefail -c '
        echo "[clean] proving the machine is bare"
        for tool in python3 ffmpeg ffprobe deno yt-dlp; do
            command -v "$tool" >/dev/null 2>&1 \
                && { echo "  !! $tool is present; this is not a clean environment" >&2; exit 1; }
            echo "  no $tool"
        done

        cd /tmp
        cp "/artifacts/$ARTIFACT_NAME" app.AppImage
        chmod +x app.AppImage
        # Containers have no FUSE, so the AppImage is unpacked instead
        ./app.AppImage --appimage-extract >/dev/null

        APPRUN=/tmp/squashfs-root/AppRun bash -c "$CHECKS"
    '

printf '\n[validate] the AppImage works on a machine with nothing installed\n'
