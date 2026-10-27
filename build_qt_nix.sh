#!/bin/sh
# Build on the target OS: a Linux executable or a macOS application bundle.
set -eu

cd -- "$(dirname -- "$0")"

fail() {
    printf '\n%s\n' "$1" >&2
    exit 1
}

case "$(uname -s)" in
    Linux) platform=linux ;;
    Darwin) platform=macos ;;
    *) fail 'This script supports Linux and macOS. Build on the target operating system.' ;;
esac

# Example: PYTHON=python3.12 ./build_qt_nix.sh
PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' ||
    fail 'Python 3.12 or newer is required. Set PYTHON to a suitable interpreter.'

if [ ! -x .venv-qt/bin/python ]; then
    "$PYTHON" -m venv .venv-qt ||
        fail 'Could not create .venv-qt. Install venv support for your Python interpreter and retry.'
fi

.venv-qt/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' ||
    fail 'The existing .venv-qt needs Python 3.12 or newer. Move it aside and rerun this script.'

.venv-qt/bin/python -m pip install --upgrade pip || fail 'Could not upgrade pip.'
.venv-qt/bin/python -m pip install -r requirements_qt.txt 'pyinstaller>=6,<7' ||
    fail 'Could not install build dependencies. Review the error above.'

.venv-qt/bin/python -m unittest discover -s tests -q || fail 'Model tests failed.'

# Scope the offscreen setting to each test; preserve the caller's environment.
for test_script in \
    tests/qt_preview_smoke.py \
    tests/qt_grid_smoke.py \
    tests/qt_editor_smoke.py \
    tests/qt_segments_smoke.py \
    tests/qt_junction_markers_smoke.py \
    tests/qt_consumed_tips_smoke.py
do
    QT_QPA_PLATFORM=offscreen .venv-qt/bin/python "$test_script" ||
        fail "Qt check failed: $test_script"
done

if [ "$platform" = macos ]; then
    # PyInstaller recommends onedir for macOS .app bundles.
    set -- --onedir --windowed
else
    set -- --onefile
fi

.venv-qt/bin/python -m PyInstaller --noconfirm --clean "$@" \
    --exclude-module tkinter --name VerilogCanvasQt qt_editor.py ||
    fail 'Packaging failed. Review the error above.'

if [ "$platform" = macos ]; then
    printf '\nReady: dist/VerilogCanvasQt.app\n'
else
    printf '\nReady: dist/VerilogCanvasQt\n'
fi
printf 'Full Qt editor. Open existing .vsch files or create a new schematic.\n'
