"""
Drag & drop tests.

Simulate QDragEnterEvent / QDragMoveEvent / QDragLeaveEvent / QDropEvent for
the dashboard (window, card container, viewport), the dialog drop zones and
the drag-feedback states, plus the filename -> display-name and icon-detection
helpers. All drags reference files in tmp dirs; nothing touches the real HOME.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent,
    QPixmap,
)
from PyQt6.QtWidgets import QApplication  # noqa: E402

from omarchy_app_manager import ui_mainwindow as ui  # noqa: E402
from omarchy_app_manager.ui_mainwindow import (  # noqa: E402
    CategoryDialog, OmarchyAppManager, detect_icon_for_path, is_executable_drop,
    is_image_drop, suggest_app_name,
)


# --------------------------------------------------------------------------- #
# Helpers to build synthetic drag events
# --------------------------------------------------------------------------- #
def file_mime(*paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    return mime


def _bind_mime(event, mime):
    """Keep the QMimeData referenced by the event.

    PyQt6 does not take ownership of the mime data passed to synthetic drag
    events; without this the garbage collector frees it and ``mimeData()``
    segfaults (real drags are owned by QDrag, so this is test-only).
    """
    event._drop_mime_keepalive = mime
    return event


def drag_enter(mime, pos=(200, 200)):
    return _bind_mime(QDragEnterEvent(
        QPoint(*pos), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier), mime)


def drag_move(mime, pos=(200, 200)):
    return _bind_mime(QDragMoveEvent(
        QPoint(*pos), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier), mime)


def drag_leave():
    return QDragLeaveEvent()


def drop(mime, pos=(200, 200)):
    return _bind_mime(QDropEvent(
        QPointF(*pos), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier), mime)


def make_png(path, color="#ff8800"):
    """Write a real (solid-color) PNG so icon loading succeeds."""
    pixmap = QPixmap(24, 24)
    pixmap.fill(QColor(color))
    assert pixmap.save(str(path))


def capture_dialogs(monkeypatch):
    """Stub ``CategoryDialog.exec`` so drops don't block on the modal loop."""
    captured = {}

    def fake_exec(dialog):
        captured['path'] = dialog.path_input.text()
        captured['name'] = dialog.name_input.text()
        captured['icon'] = dialog.icon_input.text()
        return 0  # rejected -> nothing is written to disk

    monkeypatch.setattr(ui.CategoryDialog, "exec", fake_exec)
    return captured


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    monkeypatch.setenv("OMARCHY_APPS_DIR", str(apps_dir))
    return apps_dir


@pytest.fixture
def window(qapp, sandbox):
    win = OmarchyAppManager()
    yield win
    win.close()


@pytest.fixture
def appimage(tmp_path):
    path = tmp_path / "Liner-0.1.35.AppImage"
    path.write_bytes(b"AppImage-ish")
    return path


@pytest.fixture
def png_icon(tmp_path):
    path = tmp_path / "icon.png"
    make_png(path)
    return path


@pytest.fixture
def stray_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("just a text file")
    return path


# --------------------------------------------------------------------------- #
# Filename -> display name
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("filename,expected", [
    ("Liner-0.1.35.AppImage", "Liner"),
    ("super_tux_kart.sh", "Super Tux Kart"),
    ("python3-helper.py", "Python3 Helper"),
    ("Firefox.appimage", "Firefox"),
    ("UltimMC-4.0.AppImage", "UltimMC"),
])
def test_suggest_app_name(tmp_path, filename, expected):
    assert suggest_app_name(tmp_path / filename) == expected


# --------------------------------------------------------------------------- #
# Drop validation
# --------------------------------------------------------------------------- #
def test_is_executable_drop_accepts_appimages_scripts_and_binaries(tmp_path):
    appimage = tmp_path / "Liner.AppImage"          # not yet +x, still accepted
    appimage.write_bytes(b"x")
    script = tmp_path / "tool.sh"
    script.write_text("#!/bin/sh\n")
    plain_script = tmp_path / "setup.py"
    plain_script.write_text("print('hi')\n")
    binary = tmp_path / "mytool"
    binary.write_text("")
    binary.chmod(0o755)

    assert is_executable_drop(str(appimage))
    assert is_executable_drop(str(script))
    assert is_executable_drop(str(plain_script))
    assert is_executable_drop(str(binary))


def test_is_executable_drop_rejects_non_executables(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("hi")
    plain = tmp_path / "plain"
    plain.write_text("hi")

    assert not is_executable_drop(str(notes))
    assert not is_executable_drop(str(plain))
    assert not is_executable_drop("")
    assert not is_executable_drop(str(tmp_path / "missing.AppImage"))


def test_is_image_drop(tmp_path):
    png = tmp_path / "a.png"
    png.write_bytes(b"x")
    svg = tmp_path / "a.svg"
    svg.write_text("<svg/>")
    ico = tmp_path / "a.ico"
    ico.write_bytes(b"x")
    notes = tmp_path / "a.txt"
    notes.write_text("x")

    assert is_image_drop(str(png))
    assert is_image_drop(str(svg))
    assert is_image_drop(str(ico))
    assert not is_image_drop(str(notes))
    assert not is_image_drop(str(tmp_path / "ghost.png"))


# --------------------------------------------------------------------------- #
# Icon detection for dropped files
# --------------------------------------------------------------------------- #
def test_detect_icon_from_display_name_sibling(tmp_path):
    appimage = tmp_path / "Liner-0.1.35.AppImage"
    appimage.write_bytes(b"x")
    icon = tmp_path / "Liner.png"
    icon.write_bytes(b"x")

    assert detect_icon_for_path(str(appimage), "Liner") == str(icon)


def test_detect_icon_from_stem_sibling(tmp_path):
    appimage = tmp_path / "Liner.AppImage"
    appimage.write_bytes(b"x")
    icon = tmp_path / "Liner.svg"
    icon.write_text("<svg/>")

    assert detect_icon_for_path(str(appimage), "") == str(icon)


def test_detect_icon_falls_back_to_empty(tmp_path):
    appimage = tmp_path / "Zzqqx-App.AppImage"
    appimage.write_bytes(b"x")

    assert detect_icon_for_path(str(appimage), "Zzqqx App") == ""


# --------------------------------------------------------------------------- #
# Dashboard: window-level drops
# --------------------------------------------------------------------------- #
def test_drag_enter_shows_overlay_and_leave_hides_it(window, appimage):
    assert window._drop_overlay.isHidden()

    enter = drag_enter(file_mime(appimage))
    window.dragEnterEvent(enter)
    assert enter.isAccepted()
    assert not window._drop_overlay.isHidden()

    window.dragLeaveEvent(drag_leave())
    assert window._drop_overlay.isHidden()


def test_drag_move_keeps_overlay_visible(window, appimage):
    window.dragEnterEvent(drag_enter(file_mime(appimage)))

    move = drag_move(file_mime(appimage))
    window.dragMoveEvent(move)

    assert move.isAccepted()
    assert not window._drop_overlay.isHidden()


def test_dashboard_ignores_non_executable_drag(window, stray_file, monkeypatch):
    captured = capture_dialogs(monkeypatch)

    enter = drag_enter(file_mime(stray_file))
    window.dragEnterEvent(enter)
    assert not enter.isAccepted()
    assert window._drop_overlay.isHidden()

    event = drop(file_mime(stray_file))
    window.dropEvent(event)
    assert not event.isAccepted()
    assert captured == {}


def test_dashboard_drop_opens_prefilled_add_dialog(window, appimage, monkeypatch):
    captured = capture_dialogs(monkeypatch)

    enter = drag_enter(file_mime(appimage))
    window.dragEnterEvent(enter)
    assert not window._drop_overlay.isHidden()

    event = drop(file_mime(appimage))
    window.dropEvent(event)

    assert event.isAccepted()
    assert captured['path'] == str(appimage)
    assert captured['name'] == "Liner"
    assert captured['icon'] == ""
    assert window._drop_overlay.isHidden()


def test_dashboard_drop_prefills_detected_sibling_icon(window, tmp_path, monkeypatch):
    captured = capture_dialogs(monkeypatch)
    appimage = tmp_path / "Liner.AppImage"
    appimage.write_bytes(b"x")
    icon = tmp_path / "Liner.png"
    icon.write_bytes(b"x")

    window.dropEvent(drop(file_mime(appimage)))

    assert captured['path'] == str(appimage)
    assert captured['icon'] == str(icon)


def test_dashboard_drop_uses_first_executable_among_urls(window, stray_file, appimage, monkeypatch):
    captured = capture_dialogs(monkeypatch)

    window.dropEvent(drop(file_mime(stray_file, appimage)))

    assert captured['path'] == str(appimage)


# --------------------------------------------------------------------------- #
# Dashboard: card container / viewport route drops to the window
# --------------------------------------------------------------------------- #
def test_container_and_viewport_route_drops_to_window(window, appimage, monkeypatch):
    captured = capture_dialogs(monkeypatch)

    enter = drag_enter(file_mime(appimage))
    QApplication.sendEvent(window.apps_container, enter)
    assert enter.isAccepted()
    assert not window._drop_overlay.isHidden()

    move = drag_move(file_mime(appimage))
    QApplication.sendEvent(window.apps_scroll.viewport(), move)
    assert move.isAccepted()

    event = drop(file_mime(appimage))
    QApplication.sendEvent(window.apps_scroll.viewport(), event)
    assert event.isAccepted()
    assert captured['path'] == str(appimage)
    assert window._drop_overlay.isHidden()


def test_container_drag_leave_hides_overlay(window, appimage):
    QApplication.sendEvent(window.apps_container, drag_enter(file_mime(appimage)))
    assert not window._drop_overlay.isHidden()

    QApplication.sendEvent(window.apps_container, drag_leave())
    assert window._drop_overlay.isHidden()


# --------------------------------------------------------------------------- #
# Dialog: drop zones
# --------------------------------------------------------------------------- #
def test_exec_field_accepts_exec_drop_and_suggests_name(qapp, appimage):
    dialog = CategoryDialog()
    field = dialog.path_input

    enter = drag_enter(file_mime(appimage))
    field.dragEnterEvent(enter)
    assert enter.isAccepted()
    assert field.property('dragActive') is True

    event = drop(file_mime(appimage))
    field.dropEvent(event)

    assert event.isAccepted()
    assert field.text() == str(appimage)
    assert field.property('dragActive') is False
    assert dialog.name_input.text() == "Liner"


def test_exec_drop_does_not_overwrite_filled_fields(qapp, appimage):
    dialog = CategoryDialog()
    dialog.name_input.setText("Custom Name")
    dialog.icon_input.setText("custom-icon")

    event = drop(file_mime(appimage))
    dialog.path_input.dropEvent(event)

    assert dialog.path_input.text() == str(appimage)
    assert dialog.name_input.text() == "Custom Name"
    assert dialog.icon_input.text() == "custom-icon"


def test_exec_field_rejects_image_drop(qapp, png_icon):
    dialog = CategoryDialog()
    field = dialog.path_input
    field.setText("original-command")

    move = drag_move(file_mime(png_icon))
    field.dragMoveEvent(move)
    assert not move.isAccepted()

    event = drop(file_mime(png_icon))
    field.dropEvent(event)
    assert not event.isAccepted()
    assert field.text() == "original-command"
    assert field.property('dragActive') is False


def test_icon_field_accepts_image_drop_and_refreshes_preview(qapp, png_icon):
    dialog = CategoryDialog()
    field = dialog.icon_input

    enter = drag_enter(file_mime(png_icon))
    field.dragEnterEvent(enter)
    assert enter.isAccepted()
    assert field.property('dragActive') is True

    event = drop(file_mime(png_icon))
    field.dropEvent(event)

    assert event.isAccepted()
    assert field.text() == str(png_icon)
    assert field.property('dragActive') is False

    preview = dialog.icon_preview.pixmap()
    assert not preview.isNull()
    center = preview.toImage().pixelColor(preview.width() // 2, preview.height() // 2)
    assert (center.red(), center.green(), center.blue()) == (0xFF, 0x88, 0x00)


def test_icon_field_rejects_executable_drop(qapp, appimage):
    dialog = CategoryDialog()
    field = dialog.icon_input

    event = drop(file_mime(appimage))
    field.dropEvent(event)

    assert not event.isAccepted()
    assert field.text() == ""


def test_drag_leave_clears_drag_active_state(qapp, appimage):
    dialog = CategoryDialog()
    field = dialog.path_input
    field.dragEnterEvent(drag_enter(file_mime(appimage)))
    assert field.property('dragActive') is True

    field.dragLeaveEvent(drag_leave())
    assert field.property('dragActive') is False


# --------------------------------------------------------------------------- #
# Dialog: prefill plumbing
# --------------------------------------------------------------------------- #
def test_apply_prefill_updates_fields_and_preview(qapp, appimage, png_icon):
    dialog = CategoryDialog()

    dialog.apply_prefill({
        'path': str(appimage), 'name': 'Liner', 'icon': str(png_icon),
    })

    assert dialog.path_input.text() == str(appimage)
    assert dialog.name_input.text() == "Liner"
    assert dialog.icon_input.text() == str(png_icon)
    preview = dialog.icon_preview.pixmap()
    assert not preview.isNull()
    center = preview.toImage().pixelColor(preview.width() // 2, preview.height() // 2)
    assert (center.red(), center.green(), center.blue()) == (0xFF, 0x88, 0x00)
