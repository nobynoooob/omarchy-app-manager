"""Shared pytest fixtures.

The suite must be fully isolated from whatever theme the developer's desktop
is currently running: tests always run on the bundled Catppuccin Mocha
fallback and the live palette is restored after each test.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_app_manager import styles  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_theme(monkeypatch):
    """Force the static fallback palette and restore state after each test."""
    monkeypatch.setenv("OMARCHY_APPMANAGER_NO_THEME", "1")
    palette_snapshot = dict(styles.PALETTE)
    source_snapshot = styles.PALETTE_SOURCE
    yield
    styles.apply_palette(palette_snapshot, source_snapshot)


@pytest.fixture(autouse=True)
def instant_animations(monkeypatch):
    """Zero out animation durations so tests are deterministic and fast.

    Individual tests may re-set a duration afterwards (same monkeypatch
    instance); the value is restored at teardown either way.
    """
    from omarchy_app_manager import ui_mainwindow as ui

    monkeypatch.setattr(ui, "CARD_HOVER_MS", 0)
    monkeypatch.setattr(ui, "FILTER_FADE_IN_MS", 0)
    monkeypatch.setattr(ui, "FILTER_FADE_OUT_MS", 0)
    monkeypatch.setattr(ui, "DIALOG_FADE_MS", 0)
    monkeypatch.setattr(ui, "THEME_FADE_MS", 0)
    monkeypatch.setattr(ui, "TOGGLE_ANIM_MS", 0)
    monkeypatch.setattr(ui, "CARD_APPEAR_MS", 0)
    monkeypatch.setattr(ui, "SHADOW_ANIM_MS", 0)
    monkeypatch.setattr(ui, "RIPPLE_MS", 0)
    monkeypatch.setattr(ui, "PULSE_MS", 0)
    monkeypatch.setattr(ui, "PILL_SLIDE_MS", 0)
    monkeypatch.setattr(ui, "BREATH_MS", 0)


@pytest.fixture(autouse=True)
def disable_first_run(monkeypatch):
    """Never let a stray test window auto-register on the real desktop.

    First-run tests delete this variable inside their own sandbox.
    """
    monkeypatch.setenv("OMARCHY_APPMANAGER_NO_FIRST_RUN", "1")


@pytest.fixture(autouse=True)
def destroy_windows(qapp):
    """Destroy top-level windows deterministically after each test.

    Windows that are merely dropped (or even closed) linger until the cyclic
    garbage collector reclaims them, at which point Qt destroys the C++
    side in the middle of some unrelated allocation.  Doing it ourselves
    after each test keeps teardown out of other tests' execution paths.
    """
    yield
    from PyQt6.QtCore import QCoreApplication, QEvent

    for widget in qapp.topLevelWidgets():
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            continue
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def clean_home(tmp_path, monkeypatch):
    """Sandbox HOME with no theme sources and no theme env overrides.

    Deleting ``OMARCHY_APPMANAGER_NO_THEME`` (set by ``isolated_theme``)
    re-enables theme detection, but always against the sandbox HOME.
    """
    for var in ("XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
                "OMARCHY_APPMANAGER_THEME_FILE", "OMARCHY_APPMANAGER_NO_THEME"):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home
