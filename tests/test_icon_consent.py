"""
Consent gating for AppImage icon extraction.

Selecting, browsing, or dropping an AppImage must never execute it: the
"runtime" is asked to ``--appimage-extract``, which runs arbitrary code.  The
real extraction therefore only happens after the user clicks "Extract icon"
and confirms the warning dialog.  Cached icons are served without execution.

Run with:  python -m pytest tests/test_icon_consent.py -v
"""

import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_app_manager import appimage_icons as icons  # noqa: E402
from omarchy_app_manager import ui_mainwindow as ui  # noqa: E402

#: Recording stand-in for the AppImage runtime: appends every execution to
#: ``{marker}`` and answers ``--appimage-extract *.png`` with a real icon.
EXTRACT_BODY = """
echo "executed:$2" >> "{marker}"
if [ "$2" = "*.png" ]; then
    mkdir -p squashfs-root/usr/share/icons/hicolor/256x256/apps
    printf 'real-icon-bytes' \\
        > squashfs-root/usr/share/icons/hicolor/256x256/apps/consent.png
fi
exit 0
"""


@pytest.fixture
def planted(tmp_path, monkeypatch):
    """A fake AppImage that records executions, plus a sandboxed icon cache."""
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_root))
    monkeypatch.delenv("OMARCHY_APPIMAGE_ICON_CACHE", raising=False)
    marker = tmp_path / "executed.log"
    # "Zzqqx" keeps the theme-icon fallback from accidentally matching.
    appimage = tmp_path / "Zzqqx-Consent.AppImage"
    appimage.write_text(
        "#!/bin/sh\n" + EXTRACT_BODY.format(marker=marker), encoding="utf-8")
    appimage.chmod(0o755)
    return appimage, marker


def wait_for_icon(dialog, app, timeout=10.0):
    """Pump the event loop until the worker thread fills the icon field."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not dialog.icon_input.text():
        app.processEvents()
        time.sleep(0.02)
    return dialog.icon_input.text()


def test_selecting_or_dropping_an_appimage_never_executes_it(qapp, planted):
    appimage, marker = planted

    dialog = ui.CategoryDialog()
    dialog.apply_prefill({'path': str(appimage)})
    assert not marker.exists()
    assert dialog.icon_input.text() == ''
    assert dialog.extract_button.isVisibleTo(dialog)

    dialog._on_exec_dropped(str(appimage))
    assert not marker.exists()
    assert dialog.extract_button.isVisibleTo(dialog)


def test_browsing_to_an_appimage_never_executes_it(qapp, planted, monkeypatch):
    appimage, marker = planted
    monkeypatch.setattr(
        ui.QFileDialog, 'getOpenFileName',
        lambda *args, **kwargs: (str(appimage), ''))

    dialog = ui.CategoryDialog()
    dialog._browse_file()

    assert not marker.exists()
    assert dialog.path_input.text() == str(appimage)
    assert dialog.extract_button.isVisibleTo(dialog)


def test_extraction_requires_explicit_confirmation(qapp, planted, monkeypatch):
    appimage, marker = planted

    dialog = ui.CategoryDialog()
    dialog.apply_prefill({'path': str(appimage)})
    monkeypatch.setattr(
        ui.CategoryDialog, '_confirm_extraction',
        lambda self, path: False)
    dialog.extract_button.click()

    assert not marker.exists()
    assert dialog.icon_input.text() == ''


def test_confirmed_extraction_runs_once_and_fills_the_icon(
        qapp, planted, monkeypatch):
    appimage, marker = planted

    dialog = ui.CategoryDialog()
    dialog.apply_prefill({'path': str(appimage)})
    monkeypatch.setattr(
        ui.CategoryDialog, '_confirm_extraction',
        lambda self, path: True)
    dialog.extract_button.click()

    icon_path = wait_for_icon(dialog, qapp)
    assert marker.exists()  # executed exactly now, after consent
    assert marker.read_text().startswith('executed:')
    assert icon_path and Path(icon_path).is_file()
    assert not dialog.extract_button.isVisibleTo(dialog)


def test_cached_icon_prefills_without_execution(qapp, planted):
    appimage, marker = planted
    assert icons.extract_appimage_icon(appimage)  # populate the cache once
    marker.unlink()  # forget that run; anything new is a re-execution

    dialog = ui.CategoryDialog()
    dialog.apply_prefill({'path': str(appimage)})

    assert not marker.exists()
    assert dialog.icon_input.text()  # served from the cache
    assert not dialog.extract_button.isVisibleTo(dialog)
