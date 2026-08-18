#!/usr/bin/env bash
# Runs the application from the sources, using .venv when one is present.
set -euo pipefail
cd "$(dirname "$0")"

# The helper binaries a release bundles have to be fetched once for a source
# checkout. Say so rather than starting with a degraded YouTube extraction that
# only shows up later as a missing format. Nothing is downloaded here: a
# hundreds-of-megabytes fetch hidden inside every launch would be worse than
# the problem it solves.
if [[ -z "${YTDLP_GUI_SKIP_RUNTIME_HINT:-}" ]]; then
    runtime_dir=".runtime/linux-$(uname -m)"
    if [[ ! -x "$runtime_dir/deno" ]] && ! command -v deno >/dev/null 2>&1; then
        echo "note: no JavaScript runtime found, so some YouTube formats will be missing." >&2
        echo "      fetch the same one the releases bundle with:" >&2
        echo "        ./scripts/bootstrap_dev_runtime.sh" >&2
        echo >&2
    fi
fi

if [[ -x .venv/bin/python ]]; then
    exec .venv/bin/python main.py "$@"
fi
exec python3 main.py "$@"
