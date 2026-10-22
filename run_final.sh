#!/bin/bash

# OmaApp Manager - Final Launcher Script
#
# Store installs (`omarchy plugin add ... --enable`) need no manual setup.
# The launcher self-checks its runtime on every start: bundled venv first,
# then the system interpreter with python-pyqt6. When PyQt6 is missing
# entirely, the first launch provisions a private, user-local venv inside the
# plugin folder and installs PyQt6 from PyPI - no sudo, nothing outside the
# plugin folder. The install is hash-verified against the pinned versions in
# requirements.txt, so the installed bytes are the ones recorded in this
# commit. The bar widget spawns this script detached, so progress and errors
# are announced via notify-send.

# Resolve the app folder from this script's location so the launcher works
# from any working directory (the bar widget invokes it by absolute path).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo "OmaApp Manager"
echo "==================="

notify() {
    if command -v notify-send >/dev/null 2>&1; then
        notify-send "OmaApp Manager" "$1" 2>/dev/null
    fi
}

fail() {
    # The bar widget spawns this detached, so a desktop notification is the
    # only way to surface startup errors when stdout goes nowhere.
    if command -v notify-send >/dev/null 2>&1; then
        notify-send -u critical "OmaApp Manager" "$1" 2>/dev/null
    fi
    echo ""
    echo "Error: $1" >&2
    exit 1
}

# True when the given interpreter (relative path or command name) imports PyQt6.
has_pyqt6() {
    [ -n "$1" ] || return 1
    command -v "$1" >/dev/null 2>&1 || return 1
    "$1" -c "from PyQt6.QtWidgets import QApplication" 2>/dev/null
}

# Prefer the bundled virtualenv, then the system interpreter. Both are
# zero-cost when present; provisioning only runs when neither has PyQt6.
PYTHON=""
if has_pyqt6 "venv/bin/python3"; then
    PYTHON="venv/bin/python3"
elif has_pyqt6 "python3"; then
    PYTHON="python3"
fi

if [ -z "$PYTHON" ]; then
    # First launch without PyQt6 anywhere: create a private venv and install
    # PyQt6 into it. User-local only: no sudo, no system packages touched.
    command -v python3 >/dev/null 2>&1 || \
        fail "Python 3 not found. Install PyQt6 with: sudo pacman -S python-pyqt6"
    notify "First-time setup: installing PyQt6 into a private environment (one time, may take a minute)..."
    if [ ! -x venv/bin/python3 ]; then
        python3 -m venv venv >/dev/null 2>&1 || \
            fail "Could not create a private Python environment. Install PyQt6 instead with: sudo pacman -S python-pyqt6"
    fi
    # Hash-verified install: requirements.txt pins every version and records
    # the artifact hashes, so the bytes installed are exactly the ones
    # recorded in this commit. pip refuses any download that does not match,
    # and --only-binary keeps pip from building anything from source.
    if ! venv/bin/python3 -m pip install --quiet --disable-pip-version-check --no-input \
            --require-hashes --only-binary=:all: \
            -r "$SCRIPT_DIR/requirements.txt" >> "venv/provision.log" 2>&1; then
        fail "Could not install the verified PyQt6 build (offline, or no recorded hash for this Python version). Install it instead with: sudo pacman -S python-pyqt6"
    fi
    has_pyqt6 "venv/bin/python3" || \
        fail "PyQt6 setup failed. Install it instead with: sudo pacman -S python-pyqt6"
    PYTHON="venv/bin/python3"
fi

# Verify the omarchy_app_manager package is importable
PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c "import omarchy_app_manager.ui_mainwindow" 2>/dev/null || \
    fail "OmaApp Manager package not found. Please install it with: pip install -e ."

# Add src to Python path (SCRIPT_DIR was resolved at startup)
export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

# Run the application
echo ""
echo "Starting OmaApp Manager..."
echo ""

exec "$PYTHON" -m omarchy_app_manager
