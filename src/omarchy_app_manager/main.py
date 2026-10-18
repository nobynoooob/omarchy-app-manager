from ui_mainwindow import OmarchyAppManager
import sys
from PyQt6.QtWidgets import QApplication

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Omarchy App Manager")
    app.setApplicationVersion("1.0.0")

    window = OmarchyAppManager()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
