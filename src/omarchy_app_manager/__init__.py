"""
Omarchy App Manager
A modern, elegant desktop application for managing AppImages and shortcuts
in the user's application menu (~/.local/share/applications/).
"""

from .appimage_icons import (
    cached_appimage_icon_path, extract_appimage_icon, get_icon_cache_dir,
    is_appimage,
)
from .desktop_manager import (
    get_applications_dir, get_installed_apps, create_desktop_file,
    update_desktop_file, delete_desktop_file, ensure_appimage_executable,
    parse_desktop_file, parse_category, first_exec_token, command_is_available,
    split_exec, normalize_exec, quote_command, is_system_entry, CATEGORY_MAP,
    compose_exec_line, unwrap_exec_command, wrap_exec_command,
    GAMEMODE_WRAPPER, PERF_GAMEMODE_KEY, PERF_PRIME_KEY,
)
from .integration import (
    IntegrationError, desktop_entry_path, exec_line, first_run_disabled,
    first_run_marker_path, get_launch_argv, install_desktop_entry,
    install_omarchy_widget, install_waybar_module, is_desktop_entry_installed,
    is_first_run_complete, is_omarchy_widget_installed,
    is_waybar_module_installed, mark_first_run_complete, omarchy_plugin_id,
    run_first_run_integration, should_run_first_run_setup,
    uninstall_desktop_entry, uninstall_omarchy_widget,
    uninstall_waybar_module, update_desktop_database, waybar_module_json,
    waybar_module_path, waybar_module_snippet,
)
from .theme import detect_system_theme, load_theme

__all__ = [
    'get_applications_dir',
    'get_installed_apps',
    'create_desktop_file',
    'update_desktop_file',
    'delete_desktop_file',
    'ensure_appimage_executable',
    'parse_desktop_file',
    'parse_category',
    'first_exec_token',
    'command_is_available',
    'split_exec',
    'normalize_exec',
    'quote_command',
    'is_system_entry',
    'CATEGORY_MAP',
    'compose_exec_line',
    'unwrap_exec_command',
    'wrap_exec_command',
    'GAMEMODE_WRAPPER',
    'PERF_GAMEMODE_KEY',
    'PERF_PRIME_KEY',
    'detect_system_theme',
    'load_theme',
    'cached_appimage_icon_path',
    'extract_appimage_icon',
    'get_icon_cache_dir',
    'is_appimage',
    'IntegrationError',
    'desktop_entry_path',
    'exec_line',
    'first_run_disabled',
    'first_run_marker_path',
    'get_launch_argv',
    'install_desktop_entry',
    'install_omarchy_widget',
    'install_waybar_module',
    'is_desktop_entry_installed',
    'is_first_run_complete',
    'is_omarchy_widget_installed',
    'is_waybar_module_installed',
    'mark_first_run_complete',
    'omarchy_plugin_id',
    'run_first_run_integration',
    'should_run_first_run_setup',
    'uninstall_desktop_entry',
    'uninstall_omarchy_widget',
    'uninstall_waybar_module',
    'update_desktop_database',
    'waybar_module_json',
    'waybar_module_path',
    'waybar_module_snippet',
]
