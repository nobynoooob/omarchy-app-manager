"""
Tests for system-wide integration: the app's own launcher entry, the Waybar
module snippet, and the Omarchy shell bar widget.

Everything runs against sandboxed XDG directories (never the developer's real
``~/.local/share`` / ``~/.config``), with a fake ``update-desktop-database``
on ``$PATH`` and the live-shell rescan IPC disabled.
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_app_manager import integration  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Sandbox HOME and the XDG base directories used by ``integration``."""
    home = tmp_path / "home"
    data = tmp_path / "data"
    config = tmp_path / "config"
    state = tmp_path / "state"
    for directory in (home, data, config, state):
        directory.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.delenv("OMARCHY_APPS_DIR", raising=False)
    monkeypatch.setattr(integration, "_notify_shell_rescan", lambda: False)
    return tmp_path


@pytest.fixture
def shell_config(sandbox):
    """A minimal but realistic shell.json with a bar layout."""
    path = integration.omarchy_shell_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "bar": {
            "layout": {
                "left": [{"id": "omaplug"}],
                "right": [{"id": "omarchy.tray"}],
            },
        },
        "idle": {"lock": 600},
    }
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


def fake_update_desktop_database(tmp_path, monkeypatch):
    """Put a recording ``update-desktop-database`` first on $PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "udd-args.txt"
    script = bin_dir / "update-desktop-database"
    script.write_text(
        f'#!/bin/sh\nprintf "%s" "$1" > "{marker}"\n', encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv(
        "PATH", bin_dir.as_posix() + os.pathsep + os.environ.get("PATH", ""))
    return marker


# --------------------------------------------------------------------------- #
# Launch command and Exec= quoting
# --------------------------------------------------------------------------- #
def test_launch_argv_points_at_an_executable(sandbox):
    argv = integration.get_launch_argv()
    assert argv
    assert Path(argv[0]).is_file()


def test_exec_line_quotes_specials():
    line = integration.exec_line(
        ["/opt/my app/run.sh", "--flag", 'say "hi"', "a$b", "back\\slash"])
    assert line == (
        '"/opt/my app/run.sh" --flag "say \\"hi\\"" "a\\$b" '
        '"back\\\\slash"'
    )


def test_exec_line_defaults_to_launch_argv(sandbox):
    assert integration.exec_line() == integration.exec_line(
        integration.get_launch_argv())


# --------------------------------------------------------------------------- #
# Applications-menu launcher
# --------------------------------------------------------------------------- #
def test_install_desktop_entry_writes_spec_fields(sandbox, tmp_path, monkeypatch):
    marker = fake_update_desktop_database(tmp_path, monkeypatch)

    desktop_file = integration.install_desktop_entry()

    assert desktop_file == integration.desktop_entry_path()
    content = desktop_file.read_text(encoding="utf-8")
    assert "Name=OmaApp Manager" in content
    assert "Comment=Manage AppImages and custom desktop shortcuts" in content
    assert "Terminal=false" in content
    assert "Categories=Utility;Settings;System;" in content
    assert f"Exec={integration.exec_line()}" in content
    assert "[Desktop Entry]" in content

    icon = integration.app_icon_install_path()
    assert icon.is_file()
    assert icon.read_bytes() == integration.app_icon_source().read_bytes()
    assert f"Icon={icon}" in content

    # The menu database was refreshed for the directory holding the entry.
    assert marker.read_text() == str(desktop_file.parent)
    assert integration.is_desktop_entry_installed()


def test_desktop_entry_roundtrip_is_idempotent(sandbox, tmp_path, monkeypatch):
    fake_update_desktop_database(tmp_path, monkeypatch)

    first = integration.install_desktop_entry().read_text(encoding="utf-8")
    integration.install_desktop_entry()
    assert integration.desktop_entry_path().read_text(encoding="utf-8") == first

    assert integration.uninstall_desktop_entry() is True
    assert not integration.desktop_entry_path().exists()
    assert not integration.app_icon_install_path().exists()
    assert integration.is_desktop_entry_installed() is False
    assert integration.uninstall_desktop_entry() is False


# --------------------------------------------------------------------------- #
# Waybar module
# --------------------------------------------------------------------------- #
def test_waybar_module_written_with_expected_snippet(sandbox):
    target = integration.install_waybar_module()

    assert target == integration.waybar_module_path()
    assert integration.is_waybar_module_installed()

    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert list(data) == ["custom/app-manager"]
    module = data["custom/app-manager"]
    assert module["format"] == " \U000F003B "
    assert module["tooltip-format"] == "Launch OmaApp Manager"
    assert module["on-click"] == integration.exec_line()
    # The Nerd Font glyph survives as a literal character, not an escape.
    assert "\U000F003B" in raw


def test_waybar_module_uninstall(sandbox):
    integration.install_waybar_module()
    assert integration.uninstall_waybar_module() is True
    assert not integration.is_waybar_module_installed()
    assert integration.uninstall_waybar_module() is False


# --------------------------------------------------------------------------- #
# Omarchy shell widget
# --------------------------------------------------------------------------- #
def test_install_omarchy_widget_creates_plugin_and_layout_entry(sandbox, shell_config):
    plugin_dir = integration.install_omarchy_widget()

    assert plugin_dir == integration.omarchy_plugin_dir()
    manifest = json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == integration.omarchy_plugin_id()
    assert manifest["kinds"] == ["bar-widget"]
    assert manifest["entryPoints"]["barWidget"] == "BarWidget.qml"
    assert manifest["barWidget"]["defaultSection"] == "left"
    assert manifest["author"] == integration.omarchy_username()

    qml = (plugin_dir / "BarWidget.qml").read_text(encoding="utf-8")
    assert integration.omarchy_plugin_id() in qml
    assert "Launch OmaApp Manager" in qml
    assert integration.get_launch_argv()[0] in qml
    assert "Quickshell.execDetached(" in qml

    config = json.loads(shell_config.read_text(encoding="utf-8"))
    left = config["bar"]["layout"]["left"]
    assert left == [{"id": "omaplug"}, {"id": integration.omarchy_plugin_id()}]
    # Untouched parts survive the rewrite, and a backup was taken.
    assert config["bar"]["layout"]["right"] == [{"id": "omarchy.tray"}]
    assert config["idle"] == {"lock": 600}
    assert list(shell_config.parent.glob("shell.json.bak.*"))

    assert integration.is_omarchy_widget_installed()


def test_install_omarchy_widget_is_idempotent(sandbox, shell_config):
    integration.install_omarchy_widget()
    integration.install_omarchy_widget()

    config = json.loads(shell_config.read_text(encoding="utf-8"))
    assert config["bar"]["layout"]["left"] == [
        {"id": "omaplug"}, {"id": integration.omarchy_plugin_id()},
    ]
    assert len(list(shell_config.parent.glob("shell.json.bak.*"))) == 1


def test_omarchy_widget_install_requests_shell_rescan(sandbox, shell_config, monkeypatch):
    calls = []
    monkeypatch.setattr(
        integration, "_notify_shell_rescan",
        lambda: calls.append(True) or True)

    integration.install_omarchy_widget()
    assert calls == [True]


def test_uninstall_omarchy_widget_removes_only_its_entry(sandbox, shell_config):
    integration.install_omarchy_widget()

    assert integration.uninstall_omarchy_widget() is True
    config = json.loads(shell_config.read_text(encoding="utf-8"))
    assert config["bar"]["layout"]["left"] == [{"id": "omaplug"}]
    assert not integration.is_omarchy_widget_installed()
    # The plugin files stay on disk so re-enabling is instant.
    assert (integration.omarchy_plugin_dir() / "BarWidget.qml").is_file()
    assert integration.uninstall_omarchy_widget() is False


def test_omarchy_widget_requires_shell_config(sandbox):
    with pytest.raises(integration.IntegrationError) as excinfo:
        integration.install_omarchy_widget()
    assert "shell.json" in str(excinfo.value)
    assert not integration.omarchy_plugin_dir().exists()


def test_omarchy_widget_rejects_malformed_shell_config(sandbox):
    path = integration.omarchy_shell_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(integration.IntegrationError):
        integration.install_omarchy_widget()
    assert path.read_text(encoding="utf-8") == "{ not json"
    assert not integration.omarchy_plugin_dir().exists()
    assert integration.is_omarchy_widget_installed() is False


def test_omarchy_widget_reports_missing_layout(sandbox):
    path = integration.omarchy_shell_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"idle": {"lock": 600}}), encoding="utf-8")

    with pytest.raises(integration.IntegrationError) as excinfo:
        integration.install_omarchy_widget()
    assert "bar.layout.left" in str(excinfo.value)
    assert not integration.omarchy_plugin_dir().exists()


# --------------------------------------------------------------------------- #
# UI integration menu
# --------------------------------------------------------------------------- #
def make_window(monkeypatch):
    from omarchy_app_manager.ui_mainwindow import OmarchyAppManager

    window = OmarchyAppManager()
    monkeypatch.setattr(window, "_show_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(window, "_show_warning", lambda *args, **kwargs: None)
    return window


def test_window_has_integration_button(qapp, sandbox, monkeypatch):
    window = make_window(monkeypatch)
    assert window.integration_button.glyph == "gear"
    assert window.integration_button.toolTip() == "System integration"


def test_integration_menu_toggles_all_three_integrations(
        qapp, sandbox, shell_config, monkeypatch, tmp_path):
    fake_update_desktop_database(tmp_path, monkeypatch)
    window = make_window(monkeypatch)

    window._refresh_integration_menu()
    assert not window.desktop_action.isChecked()
    assert not window.waybar_action.isChecked()
    assert not window.omarchy_action.isChecked()

    window.desktop_action.trigger()
    assert window.desktop_action.isChecked()
    assert integration.desktop_entry_path().is_file()

    window.waybar_action.trigger()
    assert window.waybar_action.isChecked()
    assert integration.waybar_module_path().is_file()

    window.omarchy_action.trigger()
    assert window.omarchy_action.isChecked()
    assert integration.is_omarchy_widget_installed()

    window.desktop_action.trigger()
    window.waybar_action.trigger()
    window.omarchy_action.trigger()
    assert not window.desktop_action.isChecked()
    assert not window.waybar_action.isChecked()
    assert not window.omarchy_action.isChecked()
    assert not integration.desktop_entry_path().exists()
    assert not integration.waybar_module_path().exists()
    assert not integration.is_omarchy_widget_installed()


def test_integration_failure_warns_and_unchecks(qapp, sandbox, monkeypatch):
    warnings = []
    window = make_window(monkeypatch)
    monkeypatch.setattr(
        window, "_show_warning",
        lambda title, text: warnings.append((title, text)))

    window._refresh_integration_menu()
    window.omarchy_action.trigger()  # shell.json missing in the sandbox

    assert not window.omarchy_action.isChecked()
    assert warnings
    assert "shell.json" in warnings[0][1]


def test_copy_waybar_snippet_puts_json_on_clipboard(qapp, sandbox, monkeypatch):
    from PyQt6.QtWidgets import QApplication

    window = make_window(monkeypatch)
    window._refresh_integration_menu()

    window.copy_waybar_action.trigger()

    clipboard_text = QApplication.clipboard().text()
    assert "custom/app-manager" in clipboard_text
    assert "Launch OmaApp Manager" in clipboard_text


# --------------------------------------------------------------------------- #
# First-run auto-registration
# --------------------------------------------------------------------------- #
def enable_first_run(monkeypatch):
    """Undo the conftest kill-switch for a single test."""
    monkeypatch.delenv(integration.FIRST_RUN_DISABLE_ENV, raising=False)


def wait_until(qapp, predicate, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        qapp.processEvents()
        time.sleep(0.01)
    return predicate()


def test_first_run_auto_installs_launcher_without_blocking(
        qapp, sandbox, monkeypatch, tmp_path):
    enable_first_run(monkeypatch)
    fake_update_desktop_database(tmp_path, monkeypatch)

    events = []
    started = threading.Event()
    release = threading.Event()
    real_install = integration.install_desktop_entry

    def parked_install():
        events.append("start")
        started.set()
        # The test decides when the install finishes.  On an aborted test the
        # timeout raises (instead of installing) so nothing escapes the
        # sandbox after the environment is restored at teardown.
        if not release.wait(timeout=5):
            raise integration.IntegrationError("test aborted before release")
        result = real_install()
        events.append("end")
        return result

    monkeypatch.setattr(integration, "install_desktop_entry", parked_install)

    window = make_window(monkeypatch)  # must return while the install is parked
    assert started.wait(timeout=5), "the background task never started"
    assert "end" not in events, "window construction waited for the install"

    release.set()
    assert wait_until(qapp, lambda: "end" in events)
    assert integration.desktop_entry_path().is_file()
    assert integration.is_first_run_complete()

    # The bridge refreshes the toggle on the GUI thread, without any manual
    # menu interaction, the moment the background install finishes.
    assert wait_until(qapp, lambda: window.desktop_action.isChecked())


def test_startup_toggles_reflect_installed_state(qapp, sandbox, monkeypatch, tmp_path):
    fake_update_desktop_database(tmp_path, monkeypatch)
    integration.install_desktop_entry()
    integration.mark_first_run_complete()

    window = make_window(monkeypatch)

    assert window.desktop_action.isChecked()
    assert not window.waybar_action.isChecked()
    assert not window.omarchy_action.isChecked()


def test_first_run_runs_only_once_across_launches(qapp, sandbox, monkeypatch, tmp_path):
    from omarchy_app_manager import ui_mainwindow as ui

    enable_first_run(monkeypatch)
    fake_update_desktop_database(tmp_path, monkeypatch)

    calls = []
    real_install = integration.install_desktop_entry

    def counting_install():
        calls.append(True)
        return real_install()

    monkeypatch.setattr(integration, "install_desktop_entry", counting_install)

    make_window(monkeypatch)  # first launch
    assert wait_until(qapp, lambda: integration.is_first_run_complete())
    assert calls == [True]

    # The next launch must not schedule anything at all.
    assert ui.schedule_first_run_integration(ui._FirstRunBridge()) is False
    assert integration.run_first_run_integration() is None
    assert calls == [True]


def test_opt_out_survives_next_launch(qapp, sandbox, monkeypatch, tmp_path):
    fake_update_desktop_database(tmp_path, monkeypatch)
    integration.install_desktop_entry()
    integration.mark_first_run_complete()

    window = make_window(monkeypatch)
    window._refresh_integration_menu()
    assert window.desktop_action.isChecked()

    enable_first_run(monkeypatch)  # auto-registration is active again
    window.desktop_action.trigger()  # ... but the user unchecks it

    assert not window.desktop_action.isChecked()
    assert not integration.desktop_entry_path().exists()
    assert integration.run_first_run_integration() is None
    assert not integration.desktop_entry_path().exists()


def test_first_run_failure_is_retried_on_next_launch(sandbox, monkeypatch, tmp_path):
    enable_first_run(monkeypatch)
    fake_update_desktop_database(tmp_path, monkeypatch)

    failing = {"active": True}
    real_install = integration.install_desktop_entry

    def flaky_install():
        if failing["active"]:
            raise integration.IntegrationError("disk full")
        return real_install()

    monkeypatch.setattr(integration, "install_desktop_entry", flaky_install)

    assert integration.run_first_run_integration() is None
    assert not integration.is_first_run_complete()
    assert integration.should_run_first_run_setup()

    failing["active"] = False
    assert integration.run_first_run_integration() == integration.desktop_entry_path()
    assert integration.is_first_run_complete()


def test_first_run_disabled_by_env(sandbox):
    assert integration.first_run_disabled()
    assert not integration.should_run_first_run_setup()
    assert integration.run_first_run_integration() is None
    assert not integration.desktop_entry_path().exists()
    assert not integration.is_first_run_complete()
