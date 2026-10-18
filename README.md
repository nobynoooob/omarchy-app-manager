# OmaApp Manager

A modern, elegant desktop application for managing AppImages and shortcuts
in the user's application menu (~/.local/share/applications/).

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

### Prerequisites

- Python 3.8 or higher
- Linux system with Wayland support (recommended for optimal experience)
- PyQt6 library

### Installation

1. **Clone the Repository**

   ```bash
   git clone <repository-url>
   cd omarchy-app-manager
   ```

2. **Set Up Environment**

   The project includes a virtual environment. Activate it with:

   ```bash
   source venv/bin/activate  # On Linux/macOS
   # Or
   venv\\Scripts\\activate    # On Windows
   ```

3. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   # Or install directly with pip
   pip install -e .
   ```

4. **Run the Application**

   ```bash
   ./run.sh
   # or
   source venv/bin/activate && python3 -m omarchy_app_manager
   ```

## Project Structure

```
omarchy-app-manager/
├── src/
│   └── omarchy_app_manager/
│       ├── __init__.py
│       ├── __main__.py
│       ├── main.py
│       ├── desktop_manager.py      # Handles .desktop file operations
│       └── ui_mainwindow.py        # UI components and animations
├── pyproject.toml              # Package configuration
├── README.md                   # Project documentation
├── requirements.txt            # Dependency list
└── run.sh                      # Launch script
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

## License

MIT License

## System Requirements

This application is designed for modern Linux desktop environments, particularly:

- **Wayland** as the display server
- **Hyprland** as the window manager (optional but recommended)
- **XDG Base Directory Specification** compliant systems
- **Python 3.8** or higher
- **PyQt6** library

The application will also work on traditional X11 setups, though some visual effects may differ.

## Installation

1. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Launch Application**

   ```bash
   ./run.sh
   ```

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

## Installation

This application is designed for Linux systems with Wayland support (Hyprland friendly).

### System Requirements

- Python 3.8 or higher
- Linux distribution
- Wayland display server (Hyprland recommended)

### Installing Dependencies

```bash
pip install -r requirements.txt
```

### Running the Application

```bash
./run.sh
```

### Building the Application

```bash
pip install build
python -m build
```

## Notes

- The application is optimized for modern Linux desktop environments
- It uses PyQt6 for a smooth, modern user experience
- All .desktop files are created in `~/.local/share/applications/` as per XDG Base Directory Specification
- The application automatically ensures AppImages are executable
- The UI features modern animations and a clean, professional design

## Troubleshooting

### If you encounter errors:

1. **Missing PyQt6**: Install the required dependencies
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
