#!/usr/bin/env bash
# Give a source checkout the same helper binaries a release bundles.
#
#   ./scripts/bootstrap_dev_runtime.sh            # FFmpeg, ffprobe and Deno
#   ./scripts/bootstrap_dev_runtime.sh --only deno
#
# Without this, `./run.sh` starts with no JavaScript runtime and YouTube
# extraction is degraded, while the packaged build works - a difference that is
# confusing and entirely avoidable.
#
# A thin wrapper: the pinned versions, URLs, checksums and download cache all
# live in scripts/runtime_deps.py, shared with the release build. Running it
# again is cheap; archives are cached and nothing is re-downloaded.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
    if [ -x "$ROOT/.venv/bin/python" ]; then
        PYTHON="$ROOT/.venv/bin/python"
    else
        PYTHON="$(command -v python3 || true)"
    fi
fi
[ -n "$PYTHON" ] && [ -x "$PYTHON" ] || {
    echo "error: no Python interpreter found; create .venv or set PYTHON=" >&2
    exit 1
}

exec "$PYTHON" "$ROOT/scripts/runtime_deps.py" --development "$@"
