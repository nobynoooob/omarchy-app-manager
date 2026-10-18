"""
OmaApp Manager - visual design system.

Single source of truth for the Catppuccin Mocha rice palette, the unified QSS
stylesheet, and the animated-button color variants. Keeping this out of
``ui_mainwindow.py`` keeps the widget code focused on behaviour.
"""

import tempfile
from pathlib import Path
from string import Template

from PyQt6.QtGui import QColor, QPalette


# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #
# Bundled Catppuccin Mocha palette: the value of every role when no dynamic
# system theme is detected (see ``theme.py``).
DEFAULT_PALETTE = {
    'crust':      '#11111b',
    'mantle':     '#181825',
    'base':       '#1e1e2e',
    'surface0':   '#313244',
    'surface1':   '#45475a',
    'surface2':   '#585b70',
    'overlay0':   '#6c7086',
    'overlay1':   '#7f849c',
    'subtext0':   '#a6adc8',
    'subtext1':   '#bac2de',
    'text':       '#cdd6f4',
    'mauve':      '#cba6f7',
    'blue':       '#89b4fa',
    'lavender':   '#b4befe',
    'red':        '#f38ba8',
    'peach':      '#fab387',
    'yellow':     '#f9e2af',
    'green':      '#a6e3a1',
    'teal':       '#94e2d5',
    'white':      '#ffffff',
}

# The live palette. Mutated in place by :func:`apply_palette` so every module
# that imported these dict objects sees the update.
PALETTE = dict(DEFAULT_PALETTE)
PALETTE_SOURCE = 'Catppuccin Mocha'
#: Bumped on every :func:`apply_palette` call; lets the UI (and tests) detect
#: palette shifts without diffing the dict.
PALETTE_REVISION = 0

#: WCAG 2.1 AA minimum contrast ratio for normal-size text.
WCAG_AA_RATIO = 4.5

# --------------------------------------------------------------------------- #
# Bundled theme presets
# --------------------------------------------------------------------------- #
#: Full palettes for the popular rice themes.  The generic color-file mapping
#: in ``theme.py`` already handles arbitrary desktop themes; these presets act
#: as first-class fallbacks / test fixtures (selectable with
#: ``OMARCHY_APPMANAGER_THEME_PRESET``) so multi-theme rendering is verifiable
#: without editing any real system file.
THEME_PRESETS = {
    'Catppuccin Mocha': dict(DEFAULT_PALETTE),
    'Catppuccin Macchiato': {
        'crust': '#181926', 'mantle': '#1e2030', 'base': '#24273a',
        'surface0': '#363a4f', 'surface1': '#494d64', 'surface2': '#5b6078',
        'overlay0': '#6e738d', 'overlay1': '#8087a2', 'subtext0': '#a5adcb',
        'subtext1': '#b8c0e0', 'text': '#cad3f5', 'mauve': '#c6a0f6',
        'blue': '#8aadf4', 'lavender': '#b7bdf8', 'red': '#ed8796',
        'peach': '#f5a97f', 'yellow': '#eed49f', 'green': '#a6da95',
        'teal': '#8bd5ca', 'white': '#ffffff',
    },
    'Catppuccin Latte': {
        'crust': '#dce0e8', 'mantle': '#e6e9ef', 'base': '#eff1f5',
        'surface0': '#ccd0da', 'surface1': '#bcc0cc', 'surface2': '#acb0be',
        'overlay0': '#9ca0b0', 'overlay1': '#8c8fa1', 'subtext0': '#6c6f85',
        'subtext1': '#5c5f77', 'text': '#4c4f69', 'mauve': '#8839ef',
        'blue': '#1e66f5', 'lavender': '#7287fd', 'red': '#d20f39',
        'peach': '#fe640b', 'yellow': '#df8e1d', 'green': '#40a02b',
        'teal': '#179299', 'white': '#ffffff',
    },
    'Tokyo Night': {
        'crust': '#13131a', 'mantle': '#16161e', 'base': '#1a1b26',
        'surface0': '#292e42', 'surface1': '#3b4261', 'surface2': '#545c7e',
        'overlay0': '#565f89', 'overlay1': '#737aa2', 'subtext0': '#9aa5ce',
        'subtext1': '#a9b1d6', 'text': '#c0caf5', 'mauve': '#bb9af7',
        'blue': '#7aa2f7', 'lavender': '#a9b8e8', 'red': '#f7768e',
        'peach': '#ff9e64', 'yellow': '#e0af68', 'green': '#9ece6a',
        'teal': '#7dcfff', 'white': '#ffffff',
    },
    'Gruvbox': {
        'crust': '#1d2021', 'mantle': '#282828', 'base': '#32302f',
        'surface0': '#3c3836', 'surface1': '#504945', 'surface2': '#665c54',
        'overlay0': '#928374', 'overlay1': '#a89984', 'subtext0': '#bdae93',
        'subtext1': '#d5c4a1', 'text': '#ebdbb2', 'mauve': '#d3869b',
        'blue': '#83a598', 'lavender': '#d8a3b8', 'red': '#fb4934',
        'peach': '#fe8019', 'yellow': '#fabd2f', 'green': '#b8bb26',
        'teal': '#8ec07c', 'white': '#ffffff',
    },
    'Nord': {
        'crust': '#242933', 'mantle': '#2e3440', 'base': '#3b4252',
        'surface0': '#434c5e', 'surface1': '#4c566a', 'surface2': '#5e6a82',
        'overlay0': '#616e88', 'overlay1': '#7b88a1', 'subtext0': '#b6c0d0',
        'subtext1': '#d8dee9', 'text': '#eceff4', 'mauve': '#b48ead',
        'blue': '#81a1c1', 'lavender': '#88c0d0', 'red': '#bf616a',
        'peach': '#d08770', 'yellow': '#ebcb8b', 'green': '#a3be8c',
        'teal': '#8fbcbb', 'white': '#ffffff',
    },
    'Rose Pine': {
        'crust': '#14121c', 'mantle': '#191724', 'base': '#1f1d2e',
        'surface0': '#26233a', 'surface1': '#524f67', 'surface2': '#6e6a86',
        'overlay0': '#6e6a86', 'overlay1': '#908caa', 'subtext0': '#a8a4c0',
        'subtext1': '#c8c4de', 'text': '#e0def4', 'mauve': '#c4a7e7',
        'blue': '#9ccfd8', 'lavender': '#ebbcba', 'red': '#eb6f92',
        'peach': '#f6c177', 'yellow': '#f6c177', 'green': '#9ccfd8',
        'teal': '#9ccfd8', 'white': '#ffffff',
    },
    'Dracula': {
        'crust': '#191a21', 'mantle': '#21222c', 'base': '#282a36',
        'surface0': '#343746', 'surface1': '#44475a', 'surface2': '#6272a4',
        'overlay0': '#6272a4', 'overlay1': '#828bb8', 'subtext0': '#a6aed6',
        'subtext1': '#c8d0e8', 'text': '#f8f8f2', 'mauve': '#bd93f9',
        'blue': '#8be9fd', 'lavender': '#d0a9ff', 'red': '#ff5555',
        'peach': '#ffb86c', 'yellow': '#f1fa8c', 'green': '#50fa7b',
        'teal': '#8be9fd', 'white': '#ffffff',
    },
}


def preset_palette(name):
    """Look up a bundled preset (case-insensitive); ``None`` when unknown."""
    wanted = (name or '').strip().lower()
    for preset_name, palette in THEME_PRESETS.items():
        if preset_name.lower() == wanted:
            return dict(palette)
    return None


def blend_hex(color_a, color_b, t):
    """Linear blend between two ``#rrggbb`` colors, ``t`` in [0, 1]."""
    t = max(0.0, min(1.0, float(t)))
    ca, cb = QColor(color_a), QColor(color_b)
    return QColor(
        round(ca.red()   + (cb.red()   - ca.red())   * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue()  + (cb.blue()  - ca.blue())  * t),
    ).name()


# --------------------------------------------------------------------------- #
# WCAG contrast
# --------------------------------------------------------------------------- #
def relative_luminance(color):
    """WCAG 2.1 relative luminance of a color (0.0 dark .. 1.0 light)."""
    def channel(value):
        value /= 255.0
        if value <= 0.03928:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    qcolor = QColor(color)
    return (0.2126 * channel(qcolor.red())
            + 0.7152 * channel(qcolor.green())
            + 0.0722 * channel(qcolor.blue()))


def contrast_ratio(color_a, color_b):
    """WCAG contrast ratio between two colors (1.0 .. 21.0)."""
    luminance_a = relative_luminance(color_a)
    luminance_b = relative_luminance(color_b)
    lighter, darker = max(luminance_a, luminance_b), min(luminance_a, luminance_b)
    return (lighter + 0.05) / (darker + 0.05)


def ensure_contrast(foreground, background, min_ratio=WCAG_AA_RATIO):
    """Blend ``foreground`` toward black/white until it meets ``min_ratio``.

    Both poles are searched and the result needing the smallest perceptual
    change wins, so mid-luminance backgrounds (where a single pole can never
    reach the ratio) are handled correctly.  Returns a ``#rrggbb`` string; the
    input color is returned unchanged when it already passes.
    """
    foreground = QColor(foreground).name()
    if contrast_ratio(foreground, background) >= min_ratio:
        return foreground

    best = None
    for target in ('#ffffff', '#000000'):
        for step in range(1, 21):
            candidate = blend_hex(foreground, target, step / 20.0)
            if contrast_ratio(candidate, background) >= min_ratio:
                if best is None or step < best[0]:
                    best = (step, candidate)
                break
    if best is not None:
        return best[1]
    # Mathematically unreachable (black/white always bracket the ratio), but
    # stay defensive: fall back to whichever extreme contrasts better.
    return max(('#ffffff', '#000000'),
               key=lambda color: contrast_ratio(color, background))


def ensure_readable(foreground, backgrounds, min_ratio=WCAG_AA_RATIO):
    """Run :func:`ensure_contrast` against every background in turn."""
    result = QColor(foreground).name()
    for background in backgrounds:
        result = ensure_contrast(result, background, min_ratio)
    return result


def readable_blend(foreground, backgrounds, min_ratio=WCAG_AA_RATIO):
    """Blend ``foreground`` once so it is readable on *every* background.

    Unlike chaining :func:`ensure_contrast`, the returned colour satisfies all
    backgrounds simultaneously.  Returns ``None`` when no blend can (both
    black and white light in the unattainable band between the backgrounds).
    """
    foreground = QColor(foreground).name()
    if all(contrast_ratio(foreground, bg) >= min_ratio for bg in backgrounds):
        return foreground

    best = None
    for target in ('#ffffff', '#000000'):
        for step in range(1, 21):
            candidate = blend_hex(foreground, target, step / 20.0)
            if all(contrast_ratio(candidate, bg) >= min_ratio for bg in backgrounds):
                if best is None or step < best[0]:
                    best = (step, candidate)
                break
    return best[1] if best else None


def repair_surface(surface, text, min_ratio=WCAG_AA_RATIO):
    """Shade ``surface`` away from ``text`` until the pair meets ``min_ratio``.

    Used as the last resort for mid-luminance accents where no single label
    colour can stay legible on every interaction state.
    """
    if contrast_ratio(text, surface) >= min_ratio:
        return surface
    target = '#000000' if relative_luminance(text) > 0.5 else '#ffffff'
    candidate = surface
    for step in range(1, 21):
        candidate = blend_hex(surface, target, step / 20.0)
        if contrast_ratio(text, candidate) >= min_ratio:
            return candidate
    return blend_hex(surface, target, 1.0)


def readable_text(background, first, second, min_ratio=WCAG_AA_RATIO):
    """Pick whichever candidate color contrasts best against ``background``."""
    return max((first, second), key=lambda c: contrast_ratio(c, background))


def contrast_tint(color):
    """Black or white, whichever reads better on top of ``color``.

    Used for ripples and translucent overlays whose host color is only known
    at paint time (buttons of every variant, in every theme).
    """
    return '#ffffff' if relative_luminance(color) < 0.5 else '#000000'


def lighten(color, t):
    return blend_hex(color, PALETTE['white'], t)


def darken(color, t):
    return blend_hex(color, PALETTE['crust'], t)


def is_light_theme():
    """True when the active palette's chrome is light (e.g. Catppuccin Latte)."""
    return relative_luminance(PALETTE['crust']) > 0.5


def surface_hover(color, t=0.14):
    """Hover shade: lighter on dark themes, darker on light themes."""
    target = '#000000' if is_light_theme() else '#ffffff'
    return blend_hex(color, target, t)


def surface_press(color, t=0.22):
    """Press shade: always a deeper version of the surface."""
    return blend_hex(color, '#000000', t)


# --------------------------------------------------------------------------- #
# Derived structures (rebuilt whenever the palette changes)
# --------------------------------------------------------------------------- #
def _build_card_colors():
    return {
        # Glassmorphic card surface: the glass alpha composites deterministically
        # over the window background (crust) in AppCard.paintEvent.
        'bg': PALETTE['mantle'],
        'bg_alpha': 0.84,
        'hover_bg': blend_hex(PALETTE['base'], PALETTE['surface0'], 0.50),
        'hover_bg_alpha': 0.96,
        'border': PALETTE['surface0'],
        'hover_border': PALETTE['mauve'],
        # Soft outer ring painted under the card while hovering (alpha is
        # scaled by the hover progress in AppCard.paintEvent).
        'hover_glow': PALETTE['lavender'],
        # Colour of the elevated hover drop shadow.
        'hover_shadow': PALETTE['lavender'],
    }


def _category_tint(accent):
    """Badge tint with WCAG-ensured label contrast (dark and light themes)."""
    bg = blend_hex(PALETTE['base'], accent, 0.16)
    return {
        'text': ensure_contrast(accent, bg),
        'bg': bg,
        'border': blend_hex(PALETTE['base'], accent, 0.45),
    }


def _build_category_colors():
    return {
        'Game': _category_tint(PALETTE['green']),
        'AudioVideo': _category_tint(PALETTE['mauve']),
        'Utility': _category_tint(PALETTE['blue']),
        'Development': _category_tint(PALETTE['peach']),
    }


def _build_button_variants():
    variants = {
        'primary': {
            'bg': PALETTE['mauve'],
            'hover': surface_hover(PALETTE['mauve'], 0.14),
            'press': surface_press(PALETTE['mauve'], 0.18),
            # The label must read on the accent surface itself; readable_text
            # picks crust or white depending on the theme's luminance.
            'text': readable_text(PALETTE['mauve'], PALETTE['crust'], PALETTE['white']),
            'border': surface_hover(PALETTE['mauve'], 0.14),
            'hover_border': surface_hover(PALETTE['mauve'], 0.28),
        },
        'ghost': {
            'bg': PALETTE['base'],
            'hover': PALETTE['surface0'],
            'press': PALETTE['surface1'],
            'text': PALETTE['subtext1'],
            'border': PALETTE['surface0'],
            'hover_border': PALETTE['surface1'],
        },
        'danger': {
            'bg': PALETTE['base'],
            'hover': blend_hex(PALETTE['base'], PALETTE['red'], 0.16),
            'press': blend_hex(PALETTE['base'], PALETTE['red'], 0.28),
            'text': PALETTE['red'],
            'border': blend_hex(PALETTE['base'], PALETTE['red'], 0.35),
            'hover_border': blend_hex(PALETTE['base'], PALETTE['red'], 0.60),
        },
        'segment': {
            'bg': PALETTE['surface0'],
            'hover': PALETTE['surface1'],
            'press': PALETTE['surface2'],
            'text': PALETTE['subtext1'],
            'border': PALETTE['surface0'],
            'hover_border': PALETTE['surface1'],
        },
    }
    # Overlay-button labels must stay legible on every resting/hover/press
    # surface of the variant, in both dark and light themes.
    for variant in variants.values():
        surfaces = (variant['bg'], variant['hover'], variant['press'])
        text = readable_blend(variant['text'], surfaces)
        if text is not None:
            variant['text'] = text
        else:
            # Mid-luminance accent: no single label colour serves every
            # state, so shade the surfaces until the intended label passes.
            for key in ('bg', 'hover', 'press'):
                variant[key] = repair_surface(variant[key], variant['text'])
    return variants


CARD_COLORS = _build_card_colors()
CATEGORY_COLORS = _build_category_colors()
BUTTON_VARIANTS = _build_button_variants()

#: Text-role palette with WCAG-ensured contrast against the surfaces those
#: roles are painted on.  Kept separate from ``PALETTE`` so the raw resolved
#: theme palette is never mutated (the live-reload comparison depends on it).
READABLE_PALETTE = dict(PALETTE)


def _build_readable_palette():
    readable = dict(PALETTE)
    readable['overlay1'] = ensure_readable(
        PALETTE['overlay1'], (PALETTE['mantle'], PALETTE['crust']))
    readable['overlay0'] = ensure_readable(
        PALETTE['overlay0'], (PALETTE['crust'], PALETTE['surface0']))
    readable['subtext0'] = ensure_readable(
        PALETTE['subtext0'], (PALETTE['crust'], PALETTE['surface0']))
    readable['subtext1'] = ensure_readable(
        PALETTE['subtext1'],
        (PALETTE['crust'], PALETTE['mantle'], PALETTE['base'], PALETTE['surface0']))
    return readable


READABLE_PALETTE.clear()
READABLE_PALETTE.update(_build_readable_palette())


def apply_palette(palette, source='Custom'):
    """Replace the live palette and rebuild every derived structure.

    The module-level dicts are cleared/updated in place so widgets and modules
    that already hold references (e.g. ``ui_mainwindow``) pick the change up.
    """
    global PALETTE_SOURCE, PALETTE_REVISION
    for key, value in palette.items():
        if key in DEFAULT_PALETTE:
            PALETTE[key] = value
    PALETTE_SOURCE = source
    PALETTE_REVISION += 1
    CARD_COLORS.clear()
    CARD_COLORS.update(_build_card_colors())
    CATEGORY_COLORS.clear()
    CATEGORY_COLORS.update(_build_category_colors())
    BUTTON_VARIANTS.clear()
    BUTTON_VARIANTS.update(_build_button_variants())
    READABLE_PALETTE.clear()
    READABLE_PALETTE.update(_build_readable_palette())


# --------------------------------------------------------------------------- #
# Global stylesheet
# --------------------------------------------------------------------------- #
APP_QSS_TEMPLATE = Template("""
* {
    font-family: 'Inter', 'Noto Sans', 'Ubuntu', 'Segoe UI', 'Cantarell', sans-serif;
    font-size: 13px;
}

QMainWindow, QDialog, QMessageBox {
    background-color: $crust;
}

QWidget#centralWidget, QWidget#appsContainer {
    background-color: $crust;
}

QLabel {
    color: $text;
    background: transparent;
}

QLabel#appName {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}

QLabel#appPath {
    font-size: 11px;
    color: $overlay1;
}

QLabel#counterTag {
    background-color: $surface0;
    color: $subtext1;
    border: 1px solid $surface1;
    border-radius: 14px;
    padding: 7px 14px;
    font-size: 11px;
    font-weight: 600;
}

QWidget#segmented {
    background-color: $surface0;
    border-radius: 14px;
}

QLabel#emptyState {
    color: $overlay0;
    font-size: 13px;
}

QLabel#emptyTitle {
    color: $subtext1;
    font-size: 16px;
    font-weight: 600;
}

QLabel#dropHint {
    color: $overlay0;
    font-size: 11px;
}

QLabel#fieldLabel {
    color: $subtext1;
    font-size: 12px;
    font-weight: 500;
}

QLabel#iconPreview {
    background-color: $surface0;
    border: 1px solid $surface1;
    border-radius: 10px;
}

QLineEdit {
    background-color: $surface0;
    border: 1px solid $surface0;
    border-radius: 10px;
    padding: 8px 12px;
    color: $text;
    selection-background-color: $mauve;
    selection-color: $crust;
}

QLineEdit:hover {
    border-color: $surface1;
}

QLineEdit:focus {
    border-color: $mauve;
}

/* Extra left padding leaves room for the integrated search icon. */
QLineEdit#searchBar {
    padding: 10px 16px 10px 40px;
}

/* Drag & drop affordance: dashed accent frame + faint accent wash. The
   padding is reduced by the extra border width so the field does not jump. */
QLineEdit[dragActive="true"] {
    border: 2px dashed $mauve;
    padding: 7px 11px;
    background-color: $mauveOverlay;
}

QComboBox {
    background-color: $surface0;
    border: 1px solid $surface0;
    border-radius: 10px;
    padding: 8px 30px 8px 12px;
    color: $text;
}

QComboBox:hover {
    border-color: $surface1;
}

QComboBox:focus, QComboBox:on {
    border-color: $mauve;
}

QComboBox::drop-down {
    border: none;
    background: transparent;
    width: 26px;
}

QComboBox::down-arrow {
    image: url("$comboArrow");
    width: 12px;
    height: 12px;
}

QComboBox QAbstractItemView {
    background-color: $mantle;
    color: $text;
    border: 1px solid $surface1;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: $mauve;
    selection-color: $crust;
    outline: none;
}

QPushButton {
    background-color: $surface0;
    color: $text;
    border: 1px solid $surface1;
    border-radius: 8px;
    padding: 6px 14px;
}

QPushButton:hover {
    background-color: $surface1;
}

QPushButton:pressed {
    background-color: $surface2;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}

QScrollBar::handle:vertical {
    background: $surface1;
    min-height: 32px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: $surface2;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
    background: none;
    border: none;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QToolTip {
    background-color: $surface0;
    color: $text;
    border: 1px solid $surface1;
    border-radius: 6px;
    padding: 4px 8px;
}
""")


def _combo_arrow_path():
    """Render (once) a themed chevron for QComboBox and return its path.

    QSS cannot draw arrows, so a tiny PNG is generated next to the usual temp
    files and referenced by :func:`build_app_qss`.
    """
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QPainter, QPen, QPixmap, QPolygonF

    target_dir = Path(tempfile.gettempdir()) / 'omarchy-app-manager'
    target_dir.mkdir(parents=True, exist_ok=True)
    # Keyed by color so switching themes regenerates the arrow.
    arrow_color = READABLE_PALETTE['overlay1']
    arrow = target_dir / f"combo-arrow-{arrow_color.lstrip('#')}.png"
    if arrow.exists():
        return arrow

    canvas = QPixmap(24, 24)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(arrow_color), 2.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline(QPolygonF([
        QPointF(7.0, 10.0), QPointF(12.0, 15.0), QPointF(17.0, 10.0),
    ]))
    painter.end()
    canvas.save(str(arrow))
    return arrow


def _rgba(color, alpha):
    """QSS ``rgba(r, g, b, a)`` string (Qt wants an int 0-255 alpha)."""
    tint = QColor(color)
    tint.setAlphaF(alpha)
    return f"rgba({tint.red()}, {tint.green()}, {tint.blue()}, {tint.alpha()})"


def build_app_qss():
    """The full application stylesheet (requires a live QApplication)."""
    return APP_QSS_TEMPLATE.substitute({
        **READABLE_PALETTE,
        'comboArrow': _combo_arrow_path().as_posix(),
        'mauveOverlay': _rgba(READABLE_PALETTE['mauve'], 0.05),
    })


def dark_palette():
    """Dark QPalette so unstyled/native widgets (message boxes, menus) blend in."""
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(READABLE_PALETTE['crust']))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(READABLE_PALETTE['text']))
    pal.setColor(QPalette.ColorRole.Base, QColor(READABLE_PALETTE['mantle']))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(READABLE_PALETTE['base']))
    pal.setColor(QPalette.ColorRole.Text, QColor(READABLE_PALETTE['text']))
    pal.setColor(QPalette.ColorRole.Button, QColor(READABLE_PALETTE['surface0']))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(READABLE_PALETTE['text']))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(READABLE_PALETTE['surface0']))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(READABLE_PALETTE['text']))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(READABLE_PALETTE['mauve']))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(READABLE_PALETTE['crust']))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(ensure_contrast(
        READABLE_PALETTE['overlay0'], READABLE_PALETTE['surface0'], 3.0)))
    return pal
