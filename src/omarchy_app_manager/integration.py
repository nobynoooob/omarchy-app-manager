"""
Omarchy App Manager - system-wide integration.

Three opt-in integrations register the app itself with the desktop:

* :func:`install_desktop_entry` - a launcher in
  ``~/.local/share/applications/omarchy-app-manager.desktop`` plus the app
  icon in the user's hicolor theme, so the entry immediately shows up in the
  Omarchy launcher menu (``update-desktop-database`` is invoked best-effort).
* :func:`install_waybar_module` - a Waybar custom-module snippet at
  ``~/.config/waybar/modules/omarchy-appmanager.json``, ready to be
  referenced as ``"custom/app-manager"`` from a Waybar config.
* :func:`install_omarchy_widget` - a tiny Omarchy shell (Quickshell) bar
  widget written under ``~/.config/omarchy/plugins/<user>.app-manager`` and
  wired into the bar layout in ``~/.config/omarchy/shell.json``.

All paths honour ``XDG_DATA_HOME`` / ``XDG_CONFIG_HOME`` (and ``HOME``), and
the applications directory additionally honours ``OMARCHY_APPS_DIR`` like
``desktop_manager`` does - the test-suite sandboxes everything through those.
User-actionable failures raise :class:`IntegrationError`.

First run: :func:`run_first_run_integration` installs the launcher
automatically the first time the app is ever started (the UI drives it on a
worker thread).  A marker under ``XDG_STATE_HOME`` records that the decision
was made, so a user who later unchecks the toggle is never re-registered.
``OMARCHY_APPMANAGER_NO_FIRST_RUN`` vetoes the whole thing (used by the
test-suite).
"""

import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_ID = 'omarchy-app-manager'
APP_NAME = 'Omarchy App Manager'
APP_COMMENT = 'Manage AppImages and custom desktop shortcuts'
APP_CATEGORIES = 'Utility;Settings;System;'

WAYBAR_MODULE_ID = 'custom/app-manager'
WAYBAR_MODULE_FILE = 'omarchy-appmanager.json'

OMARCHY_WIDGET_GLYPH = '\U000F003B'  # nf-md-apps grid glyph
OMARCHY_WIDGET_SECTION = 'left'
OMARCHY_WIDGET_LABEL = 'Launch Omarchy App Manager'

FIRST_RUN_DISABLE_ENV = 'OMARCHY_APPMANAGER_NO_FIRST_RUN'


class IntegrationError(RuntimeError):
    """A user-actionable failure (missing config, unwritable path, ...)."""


# --------------------------------------------------------------------------- #
# Paths and launch command
# --------------------------------------------------------------------------- #
def project_root():
    """Repository root (``src/omarchy_app_manager/integration.py`` -> root)."""
    return Path(__file__).resolve().parent.parent.parent


def get_data_home():
    override = os.environ.get('XDG_DATA_HOME')
    return Path(override) if override else Path.home() / '.local' / 'share'


def get_config_home():
    override = os.environ.get('XDG_CONFIG_HOME')
    return Path(override) if override else Path.home() / '.config'


def get_applications_dir():
    """Directory holding user .desktop files (OMARCHY_APPS_DIR-aware)."""
    override = os.environ.get('OMARCHY_APPS_DIR')
    if override:
        return Path(override)
    return get_data_home() / 'applications'


def app_icon_source():
    """The bundled application icon shipped inside the package."""
    return Path(__file__).resolve().parent / 'assets' / 'omarchy-app-manager.svg'


def app_icon_install_path():
    return get_data_home() / 'icons' / 'hicolor' / 'scalable' / 'apps' / f'{APP_ID}.svg'


def get_launch_argv():
    """Absolute command that starts this application.

    Prefers the virtualenv console script this package installs, then the
    repository's ``run_final.sh``, and finally the running interpreter.
    """
    entry = Path(sys.executable).with_name(APP_ID)
    if entry.is_file():
        return [str(entry)]
    script = project_root() / 'run_final.sh'
    if script.is_file():
        return [str(script)]
    return [sys.executable, '-m', 'omarchy_app_manager']


_EXEC_SPECIALS = re.compile(r'[ \t\n"\'\\`$&|;<>()*?#\[\]{}~]')


def quote_exec_token(token):
    """Quote one Exec= argument per the freedesktop spec when needed."""
    if not token:
        return '""'
    if not _EXEC_SPECIALS.search(token):
        return token
    escaped = (token.replace('\\', '\\\\').replace('"', '\\"')
               .replace('`', '\\`').replace('$', '\\$'))
    return f'"{escaped}"'


def exec_line(argv=None):
    """The full ``Exec=`` value for the launch command."""
    if argv is None:
        argv = get_launch_argv()
    return ' '.join(quote_exec_token(token) for token in argv)


# --------------------------------------------------------------------------- #
# Applications-menu launcher
# --------------------------------------------------------------------------- #
def desktop_entry_path():
    return get_applications_dir() / f'{APP_ID}.desktop'


def is_desktop_entry_installed():
    return desktop_entry_path().exists()


def _desktop_entry_text(icon_path):
    return (
        '[Desktop Entry]\n'
        'Type=Application\n'
        'Version=1.0\n'
        f'Name={APP_NAME}\n'
        f'Comment={APP_COMMENT}\n'
        f'Exec={exec_line()}\n'
        f'Icon={icon_path}\n'
        'Terminal=false\n'
        f'Categories={APP_CATEGORIES}\n'
        'StartupNotify=true\n'
    )


def install_desktop_entry():
    """Write the launcher + icon and refresh the applications database."""
    try:
        icon_bytes = app_icon_source().read_bytes()
    except OSError as exc:
        raise IntegrationError(f'Bundled application icon is missing: {exc}') from exc

    desktop_file = desktop_entry_path()
    icon_dest = app_icon_install_path()
    try:
        desktop_file.parent.mkdir(parents=True, exist_ok=True)
        icon_dest.parent.mkdir(parents=True, exist_ok=True)
        icon_dest.write_bytes(icon_bytes)
        desktop_file.write_text(_desktop_entry_text(icon_dest), encoding='utf-8')
    except OSError as exc:
        raise IntegrationError(f'Cannot write {desktop_file}: {exc}') from exc

    update_desktop_database(desktop_file.parent)
    return desktop_file


def uninstall_desktop_entry():
    """Remove the launcher (and its icon); True when a file was removed."""
    removed = False
    desktop_file = desktop_entry_path()
    try:
        if desktop_file.exists():
            desktop_file.unlink()
            removed = True
        icon = app_icon_install_path()
        if icon.exists():
            icon.unlink()
    except OSError as exc:
        raise IntegrationError(f'Cannot remove {desktop_file}: {exc}') from exc

    if removed:
        update_desktop_database(desktop_file.parent)
    return removed


def update_desktop_database(apps_dir):
    """Best-effort ``update-desktop-database <dir>`` so menus refresh at once."""
    binary = shutil.which('update-desktop-database')
    if not binary:
        return False
    try:
        subprocess.run(
            [binary, str(apps_dir)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


# --------------------------------------------------------------------------- #
# Waybar custom module
# --------------------------------------------------------------------------- #
def waybar_module_path():
    return get_config_home() / 'waybar' / 'modules' / WAYBAR_MODULE_FILE


def is_waybar_module_installed():
    return waybar_module_path().exists()


def waybar_module_snippet():
    """The config a Waybar setup gains.

    A full JSON object so the file can be dropped into an ``include``d
    modules directory and referenced as ``"custom/app-manager"``.
    """
    return {
        WAYBAR_MODULE_ID: {
            'format': f' {OMARCHY_WIDGET_GLYPH} ',
            'tooltip-format': OMARCHY_WIDGET_LABEL,
            'on-click': exec_line(),
        },
    }


def waybar_module_json():
    return json.dumps(waybar_module_snippet(), indent=4, ensure_ascii=False) + '\n'


def install_waybar_module():
    target = waybar_module_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(waybar_module_json(), encoding='utf-8')
    except OSError as exc:
        raise IntegrationError(f'Cannot write {target}: {exc}') from exc
    return target


def uninstall_waybar_module():
    target = waybar_module_path()
    if not target.exists():
        return False
    try:
        target.unlink()
    except OSError as exc:
        raise IntegrationError(f'Cannot remove {target}: {exc}') from exc
    return True


# --------------------------------------------------------------------------- #
# Omarchy shell (bar) widget
# --------------------------------------------------------------------------- #
def omarchy_username():
    try:
        return getpass.getuser() or 'user'
    except (KeyError, OSError):
        return 'user'


def omarchy_plugin_id():
    return f'{omarchy_username()}.app-manager'


def omarchy_plugin_dir():
    return get_config_home() / 'omarchy' / 'plugins' / omarchy_plugin_id()


def omarchy_shell_config_path():
    return get_config_home() / 'omarchy' / 'shell.json'


def _load_shell_config(path):
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError as exc:
        raise IntegrationError(f'Cannot read {path}: {exc}') from exc
    try:
        config = json.loads(raw)
    except ValueError as exc:
        raise IntegrationError(f'{path} is not valid JSON: {exc}') from exc
    if not isinstance(config, dict):
        raise IntegrationError(f'{path} does not contain a JSON object.')
    return config


def _layout_section(config):
    """The bar layout list our widget is placed in; raises when unusable."""
    bar = config.get('bar')
    layout = bar.get('layout') if isinstance(bar, dict) else None
    section = layout.get(OMARCHY_WIDGET_SECTION) if isinstance(layout, dict) else None
    if not isinstance(section, list):
        raise IntegrationError(
            f'shell.json has no bar.layout.{OMARCHY_WIDGET_SECTION} list; '
            'add the widget to the bar manually.')
    return section


def _widget_layout_entry():
    return {'id': omarchy_plugin_id()}


def _has_widget_entry(section):
    return any(
        isinstance(entry, dict) and entry.get('id') == omarchy_plugin_id()
        for entry in section
    )


def is_omarchy_widget_installed():
    """True when shell.json's layout already contains our widget."""
    path = omarchy_shell_config_path()
    if not path.exists():
        return False
    try:
        config = json.loads(path.read_text(encoding='utf-8'))
        section = _layout_section(config)
    except (OSError, ValueError, IntegrationError):
        return False
    return _has_widget_entry(section)


def _write_shell_config(shell_path, config):
    """Back up shell.json, then rewrite it atomically-ish."""
    stamp = time.time_ns()
    backup = shell_path.with_name(f'{shell_path.name}.bak.{stamp}')
    try:
        shutil.copy2(shell_path, backup)
        shell_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8')
    except OSError as exc:
        raise IntegrationError(f'Cannot update {shell_path}: {exc}') from exc


def _plugin_manifest_text():
    manifest = {
        'schemaVersion': 1,
        'id': omarchy_plugin_id(),
        'name': 'App Manager',
        'version': '1.0.0',
        'author': omarchy_username(),
        'license': 'MIT',
        'description': 'Launch Omarchy App Manager from the bar.',
        'kinds': ['bar-widget'],
        'entryPoints': {'barWidget': 'BarWidget.qml'},
        'barWidget': {
            'displayName': 'App Manager',
            'description': 'Open the Omarchy App Manager',
            'category': 'System',
            'allowMultiple': False,
            'defaultSection': OMARCHY_WIDGET_SECTION,
        },
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False) + '\n'


def _plugin_qml_text():
    def js_string(value):
        return json.dumps(value, ensure_ascii=False)

    argv = json.dumps(get_launch_argv(), ensure_ascii=False)
    return (
        'import QtQuick\n'
        'import Quickshell\n'
        'import qs.Ui\n'
        '\n'
        'BarWidget {\n'
        '  id: root\n'
        f'  moduleName: {js_string(omarchy_plugin_id())}\n'
        '\n'
        '  implicitWidth: button.implicitWidth\n'
        '  implicitHeight: button.implicitHeight\n'
        '\n'
        '  WidgetButton {\n'
        '    id: button\n'
        '    anchors.fill: parent\n'
        '    bar: root.bar\n'
        f'    text: {js_string(OMARCHY_WIDGET_GLYPH)}\n'
        '    fontFamily: "JetBrainsMono Nerd Font"\n'
        f'    tooltipText: {js_string(OMARCHY_WIDGET_LABEL)}\n'
        '    horizontalMargin: 8.5\n'
        '    onPressed: function(buttonCode) {\n'
        '      if (buttonCode === Qt.LeftButton)\n'
        f'        Quickshell.execDetached({argv})\n'
        '    }\n'
        '  }\n'
        '}\n'
    )


def _notify_shell_rescan():
    """Best-effort runtime hint so the shell picks the new plugin up."""
    binary = shutil.which('omarchy-shell')
    if not binary:
        return False
    try:
        subprocess.run(
            [binary, 'shell', 'rescanPlugins'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def install_omarchy_widget():
    """Create the bar widget plugin and add it to the shell layout.

    Returns the plugin directory.  Raises :class:`IntegrationError` when
    ``shell.json`` is missing or has no usable layout to place the widget in.
    """
    shell_path = omarchy_shell_config_path()
    if not shell_path.exists():
        raise IntegrationError(
            f'{shell_path} was not found; the Omarchy shell config is required '
            'to place the bar widget.')
    config = _load_shell_config(shell_path)
    section = _layout_section(config)

    plugin_dir = omarchy_plugin_dir()
    try:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / 'manifest.json').write_text(
            _plugin_manifest_text(), encoding='utf-8')
        (plugin_dir / 'BarWidget.qml').write_text(
            _plugin_qml_text(), encoding='utf-8')
    except OSError as exc:
        raise IntegrationError(f'Cannot write plugin files: {exc}') from exc

    if not _has_widget_entry(section):
        section.append(_widget_layout_entry())
        _write_shell_config(shell_path, config)
        _notify_shell_rescan()
    return plugin_dir


def uninstall_omarchy_widget():
    """Remove the widget from the bar layout (plugin files are kept).

    Returns True when a layout entry was removed.
    """
    shell_path = omarchy_shell_config_path()
    if not shell_path.exists():
        return False
    config = _load_shell_config(shell_path)
    section = _layout_section(config)
    remaining = [
        entry for entry in section
        if not (isinstance(entry, dict)
                and entry.get('id') == omarchy_plugin_id())
    ]
    if len(remaining) == len(section):
        return False
    section[:] = remaining
    _write_shell_config(shell_path, config)
    return True


# --------------------------------------------------------------------------- #
# First-run registration
# --------------------------------------------------------------------------- #
def get_state_home():
    override = os.environ.get('XDG_STATE_HOME')
    return Path(override) if override else Path.home() / '.local' / 'state'


def first_run_marker_path():
    """File recording that the first-run decision was already made."""
    return get_state_home() / APP_ID / 'first-run-done'


def first_run_disabled():
    """True when ``OMARCHY_APPMANAGER_NO_FIRST_RUN`` vetoes auto-registration."""
    return bool(os.environ.get(FIRST_RUN_DISABLE_ENV))


def is_first_run_complete():
    return first_run_marker_path().exists()


def mark_first_run_complete():
    """Record that the first-run decision was made (installed or opted out).

    Best-effort: the marker is a nicety, so an unwritable state dir still
    leaves the rest of the app fully functional.
    """
    marker = first_run_marker_path()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass


def should_run_first_run_setup():
    """True when a launch should kick off the background auto-registration."""
    return not first_run_disabled() and not is_first_run_complete()


def run_first_run_integration():
    """First-launch registration of the applications-menu launcher.

    Runs on a worker thread and only ever acts once: the marker under
    ``XDG_STATE_HOME`` records that the decision was made, so a user who
    unchecks the gear-menu toggle later is never re-registered behind their
    back.  Returns the desktop entry path when one exists afterwards, or
    ``None`` when nothing was done (already complete, disabled) or the
    install failed - a failure is simply retried on the next launch.
    """
    if first_run_disabled() or is_first_run_complete():
        return None
    if is_desktop_entry_installed():
        mark_first_run_complete()
        return desktop_entry_path()
    try:
        installed = install_desktop_entry()
    except IntegrationError:
        return None  # e.g. read-only home; retry on the next launch
    mark_first_run_complete()
    return installed
