"""
Tests for dynamic system-theme detection (Omarchy / pywal / Qt / GTK).

Every test runs against a sandbox home directory so the developer's real
desktop colors are never read. The shared ``isolated_theme`` fixture in
``conftest.py`` restores the live palette after each test.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_app_manager import styles, theme  # noqa: E402
from omarchy_app_manager.ui_mainwindow import OmarchyAppManager  # noqa: E402


OMARCHY_ANSI_TOML = """\
# Accent and UI colors
accent = "#F25623"
active_border_color = "#88A57D"

foreground = "#CCD0CF"
background = "#171717"

selection_foreground = "#171717"
selection_background = "#F56E0F"

color0 = "#171717"
color1 = "#aeab94"
color2 = "#F25623"
color3 = "#757864"
color4 = "#88A57D"
color5 = "#F56E0F"
color6 = "#7b837b"
color7 = "#a6ada6"
color8 = "#525252"
color15 = "#bcbfbc"
"""

OMARCHY_NAMED_TOML = """\
mode = "dark"

accent = "#89b4fa"
selection = "#45475a"
muted = "#585b70"

background = "#1e1e2e"
dark_background = "#161622"
darker_background = "#101019"
lighter_background = "#313244"

foreground = "#cdd6f4"
dark_foreground = "#6c7086"
light_foreground = "#bac2de"
bright_foreground = "#cdd6f4"

red = "#f38ba8"
yellow = "#f9e2af"
orange = "#f6b6ab"
green = "#a6e3a1"
cyan = "#94e2d5"
blue = "#89b4fa"
"""


def write_omarchy_theme(home, name="greek-noir", content=OMARCHY_ANSI_TOML):
    theme_dir = home / ".local/state/omarchy/current/theme"
    theme_dir.mkdir(parents=True, exist_ok=True)
    (theme_dir / "colors.toml").write_text(content, encoding="utf-8")
    (theme_dir.parent / "theme.name").write_text(name, encoding="utf-8")
    return theme_dir


# --------------------------------------------------------------------------- #
# Fallback
# --------------------------------------------------------------------------- #
def test_fallback_when_no_theme_is_available(clean_home):
    palette, source = theme.detect_system_theme()
    assert palette is None and source is None

    applied = theme.load_theme()
    assert applied == theme.FALLBACK_SOURCE
    assert styles.PALETTE_SOURCE == theme.FALLBACK_SOURCE
    assert styles.PALETTE["base"] == "#1e1e2e"
    assert styles.PALETTE["mauve"] == "#cba6f7"


def test_no_theme_env_var_forces_fallback(clean_home, monkeypatch):
    write_omarchy_theme(clean_home)
    monkeypatch.setenv("OMARCHY_APPMANAGER_NO_THEME", "1")

    assert theme.load_theme() == theme.FALLBACK_SOURCE
    assert styles.PALETTE["base"] == "#1e1e2e"


# --------------------------------------------------------------------------- #
# Omarchy
# --------------------------------------------------------------------------- #
def test_omarchy_ansi_theme_detection(clean_home):
    write_omarchy_theme(clean_home)

    source = theme.load_theme()
    assert "omarchy" in source.lower() and "greek" in source.lower()

    palette = styles.PALETTE
    assert palette["base"] == "#171717"
    assert palette["text"] == "#ccd0cf"
    assert palette["mauve"] == "#f25623"       # accent drives highlights
    assert palette["blue"] == "#88a57d"        # ANSI slot color4
    assert palette["red"] == "#aeab94"         # ANSI slot color1
    # Derived neutrals must sit between background and foreground.
    assert palette["surface0"] != palette["base"]
    assert palette["mantle"] != palette["base"]


def test_omarchy_named_theme_detection(clean_home):
    write_omarchy_theme(clean_home, name="catppuccin", content=OMARCHY_NAMED_TOML)

    palette, source = theme.detect_system_theme()
    assert "omarchy" in source.lower()
    assert palette["base"] == "#1e1e2e"
    assert palette["crust"] == "#101019"
    assert palette["mantle"] == "#161622"
    assert palette["surface0"] == "#313244"
    assert palette["surface1"] == "#45475a"
    assert palette["surface2"] == "#585b70"
    assert palette["overlay0"] == "#6c7086"
    assert palette["subtext1"] == "#bac2de"
    assert palette["mauve"] == "#89b4fa"
    assert palette["peach"] == "#f6b6ab"
    assert palette["teal"] == "#94e2d5"


def test_omarchy_works_from_config_dir(clean_home):
    """Older/layout variant: theme under ~/.config/omarchy/current."""
    theme_dir = clean_home / ".config/omarchy/current/theme"
    theme_dir.mkdir(parents=True, exist_ok=True)
    (theme_dir / "colors.toml").write_text(OMARCHY_ANSI_TOML, encoding="utf-8")

    palette, source = theme.detect_system_theme()
    assert "omarchy" in source.lower()
    assert palette["base"] == "#171717"


# --------------------------------------------------------------------------- #
# pywal
# --------------------------------------------------------------------------- #
def test_pywal_detection(clean_home):
    wal = clean_home / ".cache/wal"
    wal.mkdir(parents=True)
    (wal / "colors.json").write_text(json.dumps({
        "special": {
            "background": "#0f0f1a",
            "foreground": "#e0e0e0",
            "cursor": "#ff00ff",
        },
        "colors": {
            "color0": "#000000", "color1": "#ff5555", "color2": "#50fa7b",
            "color3": "#f1fa8c", "color4": "#bd93f9", "color5": "#ff79c6",
            "color6": "#8be9fd", "color7": "#f8f8f2",
        },
    }), encoding="utf-8")

    palette, source = theme.detect_system_theme()
    assert source == "pywal"
    assert palette["base"] == "#0f0f1a"
    assert palette["text"] == "#e0e0e0"
    assert palette["mauve"] == "#ff79c6"
    assert palette["red"] == "#ff5555"
    assert palette["green"] == "#50fa7b"


# --------------------------------------------------------------------------- #
# Qt color scheme
# --------------------------------------------------------------------------- #
def test_qt_scheme_detection(clean_home):
    conf_dir = clean_home / ".config/qt6ct"
    conf_dir.mkdir(parents=True)
    scheme = clean_home / "MyScheme.colors"
    scheme.write_text(
        "[Colors:Window]\n"
        "BackgroundNormal=23,23,23\n"
        "ForegroundNormal=204,208,207\n"
        "\n"
        "[Colors:View]\n"
        "BackgroundNormal=30,30,30\n"
        "\n"
        "[Colors:Button]\n"
        "BackgroundNormal=40,40,40\n"
        "\n"
        "[Colors:Selection]\n"
        "BackgroundNormal=242,86,35\n",
        encoding="utf-8",
    )
    (conf_dir / "qt6ct.conf").write_text(
        f"[General]\ncolor_scheme_path={scheme}\n", encoding="utf-8")

    palette, source = theme.detect_system_theme()
    assert source == "Qt palette"
    assert palette["base"] == "#171717"
    assert palette["text"] == "#ccd0cf"
    assert palette["mauve"] == "#f25623"


# --------------------------------------------------------------------------- #
# GTK
# --------------------------------------------------------------------------- #
def test_gtk_css_detection(clean_home):
    gtk = clean_home / ".config/gtk-4.0"
    gtk.mkdir(parents=True)
    (gtk / "gtk.css").write_text(
        "@define-color theme_bg_color #1a1b26;\n"
        "@define-color theme_fg_color #c0caf5;\n"
        "@define-color accent_bg_color #7aa2f7;\n",
        encoding="utf-8",
    )

    palette, source = theme.detect_system_theme()
    assert "gtk" in source.lower()
    assert palette["base"] == "#1a1b26"
    assert palette["text"] == "#c0caf5"
    assert palette["mauve"] == "#7aa2f7"


# --------------------------------------------------------------------------- #
# Priority + overrides
# --------------------------------------------------------------------------- #
def test_omarchy_beats_pywal(clean_home):
    write_omarchy_theme(clean_home)
    wal = clean_home / ".cache/wal"
    wal.mkdir(parents=True)
    (wal / "colors.json").write_text(json.dumps({
        "special": {"background": "#000000", "foreground": "#ffffff"},
    }), encoding="utf-8")

    palette, source = theme.detect_system_theme()
    assert "omarchy" in source.lower()
    assert palette["base"] == "#171717"


def test_theme_file_override_wins(clean_home, monkeypatch):
    custom = clean_home / "my-theme.toml"
    custom.write_text(
        'background = "#101010"\nforeground = "#f0f0f0"\naccent = "#ff0000"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OMARCHY_APPMANAGER_THEME_FILE", str(custom))

    palette, source = theme.detect_system_theme()
    assert "my-theme" in source
    assert palette["base"] == "#101010"
    assert palette["mauve"] == "#ff0000"


# --------------------------------------------------------------------------- #
# Derived structures + full app boot
# --------------------------------------------------------------------------- #
def test_apply_palette_rebuilds_derived_structures(qapp, clean_home):
    palette = theme._palette_from_colors({
        "background": "#101010", "foreground": "#f0f0f0", "accent": "#ff0000",
    })
    styles.apply_palette(palette, "Test theme")

    assert styles.PALETTE_SOURCE == "Test theme"
    assert styles.CARD_COLORS["hover_border"] == "#ff0000"
    assert styles.BUTTON_VARIANTS["primary"]["bg"] == "#ff0000"

    # Badge and button labels are WCAG-ensured against their own surfaces
    # (the raw accent is nudged toward white/black only when needed).
    tint = styles.CATEGORY_COLORS["AudioVideo"]
    assert styles.contrast_ratio(tint["text"], tint["bg"]) >= styles.WCAG_AA_RATIO
    primary = styles.BUTTON_VARIANTS["primary"]
    for surface in (primary["bg"], primary["hover"], primary["press"]):
        assert styles.contrast_ratio(primary["text"], surface) >= styles.WCAG_AA_RATIO
    assert primary["text"] in (palette["crust"], palette["white"])

    qss = styles.build_app_qss()
    assert styles.PALETTE["crust"] in qss   # window chrome color
    assert "#ff0000" in qss                 # accent reaches the stylesheet


def test_window_boots_with_detected_theme(qapp, clean_home, monkeypatch):
    write_omarchy_theme(clean_home)
    apps_dir = clean_home / "applications"
    apps_dir.mkdir()
    monkeypatch.setenv("OMARCHY_APPS_DIR", str(apps_dir))

    window = OmarchyAppManager()
    try:
        assert "omarchy" in styles.PALETTE_SOURCE.lower()
        assert styles.PALETTE["base"] == "#171717"
        assert styles.PALETTE["mauve"] == "#f25623"
    finally:
        window.close()
