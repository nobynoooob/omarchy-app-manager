# OmaApp Manager

A modern, elegant desktop application for managing AppImages and shortcuts
in the user's application menu (~/.local/share/applications/), plus an Omarchy
bar-widget launcher.

## Install

### Omarchy plugin store (recommended — no manual setup)

```sh
omarchy plugin add https://github.com/nobynoooob/omarchy-app-manager --enable
```

Adds the **OmaApp Manager** widget to your Omarchy bar (left section by
default). No manual setup steps are required: `run_final.sh` self-checks its
runtime on every start and uses the bundled `venv/` when present, otherwise
the system interpreter with `python-pyqt6`. If PyQt6 is missing entirely, the
first launch provisions a private, user-local `venv/` inside the plugin folder
and installs PyQt6 there with pip — no `sudo`, nothing outside the plugin
folder. The one-time setup is announced via a desktop notification.

Arch users who prefer the system package can install it up front and the
launcher will use it directly:

```sh
sudo pacman -S python-pyqt6   # optional
```

Optional: `gamemode` / `gamemoderun` (`sudo pacman -S gamemode`) powers the
GameMode launch wrapper; the app works without it.

### Manual / development install (fallback)

```sh
git clone https://github.com/nobynoooob/omarchy-app-manager.git
cd omarchy-app-manager
python3 -m venv venv
venv/bin/pip install -e .
./run_final.sh
```

Launching the app directly is always possible with
`PYTHONPATH=src venv/bin/python3 -m omarchy_app_manager`.

## Usage

Click the grid glyph in the bar to open OmaApp Manager. From there you can add
AppImages or shortcuts, search and filter installed entries, and launch, edit,
open the containing folder, or delete any entry. GameMode / prime-GPU
wrappers, icon extraction, and Catppuccin theme syncing are built in.

Selecting or dropping an AppImage never executes it. Importing the icon
embedded in an AppImage is an explicit **Extract icon** action guarded by a
warning dialog, because extraction runs the file (`--appimage-extract`) with
your permissions. Icons imported before are reused from the cache without
executing anything.

## Configure

Move the widget to another bar section:

```sh
omarchy bar move com.mostafa.omarchy-app-manager --section center
```

## Remove

```sh
omarchy plugin remove com.mostafa.omarchy-app-manager
```

## Overview

This is a sophisticated, feature-rich desktop application built with PyQt6
that provides a comprehensive solution for managing application shortcuts,
particularly AppImages, in the Linux ecosystem.

## Key Features

### Core Functionality
- **Dashboard / App List View**: Clean, organized display of all managed applications
- **Search Functionality**: Instant filtering of applications as you type
- **Add/Edit Application Wizard**: Guided process for creating new app entries
- **Automatic .desktop File Generation**: Seamless management of desktop entry files
- **Delete/Uninstall Support**: Safe removal of application shortcuts

### Advanced UI/UX
- **Modern Dark Theme**: Deep slate background matching modern rice themes
- **Card-Based Layout**: Elegant, rounded-corner app cards with generous padding
- **Smooth Animations**: Hover effects, fade transitions, button scale animations
- **Professional Typography**: Modern sans-serif font stack for clean readability
- **File Icon Support**: PNG/SVG icon preview and selection

### Technical Highlights
- **Cross-Platform**: Designed for Linux/Wayland with Hyprland compatibility
- **Error Handling**: Robust error management for file operations and permissions
- **Modular Architecture**: Clean separation of concerns with dedicated modules
- **Performance Optimized**: Efficient file I/O and responsive UI

## Technology Stack

- **Language**: Python 3.8+
- **GUI Framework**: PyQt6 (v6.11.0+)
- **Target Environment**: Linux/Wayland (Hyprland friendly)
- **Desktop Integration**: Integration with XDG Base Directory Specification

## Quick Start

See [Install](#install) above for the store command and the manual fallback.
Once installed, click the grid glyph in the bar to open the app.

## Project Structure

```
omarchy-app-manager/
├── manifest.json               # Omarchy plugin manifest (bar widget)
├── BarWidget.qml               # Quickshell bar-widget bridge
├── run_final.sh                # Launcher (self-provisioning)
├── src/omarchy_app_manager/
│   ├── ui_mainwindow.py        # UI components and animations
│   ├── desktop_manager.py      # Handles .desktop file operations
│   ├── styles.py               # Design system / QSS
│   ├── theme.py                # Catppuccin theme syncing
│   ├── appimage_icons.py       # Icon extraction and caching
│   └── integration.py          # System integration
├── pyproject.toml              # Package configuration
├── requirements.txt            # Dependency list
└── tests/                      # Pytest suite
```

## Usage Guide

### Adding New Applications

1. Click the "Add Application" button in the top-right corner
2. Select an AppImage or executable file using the file dialog
3. Enter a display name for the application
4. Choose an icon (PNG or SVG format)
5. Select a category from the dropdown
6. Click "Save" to create the .desktop entry

### Managing Applications

- **View**: Browse all installed applications in the dashboard
- **Search**: Use the search bar to instantly filter applications by name
- **Edit**: Click the "Edit" button on any app card to modify details
- **Delete**: Click the "Delete" button to remove an application with confirmation

## Development

### Running Tests

Run the test suite to verify functionality:

```bash
./run_tests.sh
```

### Building a Distribution

For package distribution, use the configured `pyproject.toml` with modern build tools:

```bash
pip install build
python -m build
```

## Contributing

We welcome contributions to improve this application. Please follow the existing code style and ensure comprehensive testing before submitting pull requests.

## System Requirements

This application is designed for modern Linux desktop environments, particularly:

- **Wayland** as the display server
- **Hyprland** as the window manager (optional but recommended)
- **XDG Base Directory Specification** compliant systems
- **Python 3.8** or higher
- **PyQt6** library

The application will also work on traditional X11 setups, though some visual effects may differ.

## Features

- **Dashboard / App List View**: Displays all custom apps managed by the tool
- **Add / Edit App Wizard**: Complete file picker, name input, icon selector, category assignment
- **Automatic .desktop File Generation**: Automatically writes, updates, or deletes .desktop files
- **Delete / Uninstall**: Easily remove app shortcuts with confirmation

## UI/UX & Animation Requirements (Crucial)

- **Theme**: Deep dark mode palette matching modern rice themes
- **Layout**: Clean card-based layout with generous padding and rounded corners
- **Animations**: Smooth hover effects, transitions, and button feedback
- **Typography**: Clean, modern sans-serif font stack

## Notes

- The application is optimized for modern Linux desktop environments
- It uses PyQt6 for a smooth, modern user experience
- All .desktop files are created in `~/.local/share/applications/` as per XDG Base Directory Specification
- The application automatically ensures AppImages are executable
- The UI features modern animations and a clean, professional design

## Troubleshooting

### If you encounter errors:

1. **Missing PyQt6**: the launcher provisions it automatically on first run; if that fails (e.g. offline), install it with `sudo pacman -S python-pyqt6`
2. **Permission Issues**: Ensure the application has write access to `~/.local/share/applications/`
3. **Display Issues**: Try running with a different display server if Wayland is not available

## Future Enhancements

Potential features for future versions:

- **Plugin Architecture**: Extend functionality with third-party plugins
- **Theme Support**: User-customizable themes and color schemes
- **Batch Operations**: Multiple application management
- **Import/Export**: Backup and restore application configurations
- **Remote Management**: Network-based application deployment

## Support

For issues or questions, please refer to the project documentation or open an issue in the repository.

## About

OmaApp Manager is a modern, elegant desktop application designed to easily manage AppImages and shortcuts in the user's application menu.

## License

MIT — see [LICENSE](LICENSE).
