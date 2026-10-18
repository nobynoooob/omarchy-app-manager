"""
Tests for AppImage icon extraction and its UI integration.

Real AppImages cannot be fabricated portably, so the "runtime" stand-in is a
small shell script that answers ``--appimage-extract <pattern>`` by
materialising a ``squashfs-root/`` tree in its working directory — exactly the
contract the production code relies on.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_app_manager import appimage_icons as icons  # noqa: E402


PNG_WITH_HINT = """
pattern="$2"
mkdir -p squashfs-root/usr/share/icons/hicolor/256x256/apps
printf 'real' > squashfs-root/usr/share/icons/hicolor/256x256/apps/myapp.png
mkdir -p squashfs-root/usr/share/doc
printf 'decoy payload that is clearly longer than the real icon bytes' \\
    > squashfs-root/usr/share/doc/splash.png
cat > squashfs-root/myapp.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Icon=myapp
DESKTOP
exit 0
"""

PNG_NO_HINT = """
mkdir -p squashfs-root/usr/share/icons/hicolor/128x128/apps
printf 'small' > squashfs-root/usr/share/icons/hicolor/128x128/apps/small.png
printf 'a considerably longer payload' \\
    > squashfs-root/usr/share/icons/hicolor/128x128/apps/detailed.png
mkdir -p squashfs-root/opt/assets
printf 'xxxx' > squashfs-root/opt/assets/hero.png
exit 0
"""

SVG_ONLY = """
if [ "$2" = "*.svg" ]; then
    mkdir -p squashfs-root/usr/share/icons/hicolor/scalable/apps
    printf '<svg/>' > squashfs-root/usr/share/icons/hicolor/scalable/apps/app.svg
fi
exit 0
"""

NO_ICON = """
exit 0
"""

SYMLINKED_ICON = """
if [ "$2" = "*.png" ]; then
    mkdir -p squashfs-root
    ln -sf usr/share/icons/hicolor/512x512/apps/sym-app.png squashfs-root/sym-app.png
elif [ "$2" = "usr/share/icons/hicolor/512x512/apps/sym-app.png" ]; then
    mkdir -p squashfs-root/usr/share/icons/hicolor/512x512/apps
    printf 'linked-real-icon' > squashfs-root/usr/share/icons/hicolor/512x512/apps/sym-app.png
fi
exit 0
"""

EVIL_SYMLINK = """
echo "$2" >> "{marker}"
if [ "$2" = "*.png" ]; then
    mkdir -p squashfs-root
    ln -sf /etc/passwd squashfs-root/evil.png
fi
exit 0
"""


def fake_appimage(path, body, executable=True):
    """Shell-script stand-in for an AppImage runtime."""
    path = Path(path)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)
    return path


@pytest.fixture
def icon_cache(tmp_path, monkeypatch):
    """Sandbox the cache via the standard XDG location."""
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_root))
    monkeypatch.delenv("OMARCHY_APPIMAGE_ICON_CACHE", raising=False)
    return cache_root / "omarchy_app_manager" / "icons"


def cache_icons(icon_cache):
    return sorted(icon_cache.glob("*")) if icon_cache.is_dir() else []


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def test_extracts_desktop_declared_icon_into_cache(tmp_path, monkeypatch, icon_cache):
    tmp_root = tmp_path / "tmproot"
    tmp_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_root))

    appimage = fake_appimage(tmp_path / "MyApp-1.0.AppImage", PNG_WITH_HINT)
    icon = icons.extract_appimage_icon(appimage)

    assert icon is not None
    path = Path(icon)
    assert path.is_file()
    assert path.parent == icon_cache
    assert path.name.startswith("MyApp-1.0-")
    assert path.suffix == ".png"
    # The desktop-referenced icon wins over the (larger) decoy.
    assert path.read_text() == "real"
    # Only the extracted icon survives; no squashfs/temp artifacts.
    assert cache_icons(icon_cache) == [path]
    assert list(tmp_root.iterdir()) == []


def test_cache_hit_reuses_icon_without_rerunning(tmp_path, monkeypatch, icon_cache):
    marker = tmp_path / "runs.log"
    body = f'echo "$2" >> "{marker}"\n' + PNG_WITH_HINT
    appimage = fake_appimage(tmp_path / "MyApp-1.0.AppImage", body)

    first = icons.extract_appimage_icon(appimage)
    assert first is not None
    runs_after_first = marker.read_text().splitlines()
    assert runs_after_first  # the runtime really was asked to extract

    second = icons.extract_appimage_icon(appimage)
    assert second == first
    assert marker.read_text().splitlines() == runs_after_first


def test_rebuilt_appimage_gets_fresh_icon_and_prunes_old(tmp_path, icon_cache):
    appimage = fake_appimage(tmp_path / "MyApp-1.0.AppImage", PNG_WITH_HINT)
    first = icons.extract_appimage_icon(appimage)
    assert first is not None

    # Rebuild: same path, different content/size -> different cache key.
    appimage.write_text(appimage.read_text() + "# rebuilt\n", encoding="utf-8")
    second = icons.extract_appimage_icon(appimage)

    assert second is not None and second != first
    assert cache_icons(icon_cache) == [Path(second)]


def test_prefers_bigger_resolution_bucket_then_bytes(tmp_path, icon_cache):
    appimage = fake_appimage(tmp_path / "NoHint.AppImage", PNG_NO_HINT)
    icon = icons.extract_appimage_icon(appimage)
    assert icon is not None
    # 128x128 'apps' icon beats the unsized (0-score) bigger decoy, and the
    # larger file wins within the same bucket.
    assert Path(icon).read_text() == "a considerably longer payload"


def test_svg_fallback_when_no_png_exists(tmp_path, icon_cache):
    appimage = fake_appimage(tmp_path / "Vector.AppImage", SVG_ONLY)
    icon = icons.extract_appimage_icon(appimage)
    assert icon is not None
    assert Path(icon).suffix == ".svg"
    assert Path(icon).read_text() == "<svg/>"


def test_invalid_appimage_returns_none(tmp_path, icon_cache):
    junk = tmp_path / "broken.AppImage"
    junk.write_text("this is not an executable at all", encoding="utf-8")
    assert icons.extract_appimage_icon(junk) is None
    assert cache_icons(icon_cache) == []


def test_appimage_without_icon_returns_none(tmp_path, icon_cache):
    appimage = fake_appimage(tmp_path / "Empty.AppImage", NO_ICON)
    assert icons.extract_appimage_icon(appimage) is None
    assert cache_icons(icon_cache) == []


def test_timeout_returns_none(tmp_path, icon_cache):
    appimage = fake_appimage(tmp_path / "Slow.AppImage", "exec sleep 30\n")
    started = time.monotonic()
    assert icons.extract_appimage_icon(appimage, timeout=0.3) is None
    assert time.monotonic() - started < 5.0
    assert cache_icons(icon_cache) == []


def test_non_executable_appimage_is_made_runnable(tmp_path, icon_cache):
    appimage = fake_appimage(tmp_path / "Locked.AppImage", PNG_WITH_HINT,
                             executable=False)
    icon = icons.extract_appimage_icon(appimage)
    assert icon is not None
    assert os.access(appimage, os.X_OK)


def test_non_appimage_files_are_never_executed(tmp_path, icon_cache):
    marker = tmp_path / "runs.log"
    body = f'echo "$2" >> "{marker}"\n' + PNG_WITH_HINT
    script = fake_appimage(tmp_path / "helper.sh", body)

    assert icons.extract_appimage_icon(script) is None
    assert icons.cached_appimage_icon_path(script) is None
    assert not marker.exists()


def test_follows_root_symlink_to_real_icon(tmp_path, icon_cache):
    marker = tmp_path / "runs.log"
    body = f'echo "$2" >> "{marker}"\n' + SYMLINKED_ICON
    appimage = fake_appimage(tmp_path / "SymApp.AppImage", body)

    icon = icons.extract_appimage_icon(appimage)

    assert icon is not None
    assert Path(icon).suffix == ".png"
    assert Path(icon).read_text() == "linked-real-icon"
    # The target path was requested explicitly after the dangling symlink.
    assert "usr/share/icons/hicolor/512x512/apps/sym-app.png" in marker.read_text()


def test_escaping_symlinks_are_never_read_or_extracted(tmp_path, icon_cache):
    marker = tmp_path / "runs.log"
    body = EVIL_SYMLINK.format(marker=marker)
    appimage = fake_appimage(tmp_path / "Evil.AppImage", body)

    assert icons.extract_appimage_icon(appimage) is None
    assert cache_icons(icon_cache) == []
    # Only the fixed probe set ran; the symlink target was never requested.
    assert marker.read_text().splitlines() == [
        "*.desktop", "*.png", "*.desktop", "*.svg",
    ]


def test_is_appimage_is_case_insensitive(tmp_path):
    assert icons.is_appimage("Foo.APPIMAGE")
    assert icons.is_appimage(tmp_path / "foo.appimage")
    assert not icons.is_appimage(tmp_path / "foo.zip")
    assert not icons.is_appimage("")


def test_cache_dir_honours_override_env(tmp_path, monkeypatch):
    override = tmp_path / "custom-icons"
    monkeypatch.setenv("OMARCHY_APPIMAGE_ICON_CACHE", str(override))
    assert icons.get_icon_cache_dir() == override

    appimage = fake_appimage(tmp_path / "MyApp-1.0.AppImage", PNG_WITH_HINT)
    icon = icons.extract_appimage_icon(appimage)
    assert icon is not None
    assert Path(icon).parent == override


def test_cached_lookup_matches_extraction(tmp_path, icon_cache):
    appimage = fake_appimage(tmp_path / "MyApp-1.0.AppImage", PNG_WITH_HINT)
    assert icons.cached_appimage_icon_path(appimage) is None
    icon = icons.extract_appimage_icon(appimage)
    assert icons.cached_appimage_icon_path(appimage) == icon


# --------------------------------------------------------------------------- #
# UI integration
# --------------------------------------------------------------------------- #
def test_detect_icon_for_path_uses_extracted_cache(qapp, tmp_path, icon_cache):
    from omarchy_app_manager.ui_mainwindow import detect_icon_for_path

    appimage = fake_appimage(tmp_path / "MyApp-1.0.AppImage", PNG_WITH_HINT)
    icon = icons.extract_appimage_icon(appimage)
    assert icon is not None
    assert detect_icon_for_path(appimage, "My App") == icon

    # A hand-placed sibling still outranks the cached extraction.
    sibling = tmp_path / "MyApp-1.0.png"
    sibling.write_bytes(b"x")
    assert detect_icon_for_path(appimage, "My App") == str(sibling)


def test_dialog_extracts_icon_in_background_after_consent(
        qapp, tmp_path, icon_cache, monkeypatch):
    from omarchy_app_manager.ui_mainwindow import CategoryDialog

    appimage = fake_appimage(tmp_path / "MyApp-1.0.AppImage", PNG_WITH_HINT)
    dialog = CategoryDialog()
    dialog.apply_prefill({"path": str(appimage), "name": "My App"})

    # Prefill alone never executes the AppImage; extraction is opt-in.
    assert dialog.icon_input.text().strip() == ""
    assert dialog.extract_button.isVisibleTo(dialog)

    monkeypatch.setattr(
        CategoryDialog, "_confirm_extraction", lambda self, path: True)
    dialog.extract_button.click()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not dialog.icon_input.text().strip():
        qapp.processEvents()
        time.sleep(0.01)

    icon_path = dialog.icon_input.text().strip()
    assert icon_path, "background extraction never filled the icon field"
    assert Path(icon_path).is_file()
    assert Path(icon_path).parent == icon_cache
    # The live preview picked it up (not the initial badge).
    assert not dialog.icon_preview.pixmap().isNull()


def test_dialog_falls_back_gracefully_when_extraction_fails(
        qapp, tmp_path, icon_cache, monkeypatch):
    from omarchy_app_manager.ui_mainwindow import CategoryDialog

    junk = tmp_path / "broken.AppImage"
    junk.write_text("not an executable", encoding="utf-8")

    dialog = CategoryDialog()
    dialog.apply_prefill({"path": str(junk), "name": "Broken"})

    monkeypatch.setattr(
        CategoryDialog, "_confirm_extraction", lambda self, path: True)
    dialog.extract_button.click()

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert dialog.icon_input.text() == ""
    # Falls back to the stylized initial badge, and the dialog stays alive.
    assert not dialog.icon_preview.pixmap().isNull()
