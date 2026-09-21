#!/usr/bin/env bash
# MonopInk launcher (macOS / Linux).
#
#   ./monopink.sh           start the web interface
#   ./monopink.sh --help    command line usage
#   ./monopink.sh setup     (re)create the Python environment
#
# The first run creates a private Python environment in .venv/ and installs
# the two dependencies (pyserial, Pillow).  Nothing is installed system-wide.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"

find_python() {
    for c in python3 python; do
        if command -v "$c" >/dev/null 2>&1 &&
           "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
            echo "$c"
            return 0
        fi
    done
    return 1
}

setup() {
    local py
    if ! py="$(find_python)"; then
        echo "MonopInk needs Python 3.8 or newer." >&2
        echo "  macOS : brew install python   (or https://www.python.org/downloads/)" >&2
        echo "  Linux : sudo apt install python3 python3-venv" >&2
        exit 1
    fi
    echo "== Creating the Python environment in .venv/ ($("$py" --version))"
    rm -rf "$VENV"
    if ! "$py" -m venv "$VENV"; then
        echo "Could not create a virtual environment. On Debian/Ubuntu: sudo apt install python3-venv" >&2
        exit 1
    fi
    "$VENV/bin/python" -m pip install --disable-pip-version-check -q --upgrade pip
    "$VENV/bin/python" -m pip install --disable-pip-version-check -q -r "$DIR/requirements.txt"
    echo "== Ready."
}

if [ "${1:-}" = "setup" ]; then
    setup
    exec "$VENV/bin/python" -m monopink doctor
fi

if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c "import serial, PIL" 2>/dev/null; then
    setup
fi

cd "$DIR"
exec "$VENV/bin/python" -m monopink "$@"
