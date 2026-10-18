"""
Verification tests for the OmaApp Manager desktop-entry backend.

Run with:  python -m pytest tests/ -v

The tests operate in a sandbox directory (set via ``OMARCHY_APPS_DIR``) so the
user's real ``~/.local/share/applications/`` is never modified.
"""

import os
import sys
import configparser
from pathlib import Path

import pytest

# Make ``omarchy_app_manager`` importable when running from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_app_manager import desktop_manager as dm  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect the applications directory to a fresh temporary folder."""
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    monkeypatch.setenv("OMARCHY_APPS_DIR", str(apps_dir))
    return apps_dir


def read_raw(path):
    return Path(path).read_text(encoding="utf-8")


def read_section(path):
    """Read a .desktop file the way an external tool would."""
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    cfg.optionxform = str
    with open(path, encoding="utf-8") as fh:
        cfg.read_file(fh)
    return cfg["Desktop Entry"]


# --------------------------------------------------------------------------- #
# 1. Scanning
# --------------------------------------------------------------------------- #
def test_scan_real_applications_dir():
    """Scanning the real ~/.local/share/applications/ yields a list of dicts."""
    os.environ.pop("OMARCHY_APPS_DIR", None)
    apps = dm.get_installed_apps()
    assert isinstance(apps, list)
    for app in apps:
        assert "name" in app and "path" in app and "category" in app
        assert Path(app["file_path"]).exists()


def test_scan_sandbox_is_empty(sandbox):
    assert dm.get_applications_dir() == sandbox
    assert dm.get_installed_apps() == []


# --------------------------------------------------------------------------- #
# 2. Creating
# --------------------------------------------------------------------------- #
def test_create_desktop_file(sandbox):
    path = dm.create_desktop_file({
        "name": "Omarchy Test App",
        "path": "/bin/true",
        "icon": "/tmp/test-icon.png",
        "category": "Game",
    })

    assert path.exists(), "the .desktop file must be written to disk"
    assert path.parent == sandbox

    raw = read_raw(path)
    assert raw.startswith("[Desktop Entry]"), "must begin with the section header"
    assert "Name=Omarchy Test App" in raw
    assert "Exec=/bin/true" in raw
    assert "Icon=/tmp/test-icon.png" in raw
    assert "Categories=Game;Application;" in raw

    # File must be executable.
    assert os.access(path, os.X_OK)

    # It must show up in a scan.
    names = [a["name"] for a in dm.get_installed_apps()]
    assert "Omarchy Test App" in names


def test_create_preserves_key_case(sandbox):
    path = dm.create_desktop_file({
        "name": "Case Test", "path": "/bin/true", "icon": "", "category": "Utility",
    })
    section = read_section(path)
    for key in ("Name", "Exec", "Icon", "Categories", "Type"):
        assert key in section, f"key {key!r} lost its case"


# --------------------------------------------------------------------------- #
# 3. Updating
# --------------------------------------------------------------------------- #
def test_update_name_and_category_in_place(sandbox):
    path = dm.create_desktop_file({
        "name": "Old Name", "path": "/bin/true", "icon": "", "category": "Utility",
    })

    returned = dm.update_desktop_file({
        "name": "New Name",
        "path": "/bin/true",
        "icon": "",
        "category": "AudioVideo",
    }, path)

    # Same file, no orphans.
    assert returned == path
    assert path.exists()
    assert len(list(sandbox.glob("*.desktop"))) == 1

    section = read_section(path)
    assert section["Name"] == "New Name"
    assert section["Categories"] == "AudioVideo;Application;"

    # The scan reflects the change immediately.
    app = next(a for a in dm.get_installed_apps() if a["name"] == "New Name")
    assert app["category"] == "AudioVideo"


def test_update_changes_icon(sandbox):
    path = dm.create_desktop_file({
        "name": "Icon Test", "path": "/bin/true", "icon": "", "category": "Utility",
    })
    dm.update_desktop_file({
        "name": "Icon Test", "path": "/bin/true",
        "icon": "/tmp/new-icon.svg", "category": "Utility",
    }, path)

    assert read_section(path)["Icon"] == "/tmp/new-icon.svg"


def test_update_preserves_exec_arguments(sandbox):
    """A quoted path with spaces and trailing args must round-trip intact."""
    path = dm.create_desktop_file({
        "name": "Args Test",
        "path": '"/opt/my apps/run.sh" --flag %U',
        "icon": "",
        "category": "Utility",
    })

    app = next(a for a in dm.get_installed_apps() if a["name"] == "Args Test")
    # first token ignores the args, but the full Exec line is preserved.
    assert app["path"] == "/opt/my apps/run.sh"
    assert app["exec_path"] == '"/opt/my apps/run.sh" --flag %U'

    # Edit only the name; Exec (with %U) must be untouched.
    dm.update_desktop_file({
        "name": "Args Test Renamed",
        "path": app["exec_path"],
        "icon": "",
        "category": "Utility",
    }, path)

    section = read_section(path)
    assert section["Name"] == "Args Test Renamed"
    assert section["Exec"] == '"/opt/my apps/run.sh" --flag %U'


def test_update_preserves_unknown_keys(sandbox):
    path = dm.create_desktop_file({
        "name": "Extra Keys", "path": "/bin/true", "icon": "", "category": "Utility",
    })
    # Append a custom key the way another tool might.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("StartupWMClass=custom-class\n")

    dm.update_desktop_file({
        "name": "Extra Keys", "path": "/bin/true",
        "icon": "", "category": "Development",
    }, path)

    assert read_section(path)["StartupWMClass"] == "custom-class"


def test_update_nonexistent_path_creates_file(sandbox):
    """Updating a path that does not exist creates it (never fails silently)."""
    target = sandbox / "brand_new.desktop"
    returned = dm.update_desktop_file({
        "name": "Brand New", "path": "/bin/true", "icon": "", "category": "Utility",
    }, target)
    assert returned == target
    assert target.exists()


# --------------------------------------------------------------------------- #
# 4. Deleting
# --------------------------------------------------------------------------- #
def test_delete_desktop_file(sandbox):
    path = dm.create_desktop_file({
        "name": "Delete Me", "path": "/bin/true", "icon": "", "category": "Utility",
    })
    app = next(a for a in dm.get_installed_apps() if a["name"] == "Delete Me")

    deleted = dm.delete_desktop_file(app)

    assert deleted == path
    assert not path.exists(), "the .desktop file must be gone from disk"
    assert dm.get_installed_apps() == []


def test_delete_after_rename_uses_exact_path(sandbox):
    """Renaming (but not renaming the file) must not break deletion."""
    path = dm.create_desktop_file({
        "name": "Original", "path": "/bin/true", "icon": "", "category": "Utility",
    })
    dm.update_desktop_file({
        "name": "Renamed Completely", "path": "/bin/true",
        "icon": "", "category": "Utility",
    }, path)
    # Filename still slugged from the *original* name.
    app = next(a for a in dm.get_installed_apps() if a["name"] == "Renamed Completely")

    dm.delete_desktop_file(app)
    assert not path.exists()


def test_delete_missing_raises(sandbox):
    with pytest.raises(FileNotFoundError):
        dm.delete_desktop_file({"name": "Ghost", "file_path": sandbox / "ghost.desktop"})


# --------------------------------------------------------------------------- #
# Helpers / edge cases
# --------------------------------------------------------------------------- #
def test_parse_category():
    assert dm.parse_category("Game;Application;") == "Game"
    assert dm.parse_category("AudioVideo;Application;") == "AudioVideo"
    assert dm.parse_category("Development;") == "Development"
    assert dm.parse_category("") == "Utility"
    assert dm.parse_category("SomethingElse;") == "Utility"


def test_first_exec_token():
    assert dm.first_exec_token("/bin/true --flag") == "/bin/true"
    assert dm.first_exec_token('"/path with spaces/app" --flag') == "/path with spaces/app"
    assert dm.first_exec_token("") == ""


def test_split_exec_and_normalize_unquoted_spaces(sandbox):
    """An unquoted path with spaces must resolve to the real existing file."""
    spaced = sandbox / "New Volume" / "Tools"
    spaced.mkdir(parents=True)
    target = spaced / "Liner.AppImage"
    target.write_text("#!/bin/sh\n")

    # Unquoted (legacy) form written by older versions of this tool.
    legacy = f"{target} --flag %U"
    command, args = dm.split_exec(legacy)
    assert command == str(target)
    assert args == "--flag %U"

    # It must validate, and normalizing must quote it correctly.
    assert dm.command_is_available(legacy) is True
    assert dm.normalize_exec(legacy) == f'"{target}" --flag %U'


def test_normalize_exec_leaves_plain_commands_untouched():
    assert dm.normalize_exec("firefox %U") == "firefox %U"
    assert dm.normalize_exec("env FOO=bar /usr/bin/app %F") == "env FOO=bar /usr/bin/app %F"
    assert dm.normalize_exec('"/a b/app"') == '"/a b/app"'
    assert dm.normalize_exec("") == ""


# --------------------------------------------------------------------------- #
# System / helper entry detection
# --------------------------------------------------------------------------- #
def write_raw_desktop(path, name, exec_line, extra=""):
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        f"Exec={exec_line}\n"
        "Categories=Utility;\n" + extra,
        encoding="utf-8",
    )


def test_effective_command_skips_env_and_var_prefixes():
    assert dm._effective_command("/usr/bin/firefox %u") == "/usr/bin/firefox"
    assert dm._effective_command(
        "env WINEPREFIX=/x wine start /ProgIDOpen wscript %1"
    ) == "wine"
    assert dm._effective_command('env "WINEPREFIX=/x y" wine start %1') == "wine"
    assert dm._effective_command("") == ""


def test_no_display_flag_is_parsed(sandbox):
    write_raw_desktop(sandbox / "hidden.desktop", "Hidden", "/bin/true", "NoDisplay=true\n")
    write_raw_desktop(sandbox / "shown.desktop", "Shown", "/bin/true")

    apps = {a["name"]: a for a in dm.get_installed_apps()}
    assert apps["Hidden"]["no_display"] is True
    assert apps["Shown"]["no_display"] is False


def test_is_system_entry_detection(sandbox):
    dm.create_desktop_file({
        "name": "Real App", "path": "/bin/true", "icon": "", "category": "Utility",
    })
    write_raw_desktop(
        sandbox / "wine-extension-wscript.desktop", "wscript",
        "env WINEPREFIX=/x wine start /ProgIDOpen wscript %1", "NoDisplay=true\n",
    )
    write_raw_desktop(sandbox / "hidden.desktop", "Hidden", "/bin/true", "NoDisplay=true\n")
    write_raw_desktop(
        sandbox / "python-helper.desktop", "Python", "env FOO=bar /usr/bin/python %f",
    )
    write_raw_desktop(
        sandbox / "firefox.desktop", "Firefox",
        "env MOZ_ENABLE_WAYLAND=1 /usr/bin/firefox %u",
    )

    apps = {a["name"]: a for a in dm.get_installed_apps()}
    assert dm.is_system_entry(apps["wscript"]) is True   # NoDisplay + helper name
    assert dm.is_system_entry(apps["Hidden"]) is True    # NoDisplay only
    assert dm.is_system_entry(apps["Python"]) is True    # helper name
    assert dm.is_system_entry(apps["Firefox"]) is False  # env-prefixed real app
    assert dm.is_system_entry(apps["Real App"]) is False


def test_get_installed_apps_filters_system_entries(sandbox):
    dm.create_desktop_file({
        "name": "Real App", "path": "/bin/true", "icon": "", "category": "Utility",
    })
    dm.create_desktop_file({
        "name": "Firefox", "path": "/bin/true", "icon": "", "category": "Utility",
    })
    write_raw_desktop(
        sandbox / "wine-extension-wscript.desktop", "wscript",
        "env WINEPREFIX=/x wine start /ProgIDOpen wscript %1", "NoDisplay=true\n",
    )
    write_raw_desktop(sandbox / "hidden.desktop", "Hidden", "/bin/true", "NoDisplay=true\n")

    custom = {a["name"] for a in dm.get_installed_apps(include_system=False)}
    assert custom == {"Real App", "Firefox"}

    # The default view keeps every entry (backward compatible).
    everything = {a["name"] for a in dm.get_installed_apps()}
    assert custom <= everything
    assert "Hidden" in everything and "wscript" in everything


def test_command_is_available():
    assert dm.command_is_available("/bin/true") is True
    assert dm.command_is_available("sh") is True
    assert dm.command_is_available("/nonexistent/binary") is False


def test_configparser_percent_roundtrip(sandbox):
    """Values containing '%' must not raise with interpolation enabled."""
    path = dm.create_desktop_file({
        "name": "Percent Test", "path": "firefox %U", "icon": "", "category": "Utility",
    })
    assert read_section(path)["Exec"] == "firefox %U"
    app = next(a for a in dm.get_installed_apps() if a["name"] == "Percent Test")
    assert app["exec_path"] == "firefox %U"


# --------------------------------------------------------------------------- #
# 8. Performance wrappers (GameMode / NVIDIA PRIME offload)
# --------------------------------------------------------------------------- #
def test_wrap_exec_command_composition():
    assert dm.wrap_exec_command("/usr/bin/app") == "/usr/bin/app"
    assert dm.wrap_exec_command("/usr/bin/app", gamemode=True) == (
        "gamemoderun /usr/bin/app")
    assert dm.wrap_exec_command("/usr/bin/app", prime_render_offload=True) == (
        "env __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia "
        "/usr/bin/app")
    assert dm.wrap_exec_command(
        "/usr/bin/app", gamemode=True, prime_render_offload=True) == (
        "gamemoderun env __NV_PRIME_RENDER_OFFLOAD=1 "
        "__GLX_VENDOR_LIBRARY_NAME=nvidia /usr/bin/app")
    assert dm.wrap_exec_command("") == ""


@pytest.mark.parametrize("gamemode,prime", [
    (True, True), (True, False), (False, True),
])
def test_wrap_unwrap_round_trip(gamemode, prime):
    line = '"/opt/my apps/run.sh" --flag %U'
    wrapped = dm.wrap_exec_command(
        line, gamemode=gamemode, prime_render_offload=prime)
    inner, detected_gamemode, detected_prime = dm.unwrap_exec_command(wrapped)
    assert inner == line
    assert detected_gamemode is gamemode
    assert detected_prime is prime


def test_unwrap_accepts_reversed_env_order():
    line = ("gamemoderun env __GLX_VENDOR_LIBRARY_NAME=nvidia "
            "__NV_PRIME_RENDER_OFFLOAD=1 /usr/bin/app")
    assert dm.unwrap_exec_command(line) == ("/usr/bin/app", True, True)


def test_unwrap_leaves_foreign_prefixes_alone():
    foreign = "env WINEPREFIX=/x wine start %1"
    assert dm.unwrap_exec_command(foreign) == (foreign, False, False)

    partial = "env __NV_PRIME_RENDER_OFFLOAD=1 /usr/bin/app"
    assert dm.unwrap_exec_command(partial) == (partial, False, False)

    mixed = ("env FOO=1 __NV_PRIME_RENDER_OFFLOAD=1 "
             "__GLX_VENDOR_LIBRARY_NAME=nvidia /usr/bin/app")
    assert dm.unwrap_exec_command(mixed) == (mixed, False, False)


def test_create_writes_perf_keys_and_wmclass(sandbox):
    path = dm.create_desktop_file({
        "name": "Wrapped", "path": "/bin/true", "icon": "", "category": "Utility",
        "gamemode": True, "prime_gpu": True, "startup_wm_class": "wrapped-app",
    })
    section = read_section(path)
    assert section["Exec"] == (
        "gamemoderun env __NV_PRIME_RENDER_OFFLOAD=1 "
        "__GLX_VENDOR_LIBRARY_NAME=nvidia /bin/true")
    assert section[dm.PERF_GAMEMODE_KEY] == "true"
    assert section[dm.PERF_PRIME_KEY] == "true"
    assert section["StartupWMClass"] == "wrapped-app"

    app = dm.parse_desktop_file(path)
    assert app["gamemode"] is True
    assert app["prime_gpu"] is True
    assert app["startup_wm_class"] == "wrapped-app"
    # The editor sees (and validates) the unwrapped command.
    assert app["exec_path"] == "/bin/true"
    assert app["path"] == "/bin/true"
    assert "gamemoderun" in app["raw_exec"]


def test_parse_detects_hand_wrapped_exec_without_keys(sandbox):
    write_raw_desktop(
        sandbox / "hand-wrapped.desktop", "Hand Wrapped",
        "gamemoderun env __NV_PRIME_RENDER_OFFLOAD=1 "
        "__GLX_VENDOR_LIBRARY_NAME=nvidia /bin/true",
    )
    app = dm.parse_desktop_file(sandbox / "hand-wrapped.desktop")
    assert app["gamemode"] is True
    assert app["prime_gpu"] is True
    assert app["exec_path"] == "/bin/true"


def test_update_round_trip_is_idempotent(sandbox):
    path = dm.create_desktop_file({
        "name": "Round Trip", "path": "/bin/true", "icon": "", "category": "Utility",
        "gamemode": True, "prime_gpu": True,
    })
    parsed = dm.parse_desktop_file(path)
    dm.update_desktop_file(parsed, path)
    assert dm.parse_desktop_file(path)["exec_path"] == "/bin/true"
    assert read_section(path)["Exec"] == (
        "gamemoderun env __NV_PRIME_RENDER_OFFLOAD=1 "
        "__GLX_VENDOR_LIBRARY_NAME=nvidia /bin/true")


def test_update_removes_disabled_wrappers(sandbox):
    path = dm.create_desktop_file({
        "name": "Unwrap Me", "path": "/bin/true", "icon": "", "category": "Utility",
        "gamemode": True, "prime_gpu": True, "startup_wm_class": "unwrapped",
    })
    dm.update_desktop_file({
        "name": "Unwrap Me", "path": "/bin/true", "icon": "", "category": "Utility",
        "gamemode": False, "prime_gpu": False, "startup_wm_class": "",
    }, path)
    section = read_section(path)
    assert section["Exec"] == "/bin/true"
    assert dm.PERF_GAMEMODE_KEY not in section
    assert dm.PERF_PRIME_KEY not in section
    assert "StartupWMClass" not in section


def test_compose_exec_line_uses_parsed_flags():
    assert dm.compose_exec_line({
        "exec_path": "/usr/bin/app %U", "path": "/usr/bin/app",
        "gamemode": True, "prime_gpu": False,
    }) == "gamemoderun /usr/bin/app %U"
    assert dm.compose_exec_line({"path": "firefox"}) == "firefox"
