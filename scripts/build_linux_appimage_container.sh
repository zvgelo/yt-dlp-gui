#!/usr/bin/env bash
# Build the AppImage inside an old-glibc container, for portability.
#
#   scripts/build_linux_appimage_container.sh [--allow-dirty]
#
# An AppImage is only as portable as the glibc it was linked against. Building
# on a current distribution produces a file that refuses to start on anything
# older, so the release build happens on Debian 11 - glibc 2.31 - which covers
# Debian 11, Ubuntu 20.04, RHEL 9, Fedora 34 and everything newer.
#
# The manylinux images would give an even older glibc, but their interpreters
# are built without a shared libpython, which PyInstaller requires. The
# official python images are built with --enable-shared.
#
# The checkout is mounted **read-only** and copied into a scratch directory
# inside the container. A build has no business writing to a developer's
# working tree, and a bug in it must not be able to remove tracked files. Only
# `dist/` and the download cache are writable, and only finished artifacts
# travel back.
#
# `scripts/build_linux_appimage.sh` does the same work directly on the host and
# is the faster choice while developing; its output is only guaranteed to run
# on machines at least as new as the one that built it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Debian 11 is old enough to be portable and still has a shared libpython
IMAGE="${YTDLP_GUI_BUILD_IMAGE:-python:3.12-bullseye}"

ENGINE="${CONTAINER_ENGINE:-}"
if [ -z "$ENGINE" ]; then
    if command -v podman >/dev/null 2>&1; then
        ENGINE=podman
    elif command -v docker >/dev/null 2>&1; then
        ENGINE=docker
    else
        echo "error: neither podman nor docker is available" >&2
        echo "  install one, or run scripts/build_linux_appimage.sh on this host" >&2
        exit 1
    fi
fi

# The helper binaries are always unpacked inside the container from the shared
# download cache. `--skip-runtime-deps` is a host-build convenience and would
# only leave the scratch copy without them, so it is dropped here.
BUILD_ARGS=()
for argument in "$@"; do
    case "$argument" in
        --skip-runtime-deps) ;;
        *) BUILD_ARGS+=("$argument") ;;
    esac
done

HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

# Rootless podman already maps container root onto the invoking user, so files
# land with the right owner. Docker's container root is the host's root, and
# the artifacts have to be handed back explicitly.
ROOTLESS=false
if [ "$ENGINE" = podman ]; then
    ROOTLESS="$(podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null || echo false)"
fi
CHOWN_ARTIFACTS=1
[ "$ROOTLESS" = true ] && CHOWN_ARTIFACTS=0

# git inside the container refuses to read a bind-mounted repository owned by
# somebody else, so both answers are resolved here and passed in
HOST_COMMIT="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || true)"
if [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
    HOST_TREE_STATE=dirty
else
    HOST_TREE_STATE=clean
fi

# Recorded in the release manifest, so an artifact can be traced to its toolchain
IMAGE_ID="$("$ENGINE" image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null || true)"

mkdir -p "$ROOT/dist" "$ROOT/build/runtime-cache"

printf '[container] engine %s (rootless: %s)\n' "$ENGINE" "$ROOTLESS"
printf '[container] image  %s\n' "$IMAGE"
printf '[container] commit %s (%s)\n' "${HOST_COMMIT:-unknown}" "$HOST_TREE_STATE"

# SELinux: the checkout is never relabelled. Disabling the label check for this
# one container is far less invasive than rewriting the xattrs of every file a
# developer owns, which is what a `:z` mount does.
"$ENGINE" run --rm \
    --security-opt label=disable \
    -v "$ROOT:/src:ro" \
    -v "$ROOT/dist:/out:rw" \
    -v "$ROOT/build/runtime-cache:/cache:rw" \
    -w /tmp \
    -e APPIMAGE_EXTRACT_AND_RUN=1 \
    -e PYTHON=/work/build/container-venv/bin/python \
    -e YTDLP_GUI_COMMIT="$HOST_COMMIT" \
    -e YTDLP_GUI_TREE_STATE="$HOST_TREE_STATE" \
    -e YTDLP_GUI_BUILD_IMAGE="$IMAGE" \
    -e YTDLP_GUI_BUILD_IMAGE_ID="$IMAGE_ID" \
    -e CHOWN_ARTIFACTS="$CHOWN_ARTIFACTS" \
    -e HOST_UID="$HOST_UID" \
    -e HOST_GID="$HOST_GID" \
    "$IMAGE" \
    bash -euo pipefail -c '
        echo "[container] installing build dependencies"
        export DEBIAN_FRONTEND=noninteractive
        apt-get -qq update >/dev/null
        apt-get -qq install -y --no-install-recommends \
            libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
            libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-util1 \
            libxcb-xkb1 libxkbcommon0 libxkbcommon-x11-0 \
            libgl1 libegl1 libfontconfig1 libdbus-1-3 \
            desktop-file-utils file zsync \
            >/dev/null

        echo "[container] copying the checkout into a scratch directory"
        mkdir -p /work
        # Everything the build reads and nothing it does not: no .git, no
        # virtualenvs, no previous output, and above all no development
        # runtime - a release must never pick up a binary a developer fetched.
        tar -C /src -cf - \
            --exclude=./.git \
            --exclude=./.venv \
            --exclude=./.venv-build \
            --exclude=./.runtime \
            --exclude=./build \
            --exclude=./dist \
            --exclude=./mockup \
            --exclude=*/__pycache__ \
            --exclude=*.pyc \
            . | tar -C /work -xf -
        mkdir -p /work/build /work/dist
        ln -s /cache /work/build/runtime-cache

        echo "[container] creating the build environment"
        python3 -m venv /work/build/container-venv
        /work/build/container-venv/bin/pip -q install --upgrade pip
        /work/build/container-venv/bin/pip -q install -r /work/packaging/requirements-build.txt

        echo "[container] building"
        /work/scripts/build_linux_appimage.sh '"${BUILD_ARGS[*]:-}"'

        echo "[container] handing the artifacts back"
        # The build already removed anything stale before writing, so what it
        # produced is the complete, current release
        rm -rf /out/linux
        cp -a /work/dist/linux /out/linux
        if [ "$CHOWN_ARTIFACTS" = 1 ]; then
            chown -R "$HOST_UID:$HOST_GID" /out
        fi
    '

# The build is not finished until the files belong to whoever ran it
OWNER="$(stat -c '%u' "$ROOT/dist/linux" 2>/dev/null || echo "$HOST_UID")"
if [ "$OWNER" != "$HOST_UID" ]; then
    echo "[container] correcting artifact ownership"
    if [ "$ENGINE" = podman ]; then
        podman unshare chown -R "$HOST_UID:$HOST_GID" "$ROOT/dist" || true
    else
        chown -R "$HOST_UID:$HOST_GID" "$ROOT/dist" 2>/dev/null || true
    fi
fi

printf '\n[container] artifacts in %s/dist/linux\n' "$ROOT"
ls -ln "$ROOT/dist/linux" 2>/dev/null || true
