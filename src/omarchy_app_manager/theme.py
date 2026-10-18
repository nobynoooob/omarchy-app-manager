"""
Dynamic system-theme detection.

Reads the colors currently applied to the user's desktop and maps them onto
the app palette so the window matches the rice out of the box:

  1. Omarchy current theme  ``$XDG_STATE_HOME/omarchy/current/theme/colors.toml``
  2. pywal                  ``$XDG_CACHE_HOME/wal/colors.json``
  3. Qt color scheme        qt6ct/qt5ct config or ``~/.local/share/color-schemes``
  4. GTK css                ``~/.config/gtk-{3,4}.0/gtk.css`` ``@define-color``

Falls back to the bundled Catppuccin Mocha palette when nothing is found.

Both Omarchy ``colors.toml`` schemas are supported: the rich named style
(``dark_background``, ``muted``, ``selection``...) shipped by stock themes,
and the ANSI style (``color0``-``color15``) used by hand-made themes; any role
the theme does not define is derived from ``background``/``foreground``.

Environment overrides:
  ``OMARCHY_APPMANAGER_THEME_FILE``  path to an explicit colors.toml/.json
  ``OMARCHY_APPMANAGER_NO_THEME``    set to ``1`` to force the Catppuccin fallback

Live reloading: :func:`resolve_theme` reports the file behind the active
theme; ``OmarchyAppManager`` watches it (and its enclosing directories, see
:func:`watch_paths`) so palette changes on disk are picked up without a
restart.
"""

import configparser
import json
import os
import re
from pathlib import Path

from .styles import (
    DEFAULT_PALETTE, THEME_PRESETS, apply_palette, blend_hex, preset_palette,
)

FALLBACK_SOURCE = 'Catppuccin Mocha (fallback)'

_HEX_RE = re.compile(r'#([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?')
_COLORS_TOML_RE = re.compile(
    r'^\s*([A-Za-z0-9_]+)\s*=\s*["\'](#[0-9a-fA-F]{6})["\']', re.MULTILINE)
_GTK_DEFINE_RE = re.compile(
    r'@define-color\s+([A-Za-z0-9_-]+)\s+(#[0-9a-fA-F]{6})')


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _normalize_hex(value):
    """Return ``#rrggbb`` for a valid hex color string, else None."""
    if not isinstance(value, str):
        return None
    match = _HEX_RE.fullmatch(value.strip())
    if not match:
        return None
    return f"#{match.group(1).lower()}"


def _clean_colors(mapping):
    return {
        str(key).lower(): hex_value
        for key, value in mapping.items()
        if (hex_value := _normalize_hex(value))
    }


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _read_colors_toml(path):
    """Parse a flat ``key = "#rrggbb"`` color file (colors.toml)."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError:
        return {}
    return {
        key.lower(): value
        for key, value in _COLORS_TOML_RE.findall(text)
    }


def _flatten_wal(data):
    """Flatten a pywal colors.json into a plain color-key dict."""
    colors = dict(data.get('colors') or {})
    special = data.get('special') or {}
    for key in ('background', 'foreground', 'cursor'):
        if special.get(key):
            colors.setdefault(key, special[key])
    return _clean_colors(colors)


def _parse_qt_rgb(raw):
    """Parse a Qt color scheme entry (``30,30,46`` or ``#1e1e2e``)."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith('#'):
        return _normalize_hex(raw)
    parts = [part.strip() for part in raw.split(',')]
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    red, green, blue = (int(part) for part in parts)
    if max(red, green, blue) > 255:
        return None
    return f"#{red:02x}{green:02x}{blue:02x}"


# --------------------------------------------------------------------------- #
# Color sources
# --------------------------------------------------------------------------- #
def _theme_display_name(theme_dir):
    for candidate in (theme_dir.parent / 'theme.name', theme_dir / 'theme.name'):
        try:
            raw = candidate.read_text(encoding='utf-8').strip()
        except OSError:
            continue
        if raw:
            return raw.replace('-', ' ').replace('_', ' ').title()
    return ''


def _detect_omarchy():
    state_home = os.environ.get('XDG_STATE_HOME') or str(
        Path.home() / '.local/state')
    candidates = [
        Path(state_home) / 'omarchy/current/theme/colors.toml',
        Path.home() / '.config/omarchy/current/theme/colors.toml',
    ]
    for path in candidates:
        colors = _read_colors_toml(path)
        if colors.get('background') and colors.get('foreground'):
            name = _theme_display_name(path.parent) or _theme_preset_name(colors)
            source = f'Omarchy theme ({name})' if name else 'Omarchy theme'
            return colors, source, str(path)
    return None


def _detect_pywal():
    cache_home = os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
    path = Path(cache_home) / 'wal/colors.json'
    data = _read_json(path)
    if not data:
        return None
    colors = _flatten_wal(data)
    colors.setdefault('accent', colors.get('color5', ''))
    if colors.get('background') and colors.get('foreground'):
        return colors, 'pywal', str(path)
    return None


def _detect_qt_scheme():
    scheme_path = None
    for conf in (Path.home() / '.config/qt6ct/qt6ct.conf',
                 Path.home() / '.config/qt5ct/qt5ct.conf'):
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(conf)
        except (configparser.Error, OSError):
            continue
        raw = parser.get('General', 'color_scheme_path', fallback='').strip()
        if raw:
            candidate = Path(raw).expanduser()
            if candidate.is_file():
                scheme_path = candidate
                break

    if scheme_path is None:
        schemes_dir = Path.home() / '.local/share/color-schemes'
        if schemes_dir.is_dir():
            schemes = sorted(schemes_dir.glob('*.colors'))
            scheme_path = schemes[0] if schemes else None
    if scheme_path is None:
        return None

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(scheme_path)
    except (configparser.Error, OSError):
        return None

    def entry(section, key):
        return _parse_qt_rgb(parser.get(section, key, fallback=''))

    background = (entry('Colors:Window', 'BackgroundNormal')
                  or entry('Colors:View', 'BackgroundNormal'))
    foreground = (entry('Colors:Window', 'ForegroundNormal')
                  or entry('Colors:View', 'ForegroundNormal'))
    if not (background and foreground):
        return None

    colors = {'background': background, 'foreground': foreground}
    accent = (entry('Colors:Selection', 'BackgroundNormal')
              or entry('Colors:Button', 'BackgroundNormal'))
    if accent:
        colors['accent'] = accent
    button_bg = entry('Colors:Button', 'BackgroundNormal')
    if button_bg and button_bg != background:
        colors['lighter_background'] = button_bg
    return colors, 'Qt palette', str(scheme_path)


def _detect_gtk_css():
    for path in (Path.home() / '.config/gtk-4.0/gtk.css',
                 Path.home() / '.config/gtk-3.0/gtk.css'):
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        defines = _clean_colors(dict(_GTK_DEFINE_RE.findall(text)))
        background = defines.get('theme_bg_color') or defines.get('theme_base_color')
        foreground = defines.get('theme_fg_color') or defines.get('theme_text_color')
        if not (background and foreground):
            continue
        colors = {'background': background, 'foreground': foreground}
        accent = defines.get('accent_bg_color') or defines.get('accent_color')
        if accent:
            colors['accent'] = accent
        base = defines.get('theme_base_color')
        if base and base != background:
            colors['lighter_background'] = base
        return colors, 'GTK theme', str(path)
    return None


# --------------------------------------------------------------------------- #
# Mapping onto the app palette
# --------------------------------------------------------------------------- #
def _palette_from_colors(colors):
    """Map a theme's color dict onto the app's full palette."""
    colors = _clean_colors(colors)
    background = colors.get('background', DEFAULT_PALETTE['base'])
    foreground = colors.get('foreground', DEFAULT_PALETTE['text'])
    accent = (colors.get('accent')
              or colors.get('selection_background')
              or colors.get('color5')
              or colors.get('cursor')
              or DEFAULT_PALETTE['mauve'])

    overlay0 = colors.get('dark_foreground') or blend_hex(background, foreground, 0.46)

    palette = dict(DEFAULT_PALETTE)
    palette.update({
        # Note: blend toward absolute black/white here (not darken/lighten,
        # which are relative to the live palette and would leak stale colors).
        'crust': colors.get('darker_background') or blend_hex(background, '#000000', 0.35),
        'mantle': colors.get('dark_background') or blend_hex(background, foreground, 0.05),
        'base': background,
        'surface0': (colors.get('lighter_background')
                     or colors.get('color8')
                     or blend_hex(background, foreground, 0.13)),
        'surface1': (colors.get('selection')
                     or colors.get('color8')
                     or blend_hex(background, foreground, 0.21)),
        'surface2': colors.get('muted') or blend_hex(background, foreground, 0.30),
        'overlay0': overlay0,
        'overlay1': blend_hex(overlay0, foreground, 0.28),
        'subtext0': blend_hex(background, foreground, 0.76),
        'subtext1': colors.get('light_foreground') or blend_hex(background, foreground, 0.88),
        'text': foreground,
        'mauve': accent,
    })

    accent_roles = {
        'red': ('red', 'color1'),
        'green': ('green', 'color2'),
        'yellow': ('yellow', 'color3'),
        'peach': ('orange', 'color3'),
        'blue': ('blue', 'color4'),
        'teal': ('cyan', 'color6'),
    }
    for role, keys in accent_roles.items():
        for key in keys:
            if colors.get(key):
                palette[role] = colors[key]
                break

    palette['lavender'] = blend_hex(accent, '#ffffff', 0.38)
    if colors.get('bright_foreground'):
        palette['white'] = colors['bright_foreground']
    return palette


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
#: File backing the theme that was resolved most recently (used by the live
#: theme watcher). ``None`` when the fallback palette is in effect.
_ACTIVE_THEME_FILE = None


def theme_reload_disabled():
    """True when ``OMARCHY_APPMANAGER_NO_THEME`` pins the fallback palette.

    Live reloading is pointless in that mode, so the UI skips file watching.
    """
    return bool(os.environ.get('OMARCHY_APPMANAGER_NO_THEME'))


def _theme_preset_name(colors):
    """Name of the bundled preset whose background matches, or ``''``.

    Lets a detected desktop theme be labelled with a friendly name even when
    the theme directory has no ``theme.name`` file.
    """
    background = colors.get('background') or colors.get('base')
    if not background:
        return ''
    for name, preset in THEME_PRESETS.items():
        if preset.get('base', '').lower() == str(background).lower():
            return name
    return ''


def last_theme_file():
    """Path of the file behind the last resolved theme, or ``None``."""
    return _ACTIVE_THEME_FILE


def watch_paths(path):
    """Candidate file/directory paths to watch for changes to a theme file.

    Includes the file itself and its parent directory (catches atomic
    replace/rename writes). For Omarchy ``colors.toml`` the two enclosing
    directories are added too, because switching themes swaps
    ``.../omarchy/current`` (possibly a symlink) rather than editing the
    existing file in place.
    """
    if not path:
        return []
    path = Path(path)
    candidates = [path, path.parent]
    if path.name == 'colors.toml':
        candidates.append(path.parent.parent)
        candidates.append(path.parent.parent.parent)
    return [str(candidate) for candidate in candidates]


def resolve_theme():
    """Resolve the palette that should be active, without applying it.

    Returns ``(palette, source_name, file_path_or_None)``; the palette is the
    full mapped app palette. Used both at boot (via :func:`load_theme`) and by
    the live watcher to pre-compute a palette before animating to it.
    """
    global _ACTIVE_THEME_FILE

    if theme_reload_disabled():
        _ACTIVE_THEME_FILE = None
        return dict(DEFAULT_PALETTE), FALLBACK_SOURCE, None

    override = os.environ.get('OMARCHY_APPMANAGER_THEME_FILE')
    if override:
        path = Path(override).expanduser()
        colors = (_flatten_wal(_read_json(path))
                  if path.suffix.lower() == '.json'
                  else _read_colors_toml(path))
        if colors.get('background') and colors.get('foreground'):
            _ACTIVE_THEME_FILE = str(path)
            return _palette_from_colors(colors), f'theme file ({path.name})', str(path)

    preset_name = os.environ.get('OMARCHY_APPMANAGER_THEME_PRESET')
    if preset_name:
        palette = preset_palette(preset_name)
        if palette is not None:
            _ACTIVE_THEME_FILE = None
            return palette, f'preset ({preset_name})', None

    for detector in (_detect_omarchy, _detect_pywal,
                     _detect_qt_scheme, _detect_gtk_css):
        result = detector()
        if result is not None:
            colors, source, path = result
            _ACTIVE_THEME_FILE = path
            return _palette_from_colors(colors), source, path

    _ACTIVE_THEME_FILE = None
    return dict(DEFAULT_PALETTE), FALLBACK_SOURCE, None


def detect_system_theme():
    """Return ``(palette, source_name)`` from the first available source."""
    palette, source, _path = resolve_theme()
    if source == FALLBACK_SOURCE:
        return None, None
    return palette, source


def load_theme():
    """Detect and apply the system theme; fall back to Catppuccin Mocha.

    Called at startup (see ``OmarchyAppManager._apply_theme``) and on every
    live reload; returns the palette source name for logging/diagnostics.
    """
    palette, source, _path = resolve_theme()
    apply_palette(palette, source)
    return source
