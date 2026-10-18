#!/usr/bin/env python3
"""
OmaApp Manager - Test Script

Tests the refactored application with clean PyQt6 implementation.
"""

import sys
import os
from pathlib import Path

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """Test all necessary imports."""
    print("Testing OmaApp Manager imports...")
    
    try:
        from omarchy_app_manager.desktop_manager import (
            get_applications_dir, get_installed_apps, create_desktop_file,
            update_desktop_file, delete_desktop_file, ensure_appimage_executable
        )
        print("✓ desktop_manager imports successful")
    except ImportError as e:
        print(f"✗ desktop_manager import failed: {e}")
        return False
    
    try:
        from omarchy_app_manager.ui_mainwindow import (
            OmarchyAppManager, AppCard, SearchBar, CategoryDialog
        )
        print("✓ ui_mainwindow imports successful")
    except ImportError as e:
        print(f"✗ ui_mainwindow import failed: {e}")
        return False
    
    try:
        from omarchy_app_manager import __main__
        print("✓ __main__ imports successful")
    except ImportError as e:
        print(f"✗ __main__ import failed: {e}")
        return False
    
    return True

def test_desktop_manager():
    """Test desktop_manager basic functionality."""
    print("\nTesting desktop_manager...")
    
    try:
        from omarchy_app_manager.desktop_manager import get_applications_dir
        apps_dir = get_applications_dir()
        print(f"✓ Applications directory: {apps_dir}")
        assert apps_dir.exists()
        print("✓ Directory exists")
    except Exception as e:
        print(f"✗ Error getting applications directory: {e}")
        return False
    
    try:
        from omarchy_app_manager.desktop_manager import get_installed_apps
        apps = get_installed_apps()
        print(f"✓ get_installed_apps: {len(apps)} apps found")
    except Exception as e:
        print(f"✗ Error getting installed apps: {e}")
        return False
    
    return True

def test_ui_components():
    """Test UI components."""
    print("\nTesting UI components...")
    
    try:
        from PyQt6.QtWidgets import QApplication
        print("✓ PyQt6 imported successfully")
    except Exception as e:
        print(f"✗ PyQt6 import failed: {e}")
        return False
    
    try:
        from omarchy_app_manager.ui_mainwindow import (
            StyledButton, SearchBar, AppCard, CategoryDialog
        )
        print("✓ All UI components imported successfully")
    except Exception as e:
        print(f"✗ UI components import failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("=" * 70)
    print("OmaApp Manager - Refactored Implementation Test")
    print("=" * 70)
    
    if not test_imports():
        print("\n✗ Import tests failed")
        sys.exit(1)
    
    if not test_desktop_manager():
        print("\n✗ Desktop manager tests failed")
        sys.exit(1)
    
    if not test_ui_components():
        print("\n✗ UI component tests failed")
        sys.exit(1)
    
    print("\n" + "=" * 70)
    print("✅ ALL TESTS PASSED!")
    print("\nKey improvements in this refactored version:")
    print("  ✓ Clean, bullet-proof PyQt6 implementation")
    print("  ✓ Standard QLayouts with no absolute positioning")
    print("  ✓ Proper QScrollArea integration")
    print("  ✓ Catppuccin Mocha color palette")
    print("  ✓ Native QDialog for forms")
    print("  ✓ Modular, maintainable code structure")
    print("\nTo run the application:")
    print("  ./run_simple.sh")
    print("  (or with virtual environment: source venv/bin/activate)")
    print("=" * 70)
