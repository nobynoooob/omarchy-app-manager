"""
Plugin manifest + bar widget contract tests.

The authoritative oracle is the Omarchy shell itself: ``shell.qml`` validates
the manifest through ``services/PluginRegistry.qml`` at load time, and the
``omarchy-plugin-validate`` CLI mirrors those checks so a plugin author can
verify before publishing.  These tests mirror the schema in Python (so they
run on machines without the shell), keep the QML bridge, icon and launcher
honest, and — when the CLI is available — stage a clean copy of the
distributable payload through the official validator.

Run with:  python -m pytest tests/test_plugin_manifest.py -v
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO / 'manifest.json'
BAR_WIDGET_PATH = REPO / 'BarWidget.qml'
RUNNER_PATH = REPO / 'run_final.sh'
ICON_PATH = REPO / 'assets' / 'omarchy-app-manager.svg'
PACKAGED_ICON_PATH = (
    REPO / 'src' / 'omarchy_app_manager' / 'assets' / 'omarchy-app-manager.svg')
VALIDATOR = Path('/usr/bin/omarchy-plugin-validate')

# The shell recognizes bar widgets by this exact kind - PluginRegistry.qml
# checks ``kinds.indexOf("bar-widget") !== -1`` - while entryPoints uses the
# camelCase key ``barWidget`` to point at the QML file.  A manifest that
# declares the kind as "barWidget" installs but never appears in the bar.
EXPECTED_KIND = 'bar-widget'
EXPECTED_ID = 'com.mostafa.omarchy-app-manager'
EXPECTED_VERSION = '1.0.0'
EXPECTED_DESCRIPTION = (
    'Fluid, high-performance AppImage and Desktop Shortcut manager with '
    'Catppuccin theme syncing, GameMode tuning, and icon auto-extraction.'
)
ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
SEMVER_RE = re.compile(r'^\d+\.\d+\.\d+$')

requires_validator = pytest.mark.skipif(
    not (VALIDATOR.exists() and os.access(VALIDATOR, os.X_OK)),
    reason='omarchy-plugin-validate not installed',
)
requires_qmllint = pytest.mark.skipif(
    shutil.which('qmllint') is None, reason='qmllint not installed')


@pytest.fixture(scope='module')
def manifest():
    assert MANIFEST_PATH.is_file(), 'manifest.json must live in the repo root'
    return json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))


def stage_plugin(dest, include_widget=True):
    """Copy the distributable payload (no venv, no caches) into ``dest``."""
    (dest / 'assets').mkdir(parents=True, exist_ok=True)
    shutil.copy2(MANIFEST_PATH, dest / 'manifest.json')
    shutil.copy2(RUNNER_PATH, dest / 'run_final.sh')
    shutil.copy2(ICON_PATH, dest / 'assets' / ICON_PATH.name)
    if include_widget:
        shutil.copy2(BAR_WIDGET_PATH, dest / 'BarWidget.qml')
    return dest


# --------------------------------------------------------------------------- #
# Manifest schema (mirrors PluginRegistry.validateManifest + the CLI checks)
# --------------------------------------------------------------------------- #
def test_manifest_parses_as_strict_json(manifest):
    assert isinstance(manifest, dict)
    # json.loads already rejects trailing commas/comments; re-serialising and
    # reparsing catches anything the first pass might have coerced.
    assert json.loads(json.dumps(manifest)) == manifest
    MANIFEST_PATH.read_text(encoding='utf-8')


def test_schema_version_is_the_json_number_one(manifest):
    schema_version = manifest['schemaVersion']
    assert isinstance(schema_version, int) and not isinstance(schema_version, bool)
    assert schema_version == 1


def test_manifest_identity(manifest):
    assert manifest['id'] == EXPECTED_ID
    assert manifest['name'] == 'OmaApp Manager'
    assert manifest['version'] == EXPECTED_VERSION
    assert SEMVER_RE.match(manifest['version'])
    assert manifest['author'] == 'Mostafa Hossam El-Din'
    assert manifest['description'] == EXPECTED_DESCRIPTION


def test_plugin_id_is_safe_for_the_registry(manifest):
    plugin_id = manifest['id']
    assert ID_RE.match(plugin_id)
    assert '..' not in plugin_id and '/' not in plugin_id
    assert not plugin_id.startswith('omarchy.')  # reserved namespace


def test_kinds_declare_a_bar_widget(manifest):
    assert manifest['kinds'] == [EXPECTED_KIND]
    # Guard against the camelCase trap explicitly: the shell would ignore it.
    assert 'barWidget' not in manifest['kinds']


def test_entry_points_are_safe_relative_paths_that_exist(manifest):
    entry_points = manifest['entryPoints']
    assert isinstance(entry_points, dict)
    assert entry_points == {'barWidget': 'BarWidget.qml'}

    for key, value in entry_points.items():
        assert isinstance(value, str) and value, f'{key} must be a path'
        assert not value.startswith('/')
        assert '..' not in value
        assert '\n' not in value
        target = REPO / value
        assert target.is_file(), f'entry point missing on disk: {value}'


def test_bar_widget_metadata_block(manifest):
    meta = manifest['barWidget']
    assert isinstance(meta, dict)
    assert meta['displayName'] == 'OmaApp Manager'
    assert meta['defaultSection'] in ('left', 'center', 'right')
    assert meta['allowMultiple'] is False


def test_icon_is_declared_present_and_not_a_symlink(manifest):
    assert manifest['icon'] == 'assets/omarchy-app-manager.svg'
    assert ICON_PATH.is_file()
    assert not ICON_PATH.is_symlink()  # the validator refuses symlinks
    assert ICON_PATH.read_text(encoding='utf-8').lstrip().startswith('<svg')


def test_icon_matches_the_packaged_asset(manifest):
    """The plugin icon and the in-app icon must not drift apart."""
    assert PACKAGED_ICON_PATH.is_file()
    assert PACKAGED_ICON_PATH.read_bytes() == ICON_PATH.read_bytes()


def test_homepage_is_a_plausible_url(manifest):
    homepage = manifest['homepage']
    assert homepage.startswith('https://') and ' ' not in homepage


def test_payload_files_are_regular_files(manifest):
    for path in (MANIFEST_PATH, BAR_WIDGET_PATH, RUNNER_PATH, ICON_PATH):
        assert path.is_file(), path
        assert not path.is_symlink(), path


# --------------------------------------------------------------------------- #
# BarWidget.qml bridge
# --------------------------------------------------------------------------- #
def _bar_widget_source():
    return BAR_WIDGET_PATH.read_text(encoding='utf-8')


def test_bar_widget_qml_exists_and_is_wellformed():
    source = _bar_widget_source()
    assert source.count('{') == source.count('}')
    assert source.lstrip().startswith('import QtQuick')


def test_bar_widget_extended_from_the_shell_base(manifest):
    source = _bar_widget_source()
    assert re.search(r'^BarWidget\s*\{', source, re.MULTILINE)
    assert 'import QtQuick' in source
    assert 'import Quickshell' in source
    assert 'import qs.Ui' in source
    assert f'moduleName: "{manifest["id"]}"' in source


def test_bar_widget_launches_the_startup_script_via_exec_detached():
    source = _bar_widget_source()
    assert 'Quickshell.execDetached(' in source
    assert source.count('Quickshell.execDetached(') == 1
    # The detached command is the repo's startup script, resolved relative to
    # the plugin folder rather than a hardcoded home directory.
    assert 'run_final.sh' in source
    assert 'pluginDir' in source and 'Qt.resolvedUrl' in source
    assert '/home/' not in source


def test_startup_script_is_executable_and_self_locating():
    assert os.access(RUNNER_PATH, os.X_OK), 'run_final.sh must be executable'
    source = RUNNER_PATH.read_text(encoding='utf-8')
    assert '-m omarchy_app_manager' in source
    # Invoked by absolute path from the bar widget: it must not depend on the
    # caller's working directory or on this developer's home folder.
    assert 'BASH_SOURCE' in source
    assert '/home/' not in source


def test_startup_script_survives_a_venv_less_store_install():
    """A git-installed clone has no venv (it is gitignored): the launcher must
    fall back to the system interpreter (python-pyqt6) and, when PyQt6 is
    missing everywhere, provision a private venv by itself - announcing
    progress and errors via notify-send, since the bar widget spawns it
    detached and a store install must need no manual setup."""
    source = RUNNER_PATH.read_text(encoding='utf-8')
    assert 'venv/bin/python3' in source       # preferred when present
    assert 'command -v python3' in source     # system fallback
    assert 'notify-send' in source
    assert 'pacman -S python-pyqt6' in source
    # Zero manual setup: first launch self-provisions PyQt6 user-locally.
    assert 'python3 -m venv venv' in source
    assert '-m pip install' in source
    assert 'requirements.txt' in source


def test_startup_script_never_executes_privileged_commands():
    """The launcher runs unsandboxed from the shell: it must never invoke
    sudo/pacman itself. Package-manager hints are allowed only as text inside
    notification/error strings."""
    source = RUNNER_PATH.read_text(encoding='utf-8')
    for line in source.splitlines():
        stripped = line.strip()
        assert not re.match(r'^(sudo|pacman)\b', stripped), (
            f'launcher must not execute privileged commands: {stripped!r}')


def _stage_runnable_plugin(tmp_path):
    """Stage just what a store clone needs: the launcher + requirements."""
    stage = tmp_path / 'plugin'
    stage.mkdir()
    shutil.copy2(RUNNER_PATH, stage / 'run_final.sh')
    shutil.copy2(REPO / 'requirements.txt', stage / 'requirements.txt')
    return stage


def _make_fake_toolchain(tmp_path, venv_creation_succeeds=True):
    """Fake python3/notify-send that record calls and simulate no PyQt6.

    ``python3`` fails the PyQt6 import probe, logs every call, and either
    creates a venv with a working interpreter (copying ``venv_python``) or
    fails the venv creation.  All behavior is driven by files in ``tmp_path``.
    """
    fakebin = tmp_path / 'fakebin'
    fakebin.mkdir()
    calls = tmp_path / 'calls.log'
    notifications = tmp_path / 'notify.log'

    venv_python = tmp_path / 'venv_python'
    venv_python.write_text(
        '#!/bin/bash\n'
        'echo "venv/bin/python3 $*" >> "$FAKE_CALLS"\n'
        'exit 0\n',
        encoding='utf-8')
    venv_python.chmod(0o755)

    python3 = fakebin / 'python3'
    python3.write_text(
        '#!/bin/bash\n'
        'echo "python3 $*" >> "$FAKE_CALLS"\n'
        'case "$*" in\n'
        '  *"from PyQt6.QtWidgets import QApplication"*) exit 1 ;;\n'
        'esac\n'
        'if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then\n'
        '  [ "$FAKE_VENV_OK" = "1" ] || exit 1\n'
        '  mkdir -p venv/bin && cp "$FAKE_VENV_SOURCE" venv/bin/python3\n'
        '  chmod +x venv/bin/python3\n'
        '  exit 0\n'
        'fi\n'
        'exit 0\n',
        encoding='utf-8')
    python3.chmod(0o755)

    notify = fakebin / 'notify-send'
    notify.write_text(
        '#!/bin/bash\n'
        'echo "$*" >> "$FAKE_NOTIFY_LOG"\n'
        'exit 0\n',
        encoding='utf-8')
    notify.chmod(0o755)

    env = {
        'PATH': f'{fakebin}:/usr/bin:/bin',
        'HOME': str(tmp_path),
        'FAKE_CALLS': str(calls),
        'FAKE_NOTIFY_LOG': str(notifications),
        'FAKE_VENV_SOURCE': str(venv_python),
        'FAKE_VENV_OK': '1' if venv_creation_succeeds else '0',
        'LC_ALL': 'C',
    }
    return calls, notifications, env


def _run_staged_launcher(stage, env):
    return subprocess.run(
        ['/bin/bash', str(stage / 'run_final.sh')],
        cwd=stage, env=env, capture_output=True, text=True, timeout=60)


def test_launcher_provisions_pyqt6_into_a_private_venv(tmp_path):
    """End-to-end: with no PyQt6 anywhere, the staged launcher creates a venv
    inside its own folder, installs from requirements.txt, notifies first,
    and then starts the app through that venv - all without sudo."""
    stage = _stage_runnable_plugin(tmp_path)
    calls, notifications, env = _make_fake_toolchain(tmp_path)

    proc = _run_staged_launcher(stage, env)

    assert proc.returncode == 0, proc.stderr
    log = calls.read_text(encoding='utf-8')
    assert 'python3 -m venv venv' in log
    assert '-m pip install' in log and 'requirements.txt' in log
    assert 'venv/bin/python3 -m omarchy_app_manager' in log
    assert (stage / 'venv' / 'bin' / 'python3').exists()
    assert 'First-time setup' in notifications.read_text(encoding='utf-8')
    assert 'sudo' not in log  # nothing privileged was executed


def test_launcher_reports_failed_provisioning_gracefully(tmp_path):
    """When the venv cannot be created or PyQt6 cannot be installed, the
    launcher must fail with a notify-send message carrying the pacman
    fallback instead of starting a broken app."""
    stage = _stage_runnable_plugin(tmp_path)
    calls, notifications, env = _make_fake_toolchain(
        tmp_path, venv_creation_succeeds=False)

    proc = _run_staged_launcher(stage, env)

    assert proc.returncode != 0
    log = calls.read_text(encoding='utf-8')
    assert '-m pip install' not in log  # no pip without a venv
    notes = notifications.read_text(encoding='utf-8')
    assert 'pacman -S python-pyqt6' in notes


@requires_qmllint
def test_qmllint_accepts_the_bar_widget():
    proc = subprocess.run(
        ['qmllint', str(BAR_WIDGET_PATH)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------- #
# Official validator (store compatibility)
# --------------------------------------------------------------------------- #
@requires_validator
def test_official_validator_accepts_the_staged_plugin(tmp_path):
    staged = stage_plugin(tmp_path / 'com.mostafa.omarchy-app-manager')
    proc = subprocess.run(
        [str(VALIDATOR), str(staged)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@requires_validator
def test_official_validator_rejects_an_incomplete_plugin(tmp_path):
    """Negative control: the validator must actually look at entry points."""
    staged = stage_plugin(tmp_path / 'broken', include_widget=False)
    proc = subprocess.run(
        [str(VALIDATOR), str(staged)], capture_output=True, text=True)
    assert proc.returncode != 0
    assert 'BarWidget.qml' in proc.stderr
