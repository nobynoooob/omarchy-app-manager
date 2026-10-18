"""
Security tests for generated UI assets (the QComboBox combo-arrow PNG).

The old implementation wrote to the predictable shared path
``/tmp/omarchy-app-manager`` with a check-then-write, so a local attacker
could pre-create that directory or plant a symlink at the arrow path and have
the app truncate/overwrite arbitrary files via the write (or serve an
attacker-chosen image).  These tests pin the hardened behaviour: private
per-user directories only, symlinks/foreign files never trusted, atomic
writes that replace the directory entry instead of following it.

Run with:  python -m pytest tests/test_secure_assets.py -v
"""

import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_app_manager import styles  # noqa: E402


def arrow_name(color=None):
    color = (color or styles.READABLE_PALETTE['overlay1']).lstrip('#')
    return f"combo-arrow-{color}.png"


@pytest.fixture
def xdg_sandbox(tmp_path, monkeypatch):
    """Sandboxed per-user runtime + cache directories."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return runtime, cache


# --------------------------------------------------------------------------- #
# Placement and permissions
# --------------------------------------------------------------------------- #
def test_arrow_written_to_private_runtime_dir(qapp, xdg_sandbox):
    runtime, _ = xdg_sandbox

    arrow = styles._combo_arrow_path()

    assert arrow.parent == runtime / "omarchy-app-manager"
    assert stat.S_IMODE(os.lstat(arrow.parent).st_mode) == 0o700
    info = os.lstat(arrow)
    assert stat.S_ISREG(info.st_mode)
    assert info.st_uid == os.getuid()
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert arrow.read_bytes().startswith(b'\x89PNG')


def test_existing_permissive_dir_is_tightened(qapp, xdg_sandbox):
    runtime, _ = xdg_sandbox
    target = runtime / "omarchy-app-manager"
    target.mkdir()
    os.chmod(target, 0o755)

    arrow = styles._combo_arrow_path()

    assert arrow.parent == target
    assert stat.S_IMODE(os.lstat(target).st_mode) == 0o700


def test_owned_arrow_is_reused_without_rewrite(qapp, xdg_sandbox):
    first = styles._combo_arrow_path()
    info = os.lstat(first)

    again = styles._combo_arrow_path()

    assert again == first
    assert os.lstat(again).st_ino == info.st_ino  # same file, not rewritten


def test_build_app_qss_references_the_secure_arrow(qapp, xdg_sandbox):
    runtime, _ = xdg_sandbox

    qss = styles.build_app_qss()

    arrow = styles._combo_arrow_path()
    assert arrow.parent == runtime / "omarchy-app-manager"
    assert arrow.as_posix() in qss
    assert arrow.is_file()


# --------------------------------------------------------------------------- #
# Hostile paths
# --------------------------------------------------------------------------- #
def test_symlinked_directory_is_rejected_and_not_written_through(
        qapp, xdg_sandbox, tmp_path):
    runtime, cache = xdg_sandbox
    victim = tmp_path / "victim"
    victim.mkdir()
    (runtime / "omarchy-app-manager").symlink_to(victim)

    arrow = styles._combo_arrow_path()

    assert victim not in arrow.parent.parents
    assert list(victim.iterdir()) == []      # nothing written through the link
    assert arrow.parent == cache / "omarchy_app_manager" / "ui"
    assert arrow.is_file()


def test_planted_symlink_arrow_is_replaced_not_followed(
        qapp, xdg_sandbox, tmp_path, monkeypatch):
    runtime, _ = xdg_sandbox
    target_dir = runtime / "omarchy-app-manager"
    target_dir.mkdir(mode=0o700)

    # Existing-file victim: truncation would destroy it.
    victim = tmp_path / "notes.txt"
    victim.write_text("DO NOT CLOBBER", encoding="utf-8")
    planted = target_dir / arrow_name()
    planted.symlink_to(victim)

    arrow = styles._combo_arrow_path()
    assert victim.read_text(encoding="utf-8") == "DO NOT CLOBBER"
    assert stat.S_ISREG(os.lstat(arrow).st_mode)  # link itself was replaced

    # Dangling victim: writing through the link would create the target.
    monkeypatch.setitem(styles.READABLE_PALETTE, 'overlay1', '#112233')
    never = tmp_path / "never-created"
    planted2 = target_dir / arrow_name('#112233')
    planted2.symlink_to(never)

    arrow2 = styles._combo_arrow_path()
    assert not never.exists()
    assert stat.S_ISREG(os.lstat(arrow2).st_mode)


def test_foreign_owned_directories_fall_back_to_private_mkdtemp(
        qapp, tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    sandbox_tmp = tmp_path / "tmp"
    sandbox_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(sandbox_tmp))

    # Simulate directories owned by somebody else.
    real_uid = os.getuid()
    monkeypatch.setattr(styles.os, "getuid", lambda: real_uid + 1)

    arrow = styles._combo_arrow_path()

    assert arrow.parent.parent == sandbox_tmp  # fresh mkdtemp, not XDG paths
    assert stat.S_IMODE(os.lstat(arrow.parent).st_mode) == 0o700
    assert arrow.is_file()
