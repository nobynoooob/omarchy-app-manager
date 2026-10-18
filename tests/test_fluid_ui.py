"""
Fluid UI tests: dynamic multi-theme WCAG engine, animated elevation,
ripple/pulse feedback, the sliding pill indicator, the breathing empty state
and animation teardown on close.

Run with:  python -m pytest tests/test_fluid_ui.py -v
"""

import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PyQt6.QtCore import QAbstractAnimation, QPointF  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402

from omarchy_app_manager import desktop_manager as dm  # noqa: E402
from omarchy_app_manager import styles  # noqa: E402
from omarchy_app_manager import ui_mainwindow as ui  # noqa: E402
from omarchy_app_manager.styles import (  # noqa: E402
    CARD_COLORS, READABLE_PALETTE, THEME_PRESETS, WCAG_AA_RATIO,
    contrast_ratio, ensure_contrast, preset_palette, readable_blend,
    relative_luminance, repair_surface, surface_hover, surface_press,
)
from omarchy_app_manager.ui_mainwindow import (  # noqa: E402
    AppCard, CategoryPills, EmptyState, OmarchyAppManager, ToggleSwitch,
)

REQUIRED_PALETTE_KEYS = (
    'base', 'mantle', 'crust', 'surface0', 'surface1', 'surface2',
    'text', 'subtext0', 'subtext1', 'overlay0', 'overlay1', 'white',
    'red', 'green', 'blue', 'mauve', 'peach', 'lavender',
)


def pump(qapp, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)


def pump_until(qapp, condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return condition()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    monkeypatch.setenv("OMARCHY_APPS_DIR", str(apps_dir))
    return apps_dir


# --------------------------------------------------------------------------- #
# WCAG engine
# --------------------------------------------------------------------------- #
def test_contrast_ratio_reference_values():
    assert contrast_ratio('#ffffff', '#000000') == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio('#123456', '#123456') == pytest.approx(1.0)
    assert contrast_ratio('#ffffff', '#000000') == contrast_ratio('#000000', '#ffffff')


def test_ensure_contrast_uses_a_reachable_pole(qapp):
    # White on pure red tops out at 4.0 (< AA), so the result must not be
    # white: the search has to fall back to the dark pole that actually fits.
    result = ensure_contrast('#ffffff', '#ff0000')
    assert contrast_ratio(result, '#ff0000') >= WCAG_AA_RATIO
    assert QColor(result).name() != '#ffffff'

    # Mid-luminance light backgrounds (Catppuccin Latte press) previously
    # returned an unreachable white; both poles are searched now.
    result = ensure_contrast('#5c5f77', '#ccd0da')
    assert contrast_ratio(result, '#ccd0da') >= WCAG_AA_RATIO


def test_readable_blend_satisfies_every_state_at_once(qapp):
    states = ('#3a2119', '#4a2a1f', '#301b14')
    label = readable_blend('#f25623', states)
    assert label is not None
    for state in states:
        assert contrast_ratio(label, state) >= WCAG_AA_RATIO


def test_readable_blend_reports_impossibility(qapp):
    # #ff0000 and #c70000 bracket the contrast band: neither black nor white
    # (nor any blend) can be AA on both, so the caller must repair surfaces.
    assert readable_blend('#000000', ('#ff0000', '#c70000')) is None


def test_repair_surface_reaches_aa(qapp):
    repaired = repair_surface('#c70000', '#0a0a0a')
    assert contrast_ratio('#0a0a0a', repaired) >= WCAG_AA_RATIO


# --------------------------------------------------------------------------- #
# Theme presets + cross-preset WCAG
# --------------------------------------------------------------------------- #
def test_theme_presets_are_complete_and_valid():
    assert set(THEME_PRESETS) == {
        'Catppuccin Mocha', 'Catppuccin Macchiato', 'Catppuccin Latte',
        'Tokyo Night', 'Gruvbox', 'Nord', 'Rose Pine', 'Dracula',
    }
    for name, palette in THEME_PRESETS.items():
        for key in REQUIRED_PALETTE_KEYS:
            assert key in palette, f'{name} misses {key}'
            assert QColor(palette[key]).isValid(), f'{name}.{key} not a colour'

    copy = preset_palette('Catppuccin Mocha')
    copy['mauve'] = '#000000'
    assert THEME_PRESETS['Catppuccin Mocha']['mauve'] != '#000000'


def test_every_preset_is_wcag_aa_for_badges_and_buttons(qapp):
    """Badge labels and every button state carry AA contrast in all presets."""
    for name, palette in THEME_PRESETS.items():
        styles.apply_palette(palette, f'test ({name})')

        for category, tint in styles.CATEGORY_COLORS.items():
            ratio = contrast_ratio(tint['text'], tint['bg'])
            assert ratio >= WCAG_AA_RATIO, f'{name}/{category} {ratio:.2f}'

        for variant, spec in styles.BUTTON_VARIANTS.items():
            for state in ('bg', 'hover', 'press'):
                ratio = contrast_ratio(spec['text'], spec[state])
                assert ratio >= WCAG_AA_RATIO, f'{name}/{variant}/{state} {ratio:.2f}'

        for role, backgrounds in (
            ('subtext1', ('crust', 'mantle', 'base', 'surface0')),
            ('subtext0', ('crust', 'surface0')),
            ('overlay1', ('mantle', 'crust')),
            ('overlay0', ('crust', 'surface0')),
        ):
            for surface in backgrounds:
                ratio = contrast_ratio(
                    READABLE_PALETTE[role], READABLE_PALETTE[surface])
                assert ratio >= WCAG_AA_RATIO, f'{name}/{role}/{surface} {ratio:.2f}'


def test_hover_shading_follows_theme_direction(qapp):
    styles.apply_palette(preset_palette('Catppuccin Mocha'), 'mocha')
    dark_hover = surface_hover(styles.PALETTE['mauve'], 0.14)
    assert (relative_luminance(dark_hover)
            > relative_luminance(styles.PALETTE['mauve']))
    dark_press = surface_press(styles.PALETTE['mauve'], 0.18)
    assert (relative_luminance(dark_press)
            < relative_luminance(styles.PALETTE['mauve']))

    styles.apply_palette(preset_palette('Catppuccin Latte'), 'latte')
    light_hover = surface_hover(styles.PALETTE['mauve'], 0.14)
    assert (relative_luminance(light_hover)
            < relative_luminance(styles.PALETTE['mauve']))


def test_theme_switch_is_leak_free_and_geometry_stable(qapp, sandbox):
    dm.create_desktop_file({'name': 'Alpha', 'path': '/bin/true', 'category': 'Utility'})
    dm.create_desktop_file({'name': 'Beta', 'path': '/bin/true', 'category': 'Game'})
    window = OmarchyAppManager()
    window.load_apps()
    assert len(window._cards) == 2

    widgets_before = len(window.findChildren(object))
    geometries = [card.geometry() for card in window._cards]

    for name in ('Tokyo Night', 'Gruvbox', 'Catppuccin Latte'):
        window._apply_palette_and_styles(preset_palette(name), name)
        assert styles.PALETTE_SOURCE == name
        assert len(window.findChildren(object)) == widgets_before
        assert [card.geometry() for card in window._cards] == geometries
        assert window.centralWidget().graphicsEffect() is None
        for card in window._cards:
            assert card.graphicsEffect() is None


# --------------------------------------------------------------------------- #
# Card elevation + appear settle
# --------------------------------------------------------------------------- #
def test_card_appear_settle_animates(qapp, monkeypatch):
    monkeypatch.setattr(ui, 'CARD_APPEAR_MS', 60)
    card = AppCard({'name': 'Alpha', 'path': '/bin/true', 'category': 'Utility'})
    try:
        card.resize(360, ui.CARD_HEIGHT)
        card.start_appear_settle()
        assert card._appear_anim.state() == ui._ANIM_RUNNING
        assert card._appear_progress < 1.0
        card.grab()  # mid-settle paint must not crash
        assert pump_until(qapp, lambda: card._appear_progress >= 1.0)
    finally:
        card.stop_animations()
        card.deleteLater()


def test_card_appear_settle_is_instant_when_zeroed(qapp):
    card = AppCard({'name': 'Alpha', 'path': '/bin/true', 'category': 'Utility'})
    try:
        card.start_appear_settle()
        assert card._appear_progress == 1.0
        assert card._appear_anim.state() == QAbstractAnimation.State.Stopped
    finally:
        card.deleteLater()


def test_hover_shadow_elevates_and_drops(qapp, monkeypatch):
    monkeypatch.setattr(ui, 'SHADOW_ANIM_MS', 50)
    card = AppCard({'name': 'Alpha', 'path': '/bin/true', 'category': 'Utility'})
    try:
        card.resize(360, ui.CARD_HEIGHT)
        card._animate_shadow(1.0)
        assert card._shadow_effect is not None
        assert card.graphicsEffect() is card._shadow_effect
        assert pump_until(qapp, lambda: card._shadow_effect.blurRadius() >= 25.9)

        card._animate_shadow(0.0)
        assert pump_until(qapp, lambda: card.graphicsEffect() is None)
        assert card._shadow_effect is None
    finally:
        card.stop_animations()
        card.deleteLater()


def test_hover_shadow_yields_the_effect_slot_to_filter_fades(qapp):
    card = AppCard({'name': 'Alpha', 'path': '/bin/true', 'category': 'Utility'})
    try:
        card.resize(360, ui.CARD_HEIGHT)
        card._animate_shadow(1.0)  # instant: durations are zeroed
        assert card._shadow_effect is not None

        card._ensure_opacity_effect()
        assert card._shadow_effect is None

        card._clear_opacity_effect()
        assert card._shadow_effect is not None
        assert card.graphicsEffect() is card._shadow_effect
    finally:
        card.stop_animations()
        card.deleteLater()


# --------------------------------------------------------------------------- #
# Ripple + pulse
# --------------------------------------------------------------------------- #
def test_ripple_animates_and_paints(qapp, monkeypatch):
    monkeypatch.setattr(ui, 'RIPPLE_MS', 80)
    button = ui.AnimatedButton('Ripple', 'primary')
    try:
        button.resize(button.sizeHint())
        button._ripple_origin = QPointF(10.0, 12.0)
        button._animate_ripple()
        assert button._ripple_anim.state() == ui._ANIM_RUNNING
        assert 0.0 <= button._ripple_progress < 1.0
        button.grab()  # mid-ripple paint must not crash
        assert pump_until(qapp, lambda: button._ripple_progress >= 1.0)
    finally:
        button.stop_animations()
        button.deleteLater()


def test_ripple_is_skipped_in_instant_mode(qapp):
    button = ui.AnimatedButton('Ripple', 'primary')
    try:
        button._animate_ripple()
        assert button._ripple_progress == 1.0
        assert button._ripple_anim.state() == QAbstractAnimation.State.Stopped
    finally:
        button.deleteLater()


def test_toggle_pulse_on_flip(qapp, monkeypatch):
    monkeypatch.setattr(ui, 'PULSE_MS', 60)
    toggle = ToggleSwitch()
    try:
        toggle.setChecked(True)
        assert toggle._pulse_anim.state() == ui._ANIM_RUNNING
        assert pump_until(qapp, lambda: toggle._pulse >= 1.0)
        toggle.grab()
    finally:
        toggle.stop_animations()
        toggle.deleteLater()

    monkeypatch.setattr(ui, 'PULSE_MS', 0)
    instant = ToggleSwitch()
    try:
        instant.setChecked(True)
        assert instant._pulse == 1.0
        assert instant._pulse_anim.state() == QAbstractAnimation.State.Stopped
    finally:
        instant.deleteLater()


# --------------------------------------------------------------------------- #
# Category pill indicator
# --------------------------------------------------------------------------- #
def test_pill_indicator_slides_to_the_active_pill(qapp, monkeypatch):
    from PyQt6.QtWidgets import QHBoxLayout, QWidget

    host = QWidget()
    pills = CategoryPills(['All', 'Games', 'Utilities', 'System'])
    layout = QHBoxLayout(host)
    layout.addWidget(pills)
    host.resize(700, 50)
    host.show()
    qapp.processEvents()
    try:
        pills._settle_indicator()
        assert pills._indicator_to == pills._pill_rect('All')

        monkeypatch.setattr(ui, 'PILL_SLIDE_MS', 60)
        pills.set_current('Games')
        assert pills._slide_anim.state() == ui._ANIM_RUNNING
        assert pills._indicator_progress < 1.0
        host.grab()  # mid-slide paint must not crash

        assert pump_until(qapp, lambda: pills._indicator_progress >= 1.0)
        assert pills._indicator_to == pills._pill_rect('Games')
        assert (pills._indicator_to.left()
                == pills._buttons['Games'].geometry().left())
    finally:
        pills.stop_animations()
        host.close()
        host.deleteLater()


def test_pill_indicator_snaps_in_instant_mode(qapp):
    from PyQt6.QtWidgets import QHBoxLayout, QWidget

    host = QWidget()
    pills = CategoryPills(['All', 'Games'])
    layout = QHBoxLayout(host)
    layout.addWidget(pills)
    host.resize(400, 50)
    host.show()
    qapp.processEvents()
    try:
        pills._settle_indicator()
        pills.set_current('Games')
        assert pills._indicator_progress == 1.0
        assert pills._indicator_to == pills._pill_rect('Games')
    finally:
        host.close()
        host.deleteLater()


# --------------------------------------------------------------------------- #
# Empty state breathing
# --------------------------------------------------------------------------- #
def test_empty_state_breathes_only_while_visible(qapp, monkeypatch):
    monkeypatch.setattr(ui, 'BREATH_MS', 60)
    state = EmptyState()
    state.resize(420, 300)
    try:
        state.show()
        assert state._breath_anim.state() == ui._ANIM_RUNNING
        assert pump_until(qapp, lambda: state._breath > 0.2)
        state.grab()

        state.hide()
        assert state._breath == 0.0
        assert state._breath_anim.state() == QAbstractAnimation.State.Stopped

        state.show()
        assert state._breath_anim.state() == ui._ANIM_RUNNING
    finally:
        state.stop_animations()
        state.deleteLater()


def test_empty_state_stays_still_in_instant_mode(qapp):
    state = EmptyState()
    state.resize(420, 300)
    try:
        state.show()
        assert state._breath_anim.state() == QAbstractAnimation.State.Stopped
        assert state._breath == 0.0
    finally:
        state.deleteLater()


# --------------------------------------------------------------------------- #
# Teardown + HiDPI seams
# --------------------------------------------------------------------------- #
def test_close_stops_every_animation(qapp, sandbox, monkeypatch):
    monkeypatch.setattr(ui, 'CARD_HOVER_MS', 100)
    monkeypatch.setattr(ui, 'PULSE_MS', 100)
    dm.create_desktop_file({'name': 'Alpha', 'path': '/bin/true', 'category': 'Utility'})
    window = OmarchyAppManager()
    window.load_apps()
    card = window._cards[0]
    card._animate_hover(1.0)
    assert card._hover_anim.state() == ui._ANIM_RUNNING

    window.close()

    assert card._hover_anim.state() == QAbstractAnimation.State.Stopped
    assert window._theme_effect is None
    assert window.empty_state._breath_anim.state() == QAbstractAnimation.State.Stopped
    running = [
        anim for anim in window.findChildren(QAbstractAnimation)
        if anim.state() == ui._ANIM_RUNNING
    ]
    assert running == []


def test_hidpi_assets_use_the_dpr_seam(qapp, monkeypatch):
    monkeypatch.setattr(ui, '_dpr', lambda: 2.0)

    badge = ui._perf_badge_pixmap('gamemode', ui.PERF_BADGE_SIZE)
    assert badge.width() == ui.PERF_BADGE_SIZE * 2
    assert badge.devicePixelRatio() == 2.0

    empty_icon = ui._empty_state_pixmap(32)
    assert empty_icon.width() == 64
    assert empty_icon.devicePixelRatio() == 2.0


def test_glass_alpha_contract():
    assert 0.0 < CARD_COLORS['bg_alpha'] < 1.0
    assert CARD_COLORS['bg_alpha'] <= CARD_COLORS['hover_bg_alpha'] <= 1.0
