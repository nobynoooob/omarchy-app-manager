#!/usr/bin/env python3
"""
OmaApp Manager
A modern, elegant desktop application for managing AppImages and shortcuts
in the user's application menu (~/.local/share/applications/).
"""

import sys

from PyQt6.QtWidgets import QApplication
from .ui_mainwindow import OmarchyAppManager

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("OmaApp Manager")
    app.setApplicationVersion("1.0.0")

    window = OmarchyAppManager()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
