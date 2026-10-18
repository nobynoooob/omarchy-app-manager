#!/bin/bash

# Omarchy App Manager - Final Launcher Script

# Resolve the app folder from this script's location so the launcher works
# from any working directory (the bar widget invokes it by absolute path).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo "Omarchy App Manager"
echo "==================="

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Error: Virtual environment not found!"
    echo "Please run: python3 -m venv venv"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Verify PyQt6 is installed
python3 -c "from PyQt6.QtWidgets import QApplication; print('✓ PyQt6 is available')" 2>/dev/null || {
    echo ""
    echo "Error: PyQt6 not installed in virtual environment!"
    echo "Please run: pip install PyQt6"
    exit 1
}

# Verify omarchy_app_manager package is available
python3 -c "
import sys
sys.path.insert(0, 'src')
try:
    import omarchy_app_manager.ui_mainwindow
    print('✓ Omarchy App Manager package is available')
except ImportError as e:
    print(f'✗ Omarchy App Manager not available: {e}')
    sys.exit(1)
" 2>/dev/null || {
    echo ""
    echo "Error: Omarchy App Manager package not found!"
    echo "Please install it with: pip install -e ."
    exit 1
}

# Add src to Python path (SCRIPT_DIR was resolved at startup)
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"

# Run the application
echo ""
echo "Starting Omarchy App Manager..."
echo ""
echo "If the window doesn't appear, it may be starting in the background."
echo ""

# Start the application
python3 -m omarchy_app_manager
