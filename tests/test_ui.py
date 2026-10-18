"""
UI regression tests for Omarchy App Manager.

These run Qt offscreen so they work in a headless environment. They cover the
refresh path that previously left stale/duplicated cards, the visual polish
(grid layout, animated hovers, filter fades, dialog fade, icon fallback) and
render the whole window to catch paint-time crashes.

Run with:  python -m pytest tests/test_ui.py -v
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_app_manager import desktop_manager as dm  # noqa: E402
from omarchy_app_manager import ui_mainwindow as ui  # noqa: E402
from omarchy_app_manager.styles import CATEGORY_COLORS, PALETTE  # noqa: E402
from omarchy_app_manager.ui_mainwindow import (  # noqa: E402
    AppCard, CategoryDialog, OmarchyAppManager, ToggleSwitch,
)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    monkeypatch.setenv("OMARCHY_APPS_DIR", str(apps_dir))
    return apps_dir


def make_app(name, path="/bin/true", icon="", category="Utility"):
    dm.create_desktop_file(
        {"name": name, "path": path, "icon": icon, "category": category}
    )


def card_names(window):
    return sorted(c.app_data["name"] for c in window._cards)


def visible_card_names(window):
    return sorted(
        c.app_data["name"] for c in window._cards if not c.isHidden()
    )


def pump(app, seconds):
    """Drive the event loop for up to ``seconds``."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


# --------------------------------------------------------------------------- #
# Refresh correctness
# --------------------------------------------------------------------------- #
def test_dashboard_refreshes_without_duplicates(qapp, sandbox):
    make_app("Alpha")
    window = OmarchyAppManager()
    assert card_names(window) == ["Alpha"]

    make_app("Beta")
    window.load_apps()
    qapp.processEvents()
    assert card_names(window) == ["Alpha", "Beta"]

    # Rename Alpha in place, then refresh: no stale "Alpha" card may remain.
    path = next(a["file_path"] for a in window.apps if a["name"] == "Alpha")
    dm.update_desktop_file(
        {"name": "Alpha Renamed", "path": "/bin/true", "icon": "", "category": "AudioVideo"},
        path,
    )
    window.load_apps()
    qapp.processEvents()
    assert card_names(window) == ["Alpha Renamed", "Beta"]


# --------------------------------------------------------------------------- #
# Search filtering
# --------------------------------------------------------------------------- #
def test_search_filter_hides_non_matching(qapp, sandbox):
    make_app("Firefox")
    make_app("Gimp")
    window = OmarchyAppManager()

    window.search_bar.setText("fire")
    window._filter_apps("fire")
    assert visible_card_names(window) == ["Firefox"]


def test_search_filter_fade_animation_completes(qapp, sandbox, monkeypatch):
    """With real durations the fade machinery must run and settle."""
    monkeypatch.setattr(ui, "FILTER_FADE_IN_MS", 60)
    monkeypatch.setattr(ui, "FILTER_FADE_OUT_MS", 60)

    make_app("Firefox")
    make_app("Gimp")
    window = OmarchyAppManager()

    window.search_bar.setText("fire")
    pump(qapp, 2.0)

    assert visible_card_names(window) == ["Firefox"]
    gimp_card = next(
        c for c in window._cards if c.app_data["name"] == "Gimp"
    )
    assert gimp_card.isHidden()
    # The opacity effect must be torn down after the fade so text stays crisp.
    assert gimp_card.graphicsEffect() is None


# --------------------------------------------------------------------------- #
# Grid layout
# --------------------------------------------------------------------------- #
def grid_positions(window):
    """Map app name -> (row, column) for every visible card."""
    positions = {}
    for card in window._cards:
        if card.isHidden():
            continue
        index = window.apps_grid.indexOf(card)
        assert index != -1, f"{card.app_data['name']} missing from the grid"
        row, column, _, _ = window.apps_grid.getItemPosition(index)
        positions[card.app_data["name"]] = (row, column)
    return positions


def assert_packed_grid(window):
    """All visible cards must be tightly packed relative to `window._columns`."""
    columns = window._columns
    assert 1 <= columns <= ui.MAX_GRID_COLUMNS
    visible = [c for c in window._cards if not c.isHidden()]
    positions = grid_positions(window)
    assert len(positions) == len(visible)
    for index, card in enumerate(visible):
        assert positions[card.app_data["name"]] == (index // columns, index % columns)


def test_grid_columns_for_width(qapp, sandbox):
    window = OmarchyAppManager()
    assert window._grid_columns_for_width(0) == 1
    assert window._grid_columns_for_width(200) == 1
    assert window._grid_columns_for_width(600) == 1
    assert window._grid_columns_for_width(700) == 2
    assert window._grid_columns_for_width(950) == 2
    assert window._grid_columns_for_width(1100) == 3
    assert window._grid_columns_for_width(1400) == 4
    assert window._grid_columns_for_width(4000) == ui.MAX_GRID_COLUMNS


def test_cards_arranged_in_responsive_grid(qapp, sandbox):
    for name in ("One", "Two", "Three", "Four", "Five"):
        make_app(name)
    window = OmarchyAppManager()
    window.show()
    pump(qapp, 0.2)
    try:
        assert_packed_grid(window)
    finally:
        window.close()


def test_filter_reflows_grid(qapp, sandbox):
    make_app("Firefox")
    make_app("Gimp")
    make_app("VLC", category="AudioVideo")
    window = OmarchyAppManager()
    window.show()
    pump(qapp, 0.2)

    window._filter_apps("i")  # matches Firefox & Gimp, not VLC
    window._filter_apps("i", animate=False)  # settle instantly
    try:
        assert visible_card_names(window) == ["Firefox", "Gimp"]
        assert_packed_grid(window)
    finally:
        window.close()


# --------------------------------------------------------------------------- #
# Icons
# --------------------------------------------------------------------------- #
def test_icon_fallback_badge_is_generated(qapp, sandbox):
    make_app("Firefox")
    window = OmarchyAppManager()
    card = window._cards[0]

    pixmap = card.icon_label.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.width() / pixmap.devicePixelRatio() == ui.ICON_SIZE


def test_icon_file_is_masked_and_scaled(qapp, sandbox, tmp_path):
    from PyQt6.QtGui import QPixmap

    source = tmp_path / "icon.png"
    pixmap = QPixmap(128, 128)
    pixmap.fill()
    assert pixmap.save(str(source))

    make_app("Iconed", icon=str(source))
    window = OmarchyAppManager()
    card = window._cards[0]

    rendered = card.icon_label.pixmap()
    assert rendered is not None and not rendered.isNull()
    assert rendered.width() / rendered.devicePixelRatio() == ui.ICON_SIZE


# --------------------------------------------------------------------------- #
# Animations
# --------------------------------------------------------------------------- #
def test_card_hover_animation_reaches_target(qapp, sandbox):
    make_app("Hover")
    window = OmarchyAppManager()
    card = window._cards[0]

    assert card.hoverProgress == 0.0
    card._animate_hover(1.0)
    assert card.hoverProgress == 1.0
    card._animate_hover(0.0)
    assert card.hoverProgress == 0.0


def test_card_hover_animation_is_smooth_with_real_duration(qapp, sandbox, monkeypatch):
    monkeypatch.setattr(ui, "CARD_HOVER_MS", 80)
    make_app("Hover")
    window = OmarchyAppManager()
    card = window._cards[0]

    card._animate_hover(1.0)
    pump(qapp, 1.0)
    assert card.hoverProgress == 1.0


# --------------------------------------------------------------------------- #
# Hover-only actions
# --------------------------------------------------------------------------- #
def test_hover_reveals_edit_delete_actions(qapp, sandbox):
    make_app("Hover")
    window = OmarchyAppManager()
    card = window._cards[0]

    # Hidden by default and not clickable.
    assert card.actionsOpacity == 0.0
    for button in (card.launch_button, card.edit_button,
                   card.open_dir_button, card.delete_button):
        assert not button.isEnabled()

    card._set_actions_visible(True)
    assert card.actionsOpacity == 1.0
    assert card.launch_button.isEnabled()
    assert card.edit_button.isEnabled()
    assert card.open_dir_button.isEnabled()
    assert card.delete_button.isEnabled()

    card._set_actions_visible(False)
    assert card.actionsOpacity == 0.0
    for button in (card.launch_button, card.edit_button,
                   card.open_dir_button, card.delete_button):
        assert not button.isEnabled()


def test_actions_fade_out_disables_buttons(qapp, sandbox, monkeypatch):
    """With real durations the fade must complete and disable the buttons."""
    monkeypatch.setattr(ui, "CARD_HOVER_MS", 60)
    make_app("Hover")
    window = OmarchyAppManager()
    card = window._cards[0]

    card._set_actions_visible(True)
    pump(qapp, 1.0)
    assert card.actionsOpacity == 1.0
    assert card.edit_button.isEnabled()

    card._set_actions_visible(False)
    pump(qapp, 1.0)
    assert card.actionsOpacity == 0.0
    assert not card.edit_button.isEnabled()


# --------------------------------------------------------------------------- #
# View toggle + counter
# --------------------------------------------------------------------------- #
def test_view_toggle_switches_between_custom_and_system(qapp, sandbox):
    make_app("Custom App")
    (sandbox / "wine-extension-wscript.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=wscript\n"
        "Exec=env WINEPREFIX=/x wine start /ProgIDOpen wscript %1\n"
        "NoDisplay=true\nCategories=Utility;\n",
        encoding="utf-8",
    )

    window = OmarchyAppManager()
    assert window.show_all_system is False
    assert card_names(window) == ["Custom App"]
    assert window.counter_label.text() == "Showing 1 App"

    window.view_toggle.set_index(1)
    assert window.show_all_system is True
    assert card_names(window) == ["Custom App", "wscript"]
    assert window.counter_label.text() == "Showing 2 Apps"

    window.view_toggle.set_index(0)
    assert window.show_all_system is False
    assert card_names(window) == ["Custom App"]


def test_counter_reflects_visible_apps(qapp, sandbox):
    make_app("Firefox")
    make_app("Gimp")
    window = OmarchyAppManager()
    assert window.counter_label.text() == "Showing 2 Apps"

    window._filter_apps("fire", animate=False)
    assert window.counter_label.text() == "Showing 1 App"

    window._filter_apps("zzz", animate=False)
    assert window.counter_label.text() == "Showing 0 Apps"


def test_custom_view_empty_state_mentions_toggle(qapp, sandbox):
    window = OmarchyAppManager()
    window.show()
    pump(qapp, 0.2)
    try:
        assert window.empty_label.isVisible()
        assert "Add App" in window.empty_label.text()
    finally:
        window.close()


# --------------------------------------------------------------------------- #
# Category badges
# --------------------------------------------------------------------------- #
def test_category_badge_uses_tinted_pill(qapp, sandbox):
    make_app("Gamey", category="Game")
    window = OmarchyAppManager()
    card = window._cards[0]
    style = card.category_label.styleSheet()
    assert CATEGORY_COLORS["Game"]["text"] in style
    assert CATEGORY_COLORS["Game"]["bg"] in style
    assert card.category_label.text() == "Game"


def test_animated_button_hover_progress(qapp, sandbox):
    from omarchy_app_manager.ui_mainwindow import AnimatedButton

    button = AnimatedButton("Test", "primary")
    assert button.progress == 0.0
    button._animate_to(1.0)
    assert button.progress == 1.0


def test_dialog_fade_in_and_teardown(qapp, sandbox, monkeypatch):
    monkeypatch.setattr(ui, "DIALOG_FADE_MS", 60)
    dialog = CategoryDialog()
    dialog.show()
    pump(qapp, 1.0)
    try:
        assert dialog.graphicsEffect() is None  # fade finished, effect removed
    finally:
        dialog.close()


def test_dialog_no_effect_when_animations_disabled(qapp, sandbox):
    dialog = CategoryDialog()
    dialog.show()
    try:
        assert dialog.graphicsEffect() is None
    finally:
        dialog.close()


def test_edit_dialog_prepopulates_full_exec_line(qapp, sandbox):
    app_data = {
        "name": "Args Test",
        "path": "/opt/my apps/run.sh",
        "exec_path": '"/opt/my apps/run.sh" --flag %U',
        "icon": "/tmp/icon.png",
        "category": "Game",
        "file_path": None,
    }
    dialog = CategoryDialog(None, app_data)
    assert dialog.name_input.text() == "Args Test"
    assert dialog.path_input.text() == '"/opt/my apps/run.sh" --flag %U'
    assert dialog.icon_input.text() == "/tmp/icon.png"
    assert dialog.category_combo.currentText() == "Game"
    assert dialog.get_data()["path"] == '"/opt/my apps/run.sh" --flag %U'


# --------------------------------------------------------------------------- #
# Performance wrappers + window-class inspection
# --------------------------------------------------------------------------- #
def test_toggle_switch_animates_to_state(qapp):
    toggle = ToggleSwitch()
    assert toggle.offset == 0.0
    toggle.setChecked(True)
    assert toggle.isChecked() is True
    assert toggle.offset == 1.0  # instant: TOGGLE_ANIM_MS is zeroed in tests
    toggle.setChecked(False)
    assert toggle.offset == 0.0


def test_dialog_reports_perf_flags_and_wmclass(qapp, sandbox):
    dialog = CategoryDialog()
    dialog.name_input.setText("Wrapped")
    dialog.path_input.setText("/bin/true")
    dialog.wmclass_input.setText("wrapped-app")
    dialog.gamemode_toggle.setChecked(True)
    data = dialog.get_data()
    assert data["gamemode"] is True
    assert data["prime_gpu"] is False
    assert data["startup_wm_class"] == "wrapped-app"


def test_edit_dialog_prefills_perf_state(qapp, sandbox):
    dialog = CategoryDialog(None, {
        "name": "Prefilled", "path": "/bin/true", "exec_path": "/bin/true",
        "icon": "", "category": "Utility",
        "gamemode": True, "prime_gpu": True, "startup_wm_class": "prefilled",
    })
    assert dialog.gamemode_toggle.isChecked() is True
    assert dialog.prime_toggle.isChecked() is True
    assert dialog.wmclass_input.text() == "prefilled"


def test_window_classes_from_clients_parses_and_dedupes():
    payload = json.dumps([
        {"class": "firefox", "title": "Mozilla Firefox"},
        {"class": "firefox", "title": "Second Window"},
        {"class": "", "title": "no class"},
        {"class": "kitty", "title": "~/Work"},
        "junk",
    ])
    assert ui._window_classes_from_clients(payload) == [
        ("firefox", "Mozilla Firefox"), ("kitty", "~/Work")]
    assert ui._window_classes_from_clients("not json") == []
    assert ui._window_classes_from_clients(json.dumps({"a": 1})) == []


def test_inspect_missing_hyprctl_warns(qapp, sandbox, monkeypatch):
    warnings = []
    monkeypatch.setattr(ui, "_hyprctl_program", lambda: None)
    dialog = CategoryDialog()
    monkeypatch.setattr(
        dialog, "_show_warning", lambda title, text: warnings.append((title, text)))

    dialog._inspect_window_class()
    assert warnings and warnings[0][0] == "Inspect Window Class"


def test_present_window_classes_fills_field(qapp, sandbox, monkeypatch):
    class FakeAction:
        def data(self):
            return "kitty"

    monkeypatch.setattr(ui, "_choose_from_menu", lambda menu, anchor: FakeAction())
    dialog = CategoryDialog()
    dialog._present_window_classes(json.dumps([
        {"class": "firefox", "title": "Mozilla Firefox"},
        {"class": "kitty", "title": ""},
    ]))
    assert dialog.wmclass_input.text() == "kitty"


def test_present_window_classes_empty_warns(qapp, sandbox, monkeypatch):
    warnings = []
    dialog = CategoryDialog()
    monkeypatch.setattr(
        dialog, "_show_warning", lambda title, text: warnings.append(title))

    dialog._present_window_classes(json.dumps([]))
    assert warnings == ["Inspect Window Class"]


def test_card_perf_badges_reflect_flags(qapp, sandbox):
    plain = AppCard({"name": "Plain", "path": "/bin/true"})
    assert plain.perf_badges["gamemode"].isHidden()
    assert plain.perf_badges["prime_gpu"].isHidden()

    wrapped = AppCard({"name": "Wrapped", "path": "/bin/true",
                       "gamemode": True, "prime_gpu": True})
    assert not wrapped.perf_badges["gamemode"].isHidden()
    assert not wrapped.perf_badges["prime_gpu"].isHidden()
    assert wrapped.perf_badges["gamemode"].toolTip() == "Launches with GameMode"


def test_perf_badge_pixmaps_render(qapp):
    pixmap = ui._perf_badge_pixmap("gamemode", ui.PERF_BADGE_SIZE)
    assert not pixmap.isNull()
    assert pixmap.devicePixelRatio() == qapp.devicePixelRatio()


# --------------------------------------------------------------------------- #
# Category filter pills
# --------------------------------------------------------------------------- #
def test_category_pills_filter_grid(qapp, sandbox):
    make_app("Devtool", category="Development")
    make_app("Gamey", category="Game")
    make_app("Simply", category="Utility")
    window = OmarchyAppManager()

    assert list(window.category_pills._buttons) == [
        "All", "Development", "Games", "Utilities", "System"]
    assert window.category_pills.current() == "All"
    assert visible_card_names(window) == ["Devtool", "Gamey", "Simply"]

    window.category_pills._buttons["Development"].click()
    assert window.category_pills.current() == "Development"
    assert visible_card_names(window) == ["Devtool"]
    assert window.counter_label.text() == "Showing 1 App"
    assert window.category_pills._buttons["Development"].variant == "primary"
    assert window.category_pills._buttons["All"].variant == "segment"

    window.category_pills._buttons["Games"].click()
    assert visible_card_names(window) == ["Gamey"]
    assert window.category_pills._buttons["Development"].variant == "segment"

    window.category_pills._buttons["Utilities"].click()
    assert visible_card_names(window) == ["Simply"]

    window.category_pills._buttons["All"].click()
    assert visible_card_names(window) == ["Devtool", "Gamey", "Simply"]
    assert window.category_pills._buttons["All"].variant == "primary"


def test_category_pills_fade_transition(qapp, sandbox, monkeypatch):
    """With real durations the pill switch must fade and settle cleanly."""
    monkeypatch.setattr(ui, "FILTER_FADE_IN_MS", 60)
    monkeypatch.setattr(ui, "FILTER_FADE_OUT_MS", 60)

    make_app("Devtool", category="Development")
    make_app("Gamey", category="Game")
    window = OmarchyAppManager()

    window.category_pills._buttons["Development"].click()
    pump(qapp, 2.0)

    assert visible_card_names(window) == ["Devtool"]
    game = next(c for c in window._cards if c.app_data["name"] == "Gamey")
    assert game.isHidden()
    # The opacity effect must be torn down after the fade so text stays crisp.
    assert game.graphicsEffect() is None


def test_category_pills_combine_with_search(qapp, sandbox):
    make_app("Dev One", category="Development")
    make_app("Dev Two", category="Development")
    make_app("Game One", category="Game")
    window = OmarchyAppManager()

    window.search_bar.setText("dev")
    window.category_pills._buttons["Development"].click()
    assert visible_card_names(window) == ["Dev One", "Dev Two"]

    window.search_bar.setText("two")
    assert visible_card_names(window) == ["Dev Two"]

    window.category_pills._buttons["All"].click()
    assert visible_card_names(window) == ["Dev Two"]


def test_system_pill_matches_system_entries(qapp, sandbox):
    make_app("Custom App")
    (sandbox / "wine-extension-wscript.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=wscript\n"
        "Exec=env WINEPREFIX=/x wine start /ProgIDOpen wscript %1\n"
        "NoDisplay=true\nCategories=Utility;\n",
        encoding="utf-8",
    )
    window = OmarchyAppManager()
    window.view_toggle.set_index(1)  # All System Apps

    window.category_pills._buttons["System"].click()
    assert visible_card_names(window) == ["wscript"]

    window.category_pills._buttons["All"].click()
    assert visible_card_names(window) == ["Custom App", "wscript"]


def test_pill_switch_reuses_cards_without_rebuild(qapp, sandbox):
    """Filtering must only hide/show cards - never recreate them (no thrash)."""
    make_app("Devtool", category="Development")
    make_app("Gamey", category="Game")
    window = OmarchyAppManager()
    before = [id(card) for card in window._cards]

    window.category_pills._buttons["Games"].click()
    window.category_pills._buttons["All"].click()
    window.search_bar.setText("dev")
    window.search_bar.clear()

    assert [id(card) for card in window._cards] == before


def test_rapid_filter_changes_settle_cleanly(qapp, sandbox):
    for name in ("Alpha", "Beta", "Gamma"):
        make_app(name)
    window = OmarchyAppManager()

    for text in ("a", "al", "alp", "alpha", "al", "", "b", ""):
        window.search_bar.setText(text)
    window._filter_apps("", animate=False)

    assert visible_card_names(window) == ["Alpha", "Beta", "Gamma"]
    assert window.counter_label.text() == "Showing 3 Apps"


# --------------------------------------------------------------------------- #
# Card quick actions
# --------------------------------------------------------------------------- #
def test_card_quick_actions_present(qapp, sandbox):
    make_app("Quick")
    window = OmarchyAppManager()
    card = window._cards[0]

    assert card.launch_button.glyph == "play"
    assert card.edit_button.glyph == "edit"
    assert card.open_dir_button.glyph == "folder"
    assert card.delete_button.glyph == "delete"
    assert card.launch_button.toolTip() == "Launch"
    assert card.open_dir_button.toolTip() == "Open Directory"


def test_launch_builds_argv_strips_field_codes(qapp, sandbox, monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(
        ui, "_start_detached", lambda program, args: launched.append((program, args)) or True)

    executable = tmp_path / "launch me.AppImage"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    window = OmarchyAppManager()

    window._launch_app({
        "path": str(executable),
        "exec_path": f'"{executable}" --flag %U "two words"',
    })
    assert launched == [(str(executable), ["--flag", "two words"])]


def test_launch_missing_executable_warns(qapp, sandbox, monkeypatch):
    warnings = []
    window = OmarchyAppManager()
    monkeypatch.setattr(
        window, "_show_warning", lambda title, text: warnings.append((title, text)))

    window._launch_app({"path": "/missing/not-there", "exec_path": ""})
    assert warnings and warnings[0][0] == "Launch"


def test_open_directory_reveals_app_location(qapp, sandbox, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(
        ui, "_open_in_file_manager", lambda path: opened.append(str(path)) or True)

    executable = tmp_path / "app.AppImage"
    executable.write_text("x", encoding="utf-8")
    window = OmarchyAppManager()
    window._open_app_dir({"path": str(executable)})
    assert opened == [str(tmp_path)]


def test_open_directory_warns_for_command_only_entries(qapp, sandbox, monkeypatch):
    warnings = []
    window = OmarchyAppManager()
    monkeypatch.setattr(
        window, "_show_warning", lambda title, text: warnings.append(title))

    window._open_app_dir({"path": "firefox"})
    assert warnings == ["Open Directory"]


def test_launch_applies_performance_wrappers(qapp, sandbox, monkeypatch):
    launched = []
    monkeypatch.setattr(
        ui, "_start_detached",
        lambda program, args: launched.append((program, args)) or True)
    monkeypatch.setattr(ui, "command_is_available", lambda line: True)

    window = OmarchyAppManager()
    window._launch_app({
        "exec_path": "/bin/true", "path": "/bin/true",
        "gamemode": True, "prime_gpu": True,
    })
    assert launched == [(
        "gamemoderun",
        ["env", "__NV_PRIME_RENDER_OFFLOAD=1",
         "__GLX_VENDOR_LIBRARY_NAME=nvidia", "/bin/true"],
    )]


def test_launch_missing_gamemoderun_gets_specific_warning(
        qapp, sandbox, monkeypatch):
    warnings = []
    window = OmarchyAppManager()
    monkeypatch.setattr(window, "_show_warning", lambda title, text: warnings.append(text))
    monkeypatch.setattr(ui.shutil, "which", lambda name: None)

    window._launch_app({"exec_path": "/bin/true", "path": "/bin/true",
                        "gamemode": True})
    assert warnings and "gamemoderun" in warnings[0] and "not installed" in warnings[0]


# --------------------------------------------------------------------------- #
# Hover glow + search bar polish
# --------------------------------------------------------------------------- #
def test_card_hover_glow_uses_lavender(qapp, sandbox):
    from omarchy_app_manager.styles import CARD_COLORS

    assert CARD_COLORS["hover_glow"] == PALETTE["lavender"]
    make_app("Glow")
    window = OmarchyAppManager()
    card = window._cards[0]

    flat = card.grab().toImage()
    card._set_hover_progress(1.0)
    glowing = card.grab().toImage()
    assert flat != glowing  # the glow + border blend visibly change the paint


def test_search_bar_has_integrated_icons(qapp, sandbox):
    make_app("Firefox")
    window = OmarchyAppManager()
    bar = window.search_bar

    assert not bar._search_action.icon().isNull()
    assert not bar._clear_action.isVisible()

    bar.setText("fire")
    assert bar._clear_action.isVisible()
    assert visible_card_names(window) == ["Firefox"]

    bar._clear_action.trigger()  # instant clear
    assert bar.text() == ""
    assert not bar._clear_action.isVisible()
    assert visible_card_names(window) == ["Firefox"]  # everything matches again


# --------------------------------------------------------------------------- #
# Empty state
# --------------------------------------------------------------------------- #
def test_empty_state_has_drop_target_and_swaps_with_grid(qapp, sandbox):
    window = OmarchyAppManager()
    window.show()
    pump(qapp, 0.2)
    try:
        assert window.empty_state.isVisible()
        assert not window.apps_scroll.isVisible()
        assert window.empty_state.title_label.text() == "No Applications Found"
        assert "Add App" in window.empty_state.hint_label.text()
        assert "drop" in window.empty_state.drop_hint.text().lower()
        assert not window.empty_state.icon_label.pixmap().isNull()
        assert not window.empty_state.grab().isNull()

        make_app("Now There")
        window.load_apps()
        pump(qapp, 0.2)
        assert not window.empty_state.isVisible()
        assert window.apps_scroll.isVisible()

        window._filter_apps("zzz", animate=False)
        assert window.empty_state.isVisible()
        assert not window.apps_scroll.isVisible()
        assert window.empty_state.hint_label.text() == "No applications match your search"
    finally:
        window.close()


def test_polish_widgets_refresh_on_theme_swap(qapp, sandbox):
    from omarchy_app_manager import styles

    make_app("Theme")
    window = OmarchyAppManager()
    palette = dict(styles.PALETTE)
    palette["mauve"] = "#123456"

    window._apply_palette_and_styles(palette, "Test")

    # Pills rebuilt from the new palette (active pill idles on mauve) and the
    # empty-state illustration was re-rendered without crashing.
    assert window.category_pills._buttons["All"]._idle_bg.name() == "#123456"
    assert not window.empty_state.icon_label.pixmap().isNull()


# --------------------------------------------------------------------------- #
# Rendering smoke test
# --------------------------------------------------------------------------- #
def test_elide_helper(qapp):
    from PyQt6.QtGui import QFontMetrics
    from omarchy_app_manager.ui_mainwindow import _elide

    metrics = QFontMetrics(qapp.font())
    assert _elide(metrics, 'short', 500) == 'short'

    text = 'a very long application name that needs eliding'
    right = _elide(metrics, text, 80)
    assert right.endswith('\u2026')
    assert metrics.horizontalAdvance(right) <= 80

    path = '/home/user/some/very/long/path/application.AppImage'
    middle = _elide(metrics, path, 100, middle=True)
    assert '\u2026' in middle
    assert metrics.horizontalAdvance(middle) <= 100
    assert middle.startswith('/home')


def test_no_horizontal_overflow_at_minimum_width(qapp, sandbox):
    """Regression: wide labels must not force the grid to overflow/clip."""
    for index in range(4):
        make_app(f"Wide Application Name Number {index}")
    window = OmarchyAppManager()
    window.resize(window.minimumWidth(), window.minimumHeight())
    window.show()
    pump(qapp, 0.2)
    try:
        assert window.apps_scroll.horizontalScrollBar().maximum() == 0
    finally:
        window.close()


def test_window_renders_without_crashing(qapp, sandbox):
    """Force the full paint pipeline (cards, badges, buttons, scroll area)."""
    make_app("One", icon="definitely-not-a-theme-icon")
    make_app("Two", category="Game")
    window = OmarchyAppManager()
    window.show()
    pump(qapp, 0.2)
    try:
        rendered = window.grab()
        assert not rendered.isNull()
        assert rendered.width() > 0
    finally:
        window.close()


def test_card_theme_uses_catppuccin_palette(qapp, sandbox):
    from PyQt6.QtGui import QColor

    from omarchy_app_manager.styles import CARD_COLORS, blend_hex

    make_app("One")
    window = OmarchyAppManager()
    card = window._cards[0]
    image = card.grab().toImage()
    # Sample just inside the top edge, above the content area, where only the
    # card background is painted.
    sample = image.pixelColor(image.width() // 2, 6)

    # Glassmorphic card: the translucent mantle body composites over the
    # crust window chrome at a fixed alpha, so the expected pixel is the
    # deterministic blend of the two (changing the glass alpha breaks this).
    expected = QColor(blend_hex(
        PALETTE["crust"], PALETTE["mantle"], CARD_COLORS["bg_alpha"]))
    assert sample == expected


# --------------------------------------------------------------------------- #
# Teardown safety
# --------------------------------------------------------------------------- #
def test_event_filter_tolerates_collected_window_teardown(qapp, sandbox):
    """Regression: Qt >= 6.9 re-parents children while they are destroyed and
    notifies their event filters.  A window reclaimed by the cyclic GC has its
    instance dict cleared before that C++ teardown runs, so the filter must
    quietly decline instead of raising (PyQt6 escalates exceptions in
    reimplemented virtuals to qFatal)."""
    from PyQt6.QtCore import QCoreApplication, QEvent

    make_app("Firefox")
    window = OmarchyAppManager()
    viewport = window.apps_scroll.viewport()

    window.__dict__.clear()  # what the cyclic GC does before C++ teardown
    event = QEvent(QEvent.Type.ParentChange)
    assert window.eventFilter(viewport, event) is False

    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
