#!/bin/bash

# Omarchy App Manager - Final Launcher Script

# Resolve the app folder from this script's location so the launcher works
# from any working directory (the bar widget invokes it by absolute path).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo "Omarchy App Manager"
echo "==================="

# Pick the interpreter: the bundled virtualenv when present, otherwise the
# system python (the only runtime dependency is PyQt6, packaged on Arch as
# python-pyqt6). A store-installed clone has no venv, so the fallback keeps
# the bar widget working out of the box.
PYTHON=""
if [ -x "venv/bin/python3" ]; then
    PYTHON="venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
fi

fail() {
    # The bar widget spawns this detached, so a desktop notification is the
    # only way to surface startup errors when stdout goes nowhere.
    if command -v notify-send >/dev/null 2>&1; then
        notify-send -u critical "Omarchy App Manager" "$1" 2>/dev/null
    fi
    echo ""
    echo "Error: $1" >&2
    exit 1
}

[ -n "$PYTHON" ] || fail "Python 3 not found. Install python3 and python-pyqt6."

# Verify PyQt6 is available to the chosen interpreter
if ! "$PYTHON" -c "from PyQt6.QtWidgets import QApplication" 2>/dev/null; then
    if [ "$PYTHON" = "python3" ]; then
        fail "PyQt6 not available. Install it with: sudo pacman -S python-pyqt6"
    fi
    fail "PyQt6 not installed in the virtual environment! Run: venv/bin/pip install PyQt6"
fi

# Verify the omarchy_app_manager package is importable
PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c "import omarchy_app_manager.ui_mainwindow" 2>/dev/null || \
    fail "Omarchy App Manager package not found. Please install it with: pip install -e ."

# Add src to Python path (SCRIPT_DIR was resolved at startup)
export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

# Run the application
echo ""
echo "Starting Omarchy App Manager..."
echo ""

exec "$PYTHON" -m omarchy_app_manager
