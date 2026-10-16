#!/bin/sh
# Set up the Qt environment and launch VerilogCanvas on Linux/macOS.
set -eu

cd -- "$(dirname -- "$0")"

fail() {
    printf '\n%s\n' "$1" >&2
    exit 1
}

# Override the interpreter with, for example: PYTHON=python3.12 ./run_qt_unix.sh
PYTHON=${PYTHON:-python3}
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    fail 'Python 3.12 or newer is required. Set PYTHON to a suitable interpreter.'
fi

if [ ! -x .venv-qt/bin/python ]; then
    "$PYTHON" -m venv .venv-qt || fail 'Could not create .venv-qt. Install venv support for your Python interpreter and retry.'
fi

.venv-qt/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' ||
    fail 'The existing .venv-qt needs Python 3.12 or newer. Move it aside and rerun this script.'

if ! .venv-qt/bin/python -c 'import PySide6' >/dev/null 2>&1; then
    .venv-qt/bin/python -m pip install -r requirements_qt.txt ||
        fail 'Dependency installation failed. Check the error above and retry.'
fi

exec .venv-qt/bin/python qt_editor.py "$@"
