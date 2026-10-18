"""
Live theme reloading tests.

Cover the full chain: QFileSystemWatcher -> debounced signal -> hot palette
swap -> animated window transition, all against a sandboxed HOME so the
developer's real rice is never touched. The autouse fixtures in ``conftest``
force the fallback palette and zero animation durations; tests that exercise
timing re-enable durations explicitly.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_app_manager import desktop_manager as dm  # noqa: E402
from omarchy_app_manager import styles  # noqa: E402
from omarchy_app_manager import ui_mainwindow as ui  # noqa: E402
from omarchy_app_manager.ui_mainwindow import OmarchyAppManager  # noqa: E402

THEME_TOML = """\
accent = "#F25623"
foreground = "#CCD0CF"
background = "#171717"
selection_background = "#F56E0F"
color1 = "#aeab94"
color2 = "#F25623"
color4 = "#88A57D"
color5 = "#F56E0F"
color8 = "#525252"
"""

# Same theme with a swapped accent; detection lowercases hex values.
SWAPPED_TOML = THEME_TOML.replace("#F25623", "#00CC66")
OLD_ACCENT = "#f25623"
NEW_ACCENT = "#00cc66"


def pump(qapp, seconds):
    """Drive the event loop for ``seconds``."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)


def pump_until(qapp, condition, timeout=3.0):
    """Drive the event loop until ``condition()`` is true (or timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return condition()


@pytest.fixture
def theme_window(qapp, clean_home, monkeypatch):
    """Live window backed by a rewritable Omarchy theme file in a sandbox."""
    theme_dir = clean_home / ".local/state/omarchy/current/theme"
    theme_dir.mkdir(parents=True)
    colors = theme_dir / "colors.toml"
    colors.write_text(THEME_TOML, encoding="utf-8")
    (theme_dir.parent / "theme.name").write_text("greek-noir", encoding="utf-8")

    apps_dir = clean_home / "applications"
    apps_dir.mkdir()
    monkeypatch.setenv("OMARCHY_APPS_DIR", str(apps_dir))

    window = OmarchyAppManager()
    yield window, colors
    window.close()


# --------------------------------------------------------------------------- #
# Watching
# --------------------------------------------------------------------------- #
def test_watcher_covers_file_and_enclosing_dirs(theme_window):
    window, colors = theme_window
    watched = set(window._theme_watcher.files())
    watched |= set(window._theme_watcher.directories())

    assert str(colors) in watched
    assert str(colors.parent) in watched
    # Omarchy theme switches swap ".../current" (possibly a symlink), so the
    # two enclosing directories must be watched too.
    assert str(colors.parent.parent) in watched
    assert str(colors.parent.parent.parent) in watched


def test_watcher_inactive_without_live_theme(qapp, tmp_path, monkeypatch):
    """OMARCHY_APPMANAGER_NO_THEME disables detection, so nothing is watched."""
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    monkeypatch.setenv("OMARCHY_APPS_DIR", str(apps_dir))

    window = OmarchyAppManager()
    try:
        assert window._theme_watcher.files() == []
        assert window._theme_watcher.directories() == []
    finally:
        window.close()


def test_file_watcher_triggers_hot_reload_from_disk(theme_window, qapp):
    """End-to-end: rewriting the file really fires the watcher and reloads."""
    window, colors = theme_window
    assert styles.PALETTE["mauve"] == OLD_ACCENT

    colors.write_text(SWAPPED_TOML, encoding="utf-8")

    assert pump_until(qapp, lambda: styles.PALETTE["mauve"] == NEW_ACCENT)
    assert "Omarchy theme" in styles.PALETTE_SOURCE


def test_watcher_survives_atomic_file_replacement(theme_window, qapp):
    """Write-to-temp + rename must reload and re-register the dropped file watch."""
    window, colors = theme_window
    replacement = colors.with_suffix(".toml.tmp")
    replacement.write_text(SWAPPED_TOML, encoding="utf-8")
    replacement.replace(colors)

    assert pump_until(qapp, lambda: styles.PALETTE["mauve"] == NEW_ACCENT)

    watched = set(window._theme_watcher.files())
    watched |= set(window._theme_watcher.directories())
    assert str(colors) in watched


# --------------------------------------------------------------------------- #
# Debounce
# --------------------------------------------------------------------------- #
def test_change_signals_trigger_single_debounced_reload(theme_window, qapp):
    window, colors = theme_window
    revision = styles.PALETTE_REVISION
    colors.write_text(SWAPPED_TOML, encoding="utf-8")

    for _ in range(5):
        window._on_theme_source_changed(str(colors))
    assert window._theme_debounce.isActive()

    assert pump_until(qapp, lambda: styles.PALETTE_REVISION > revision)
    # Any late watcher events must coalesce into no further (no-op) reload.
    pump(qapp, 0.3)
    assert styles.PALETTE_REVISION == revision + 1
    assert styles.PALETTE["mauve"] == NEW_ACCENT


# --------------------------------------------------------------------------- #
# Hot swap
# --------------------------------------------------------------------------- #
def test_reload_hot_swaps_palette_and_stylesheet(theme_window, qapp):
    window, colors = theme_window
    assert styles.PALETTE["mauve"] == OLD_ACCENT
    revision = styles.PALETTE_REVISION

    colors.write_text(SWAPPED_TOML, encoding="utf-8")
    window._reload_theme()

    assert styles.PALETTE["mauve"] == NEW_ACCENT
    assert styles.CARD_COLORS["hover_border"] == NEW_ACCENT
    assert styles.BUTTON_VARIANTS["primary"]["bg"] == NEW_ACCENT
    assert styles.PALETTE_REVISION == revision + 1
    assert "Omarchy theme" in styles.PALETTE_SOURCE
    assert NEW_ACCENT in qapp.styleSheet()
    # With durations zeroed the swap applies directly, leaving no effect behind.
    assert window._theme_effect is None
    assert window.centralWidget().graphicsEffect() is None


def test_reload_is_noop_when_nothing_changed(theme_window):
    window, colors = theme_window
    revision = styles.PALETTE_REVISION

    window._reload_theme()

    assert styles.PALETTE_REVISION == revision
    assert window._theme_effect is None


def test_reload_refreshes_card_badge_colors(theme_window, qapp):
    window, colors = theme_window
    dm.create_desktop_file({
        "name": "Fader", "path": "/bin/true", "icon": "", "category": "AudioVideo",
    })
    window.load_apps()
    card = window._cards[0]
    # The badge label is the WCAG-ensured variant of the accent.
    old_text = styles.CATEGORY_COLORS["AudioVideo"]["text"]
    assert old_text in card.category_label.styleSheet()

    colors.write_text(SWAPPED_TOML, encoding="utf-8")
    window._reload_theme()

    new_text = styles.CATEGORY_COLORS["AudioVideo"]["text"]
    assert new_text in card.category_label.styleSheet()
    assert new_text != old_text


# --------------------------------------------------------------------------- #
# Animated transition
# --------------------------------------------------------------------------- #
def test_palette_shift_cross_fades_via_opacity_effect(theme_window, qapp, monkeypatch):
    monkeypatch.setattr(ui, "THEME_FADE_MS", 80)
    window, colors = theme_window
    colors.write_text(SWAPPED_TOML, encoding="utf-8")

    window._reload_theme()

    # Fade-out comes first: the effect is installed but the old palette is
    # still active, so no frame ever shows a half-swapped window.
    assert window.centralWidget().graphicsEffect() is not None
    assert window._theme_effect is not None
    assert styles.PALETTE["mauve"] == OLD_ACCENT

    assert pump_until(qapp, lambda: window._theme_effect is None)
    assert window.centralWidget().graphicsEffect() is None
    assert styles.PALETTE["mauve"] == NEW_ACCENT


def test_restarting_mid_transition_does_not_crash(theme_window, qapp, monkeypatch):
    monkeypatch.setattr(ui, "THEME_FADE_MS", 120)
    window, colors = theme_window
    colors.write_text(SWAPPED_TOML, encoding="utf-8")

    window._reload_theme()
    pump(qapp, 0.04)  # let the fade-out get underway
    window._reload_theme()  # fresh transition must abort the old one cleanly

    assert pump_until(qapp, lambda: window._theme_effect is None)
    assert styles.PALETTE["mauve"] == NEW_ACCENT


def test_transition_takes_over_card_filter_effects(theme_window, qapp, monkeypatch):
    """The window fade must dissolve in-flight card opacity effects first."""
    from PyQt6.QtCore import qInstallMessageHandler

    monkeypatch.setattr(ui, "THEME_FADE_MS", 80)
    window, colors = theme_window
    dm.create_desktop_file({
        "name": "Fader", "path": "/bin/true", "icon": "", "category": "Utility",
    })
    window.load_apps()
    card = window._cards[0]

    # Leave a card mid filter fade-in, holding its own opacity effect.
    card.set_filter_visible(False, 0)
    card.set_filter_visible(True, 100)
    assert card.graphicsEffect() is not None

    messages = []
    previous_handler = qInstallMessageHandler(
        lambda *_args: messages.append(_args[-1] if _args else ""))
    try:
        colors.write_text(SWAPPED_TOML, encoding="utf-8")
        window._reload_theme()
        assert card.graphicsEffect() is None  # dropped before the window fade
        assert pump_until(qapp, lambda: window._theme_effect is None)
        qapp.processEvents()
    finally:
        qInstallMessageHandler(previous_handler)

    assert styles.PALETTE["mauve"] == NEW_ACCENT
    assert not any("painted by one painter" in message for message in messages)
