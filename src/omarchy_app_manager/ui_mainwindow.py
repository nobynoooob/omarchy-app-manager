"""
Omarchy App Manager - main window and widgets.

Rice-grade visual layer: Catppuccin Mocha palette, unified QSS (see
``styles.py``), animated card hovers with a lavender glow, hover-only quick
actions (launch / edit / open directory / delete), a centered search bar,
category pill filters, a responsive grid, a dashed drop-target empty state
and a smart "Custom Apps" / "All System Apps" view toggle.
"""

import json
import math
import os
import re
import shlex
import shutil
import threading
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QEvent, QAbstractAnimation, QEasingCurve, QFileSystemWatcher, QObject,
    QPointF, QProcess, QPropertyAnimation, QRunnable, QRectF,
    QSequentialAnimationGroup, QSize, QThreadPool, QTimer, QUrl, pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QPainter,
    QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QDialog, QFileDialog,
    QFormLayout, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .appimage_icons import (
    cached_appimage_icon_path, extract_appimage_icon, is_appimage,
)
from .desktop_manager import (
    GAMEMODE_WRAPPER, command_is_available, compose_exec_line,
    create_desktop_file, delete_desktop_file, ensure_appimage_executable,
    first_exec_token, get_installed_apps, is_system_entry, split_exec,
    update_desktop_file,
)
from . import integration
from . import styles
from .styles import (
    BUTTON_VARIANTS, CARD_COLORS, CATEGORY_COLORS, PALETTE,
    blend_hex, build_app_qss, contrast_tint, dark_palette,
)
from .theme import (
    last_theme_file, load_theme, resolve_theme, theme_reload_disabled,
    watch_paths,
)

CATEGORIES = ['Game', 'AudioVideo', 'Utility', 'Development']

# Category filter pills above the grid.  "System" matches system entries
# (NoDisplay/Wine/Python shims) via ``is_system_entry``; the rest map onto the
# friendly category names produced by ``parse_category``.
CATEGORY_PILLS = ['All', 'Development', 'Games', 'Utilities', 'System']
PILL_CATEGORY_MAP = {
    'Development': 'Development',
    'Games': 'Game',
    'Utilities': 'Utility',
}

# Animation timing (module-level so tests can zero them out for determinism).
CARD_HOVER_MS = 150
FILTER_FADE_IN_MS = 180
FILTER_FADE_OUT_MS = 140
DIALOG_FADE_MS = 200
TOGGLE_ANIM_MS = 140
CARD_APPEAR_MS = 200
SHADOW_ANIM_MS = 160
RIPPLE_MS = 320
PULSE_MS = 260
PILL_SLIDE_MS = 180
BREATH_MS = 2200
# Live theme reloading: writes to a theme file often arrive in chunks, so
# reloads are debounced; a detected palette shift cross-fades the window.
THEME_DEBOUNCE_MS = 100
THEME_FADE_MS = 300

ICON_SIZE = 48
ICON_RADIUS = 10.0
ICON_PREVIEW_SIZE = 40
PERF_BADGE_SIZE = 14
CARD_RADIUS = 14.0
CARD_HEIGHT = 96
# Hover elevation: soft drop shadow under the card (paint-only, never layout).
SHADOW_MAX_BLUR = 26.0
SHADOW_OFFSET_Y = 3.0
SHADOW_ALPHA = 0.55
CARD_APPEAR_INSET = 3.0
CARD_MIN_WIDTH = 320
MAX_GRID_COLUMNS = 4
EMPTY_ICON_SIZE = 64

FONT_FAMILIES = ['Inter', 'Noto Sans', 'Ubuntu', 'Segoe UI', 'Cantarell', 'sans-serif']

# Cache enum members used inside C++-driven callbacks (paint/resize); looking
# them up reentrantly triggers a Python 3.14 enum metaclass recursion bug
# (RecursionError in enum.__subclasscheck__).
_TRANSPARENT = Qt.GlobalColor.transparent
_NO_BRUSH = Qt.BrushStyle.NoBrush
_NO_PEN = Qt.PenStyle.NoPen
_ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
_ALIGN_VCENTER = Qt.AlignmentFlag.AlignVCenter
_RESIZE_EVENT = QEvent.Type.Resize
_ROUND_CAP = Qt.PenCapStyle.RoundCap
_ROUND_JOIN = Qt.PenJoinStyle.RoundJoin
_DASH_LINE = Qt.PenStyle.DashLine
_PROCESS_NOT_RUNNING = QProcess.ProcessState.NotRunning
_PROCESS_FAILED_TO_START = QProcess.ProcessError.FailedToStart
_ANIM_RUNNING = QAbstractAnimation.State.Running

# Drag & drop event types (cached for the same reentrancy reason as above).
_DRAG_ENTER = QEvent.Type.DragEnter
_DRAG_MOVE = QEvent.Type.DragMove
_DRAG_LEAVE = QEvent.Type.DragLeave
_DROP = QEvent.Type.Drop
_DROP_EVENT_TYPES = frozenset({_DRAG_ENTER, _DRAG_MOVE, _DRAG_LEAVE, _DROP})

# File kinds accepted by the various drop targets.
EXEC_DROP_EXTENSIONS = ('.appimage', '.sh', '.py', '.run', '.bin')
IMAGE_DROP_EXTENSIONS = ('.png', '.svg', '.xpm', '.ico', '.jpg', '.jpeg')

_NAME_SPLIT_RE = re.compile(r'[-_.\s]+')
_VERSION_TOKEN_RE = re.compile(r'v?\d[\w.]*')
#: freedesktop field codes (%f %U %i ...) that must be stripped before launch.
_FIELD_CODE_RE = re.compile(r'%[fFuUdDnNickvm]')
_JUNK_NAME_TOKENS = {
    'x86', 'x86_64', 'amd64', 'i386', 'i686', 'arm', 'arm64', 'aarch64',
    'linux', 'windows', 'win', 'win32', 'win64', 'macos', 'osx', 'universal',
    'portable', 'appimage',
}


def _local_paths(mime_data):
    """Local file paths carried by a drag's mime data."""
    if mime_data is None or not mime_data.hasUrls():
        return []
    return [
        path for url in mime_data.urls()
        if url.isLocalFile() and (path := url.toLocalFile())
    ]


def is_executable_drop(path):
    """True for AppImages, scripts and generic executable binaries."""
    if not path or not os.path.isfile(path):
        return False
    if str(path).lower().endswith(EXEC_DROP_EXTENSIONS):
        return True
    return os.access(path, os.X_OK)


def is_image_drop(path):
    """True for image files usable as an application icon."""
    if not path or not os.path.isfile(path):
        return False
    return str(path).lower().endswith(IMAGE_DROP_EXTENSIONS)


def suggest_app_name(path):
    """Derive a clean display name from a dropped filename.

    Version/build/platform tokens are stripped: ``Liner-0.1.35.AppImage``
    and ``liner_0.1.35.sh`` both become ``Liner``; ``super_tux_kart`` becomes
    ``Super Tux Kart``.
    """
    name = Path(path).name
    for ext in EXEC_DROP_EXTENSIONS:
        if name.lower().endswith(ext):
            name = name[:-len(ext)]
            break
    else:
        name = os.path.splitext(name)[0]

    tokens = [token for token in _NAME_SPLIT_RE.split(name) if token]
    words = []
    for token in tokens:
        lowered = token.lower()
        if lowered in _JUNK_NAME_TOKENS or _VERSION_TOKEN_RE.fullmatch(lowered):
            break
        words.append(token)
    if not words:
        words = tokens[:1] or [name]
    return ' '.join(
        word if any(ch.isupper() for ch in word) else word.capitalize()
        for word in words
    )


def detect_icon_for_path(path, name=''):
    """Best-effort icon for a dropped executable.

    Looks for a sibling image sharing the file's stem (``Liner.AppImage`` +
    ``Liner.png``) or the cleaned display name, reuses an icon previously
    extracted from the AppImage, then falls back to a themed icon name;
    ``''`` lets the caller use the initial-badge fallback.
    """
    path = Path(path)
    stems = []
    for stem in (path.stem, (name or '').replace(' ', '')):
        if stem and stem.lower() not in [s.lower() for s in stems]:
            stems.append(stem)

    for stem in stems:
        for ext in ('.png', '.svg', '.xpm', '.ico', '.jpg'):
            sibling = path.parent / f'{stem}{ext}'
            if sibling.is_file():
                return str(sibling)
    cached = cached_appimage_icon_path(path)
    if cached:
        return cached
    for stem in stems:
        candidate = stem.lower()
        if candidate and QIcon.hasThemeIcon(candidate):
            return candidate
    return ''


# --------------------------------------------------------------------------- #
# AppImage icon extraction (background)
# --------------------------------------------------------------------------- #
class _IconExtractionBridge(QObject):
    """Funnels worker-thread results back into the GUI thread."""

    icon_ready = pyqtSignal(str, str)  # (appimage path, cached icon path)


_icon_bridge = None
_icon_inflight = set()
_icon_inflight_lock = threading.Lock()


class _IconExtractionTask(QRunnable):
    def __init__(self, appimage_path):
        super().__init__()
        self._path = str(appimage_path)

    def run(self):
        icon = ''
        try:
            icon = extract_appimage_icon(self._path) or ''
        except Exception:
            icon = ''
        with _icon_inflight_lock:
            _icon_inflight.discard(self._path)
        if icon:
            _icon_bridge_ref().icon_ready.emit(self._path, icon)


def _icon_bridge_ref():
    """Lazily create the module-level bridge (always on the GUI thread)."""
    global _icon_bridge
    if _icon_bridge is None:
        _icon_bridge = _IconExtractionBridge()
    return _icon_bridge


def request_appimage_icon(appimage_path):
    """Extract the icon of ``appimage_path`` on a worker thread.

    Emits ``_icon_bridge_ref().icon_ready`` when (and only when) an icon was
    found; duplicate in-flight requests for the same file are ignored.
    Returns True when a task was started.
    """
    if not is_appimage(appimage_path):
        return False
    path = str(appimage_path)
    with _icon_inflight_lock:
        if path in _icon_inflight:
            return False
        _icon_inflight.add(path)
    _icon_bridge_ref()  # create on the GUI thread before the worker runs
    QThreadPool.globalInstance().start(_IconExtractionTask(path))
    return True


# --------------------------------------------------------------------------- #
# First-run registration (background)
# --------------------------------------------------------------------------- #
class _FirstRunBridge(QObject):
    """Funnels first-run completion back into the GUI thread."""

    finished = pyqtSignal()


class _FirstRunIntegrationTask(QRunnable):
    """Registers the app in the launcher once, off the GUI thread."""

    def __init__(self, bridge):
        super().__init__()
        self._bridge = bridge

    def run(self):
        try:
            integration.run_first_run_integration()
        except Exception:
            pass  # a background nicety must never crash start-up
        try:
            self._bridge.finished.emit()
        except RuntimeError:
            pass  # the window (and bridge) already went away


def schedule_first_run_integration(bridge):
    """Kick off first-run auto-registration when it has not happened yet.

    Returns True when a background task was started.  ``bridge.finished`` is
    emitted once the task is done so the caller can refresh state-dependent
    UI (the gear-menu toggles) on the GUI thread; start-up itself is never
    blocked.
    """
    if not integration.should_run_first_run_setup():
        return False
    QThreadPool.globalInstance().start(_FirstRunIntegrationTask(bridge))
    return True


def _base_font(point_size=10.5, weight=QFont.Weight.Normal):
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    return font


def _dpr():
    """Device pixel ratio of the primary screen (1.0 when unavailable)."""
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def _elide(font_metrics, text, width, middle=False):
    """Elide ``text`` to ``width`` pixels without using QFontMetrics.elidedText.

    ``elidedText`` has an enum-typed argument that crashes under reentrant
    calls (PyQt6 6.11 / Python 3.14), so we do the math with
    ``horizontalAdvance`` instead. ``middle=True`` matches
    ``Qt.TextElideMode.ElideMiddle`` behaviour.
    """
    text = text or ''
    if width <= 0 or not text:
        return text
    if font_metrics.horizontalAdvance(text) <= width:
        return text

    ellipsis = '\u2026'
    budget = width - font_metrics.horizontalAdvance(ellipsis)
    if budget <= 0:
        return ellipsis

    if not middle:
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if font_metrics.horizontalAdvance(text[:mid]) <= budget:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip() + ellipsis

    low, high = 0, len(text)
    best = ellipsis
    while low <= high:
        mid = (low + high) // 2
        head_len = mid // 2
        tail_len = mid - head_len
        used = 0
        if head_len:
            used += font_metrics.horizontalAdvance(text[:head_len])
        if tail_len:
            used += font_metrics.horizontalAdvance(text[-tail_len:])
        if used <= budget:
            if mid == 0:
                best = ellipsis
            else:
                best = text[:head_len].rstrip() + ellipsis + text[-tail_len:].lstrip()
            low = mid + 1
        else:
            high = mid - 1
    return best


# --------------------------------------------------------------------------- #
# Icon rendering
# --------------------------------------------------------------------------- #
def build_icon_pixmap(app_data, size=ICON_SIZE):
    """Render a crisp, rounded app icon (or a stylized initial badge).

    The pixmap is painted at ``size * devicePixelRatio`` physical pixels and
    tagged with that ratio, so it stays sharp on HiDPI/fractional scaling.
    """
    dpr = _dpr()
    physical = max(1, int(round(size * dpr)))
    canvas = QPixmap(physical, physical)
    canvas.fill(_TRANSPARENT)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    source = _load_icon_source((app_data.get('icon') or '').strip(), physical)
    if source is not None:
        scaled = source.scaled(
            physical, physical,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        radius = ICON_RADIUS * dpr
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, physical, physical), radius, radius)
        painter.setClipPath(clip)
        x = (physical - scaled.width()) / 2.0
        y = (physical - scaled.height()) / 2.0
        painter.drawPixmap(int(x), int(y), scaled)
        painter.setClipping(False)
        # Hairline that follows the rounded silhouette.
        painter.setPen(QPen(QColor(PALETTE['surface1']), 1))
        painter.setBrush(_NO_BRUSH)
        painter.drawRoundedRect(QRectF(0.5, 0.5, physical - 1, physical - 1), radius, radius)
    else:
        _paint_badge(painter, app_data, physical, dpr)

    painter.end()
    canvas.setDevicePixelRatio(dpr)
    return canvas


def _load_icon_source(icon_ref, physical):
    """Resolve an icon field to a QPixmap (file path or themed icon name)."""
    if not icon_ref:
        return None
    if os.path.exists(icon_ref):
        pixmap = QPixmap(icon_ref)
        if not pixmap.isNull():
            return pixmap
        return None
    if '/' not in icon_ref:
        themed = QIcon.fromTheme(icon_ref)
        if not themed.isNull():
            pixmap = themed.pixmap(QSize(physical, physical))
            if not pixmap.isNull():
                return pixmap
    return None


def _paint_badge(painter, app_data, physical, dpr):
    """Fallback badge: rounded surface tile with the initial in accent mauve."""
    radius = ICON_RADIUS * dpr
    rect = QRectF(0.5, 0.5, physical - 1, physical - 1)
    painter.setPen(QPen(QColor(PALETTE['surface1']), 1))
    painter.setBrush(QColor(PALETTE['surface0']))
    painter.drawRoundedRect(rect, radius, radius)

    name = (app_data.get('name') or '').strip()
    letter = next((ch.upper() for ch in name if ch.isalnum()), '?')
    font = _base_font()
    font.setPixelSize(max(10, int(physical * 0.42)))
    font.setWeight(QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor(PALETTE['mauve']))
    painter.drawText(QRectF(0, 0, physical, physical), _ALIGN_CENTER, letter)


# --------------------------------------------------------------------------- #
# Drag & drop
# --------------------------------------------------------------------------- #
class DropOverlay(QWidget):
    """'Drop here' frame: dashed accent border over a faint accent tint.

    Covers the whole dashboard while a valid file hovers it. Transparent to
    mouse events so it never swallows the drag it is advertising.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        accent = QColor(PALETTE['mauve'])
        tint = QColor(accent)
        tint.setAlphaF(0.05)
        pen = QPen(accent, 2)
        pen.setStyle(_DASH_LINE)
        painter.setPen(pen)
        painter.setBrush(tint)
        painter.drawRoundedRect(rect, 14, 14)


class DropLineEdit(QLineEdit):
    """Line edit that accepts file drops with drag-active visual feedback.

    ``kind='exec'`` accepts AppImages / scripts / executables and
    ``kind='icon'`` accepts image files; the first valid local file is written
    into the field and announced via :attr:`dropped`.
    """

    dropped = pyqtSignal(str)

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setAcceptDrops(True)
        self.setProperty('dragActive', False)

    def _drop_path(self, event):
        checker = is_executable_drop if self.kind == 'exec' else is_image_drop
        for path in _local_paths(event.mimeData()):
            if checker(path):
                return path
        return None

    def _set_drag_active(self, active):
        if bool(self.property('dragActive')) == active:
            return
        self.setProperty('dragActive', active)
        # Re-polish so the QLineEdit[dragActive="true"] QSS rule applies.
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def dragEnterEvent(self, event):
        if self._drop_path(event) is not None:
            self._set_drag_active(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drag_active(False)
        path = self._drop_path(event)
        if path is None:
            event.ignore()
            return
        self.setText(path)
        self.dropped.emit(path)
        event.acceptProposedAction()


def _start_detached(program, args):
    """Start ``program`` with ``args``, detached from this process.

    Module-level seam so tests can record launches without spawning anything.
    """
    started, _pid = QProcess.startDetached(program, args)
    return bool(started)


def _open_in_file_manager(path):
    """Ask the desktop to reveal ``path``; module-level seam for tests."""
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))


def _hyprctl_program():
    """Resolve the hyprctl binary; module-level seam for tests."""
    return shutil.which('hyprctl')


def _choose_from_menu(menu, anchor):
    """Popup ``menu`` under ``anchor``; module-level seam for tests."""
    return menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))


def _window_classes_from_clients(payload):
    """Parse ``hyprctl clients -j`` output into unique ``(class, title)`` pairs.

    Windows without a class are skipped and duplicates collapse to their
    first occurrence, so the chooser stays readable.
    """
    try:
        clients = json.loads(payload)
    except (TypeError, ValueError):
        return []
    if not isinstance(clients, list):
        return []

    seen = set()
    ordered = []
    for client in clients:
        if not isinstance(client, dict):
            continue
        wm_class = str(client.get('class') or '').strip()
        if not wm_class or wm_class in seen:
            continue
        seen.add(wm_class)
        ordered.append((wm_class, str(client.get('title') or '').strip()))
    return ordered


# --------------------------------------------------------------------------- #
# Animated controls
# --------------------------------------------------------------------------- #
class AnimatedButton(QPushButton):
    """Push button painted in-house so hover/press colours glide smoothly.

    ``progress`` is a 0..1 float animated between idle and hover colours with
    an OutCubic easing; the pressed state snaps a darker overlay on top.
    """

    def __init__(self, text, variant='ghost', parent=None, height=36, padding=34,
                 radius=None):
        super().__init__(text, parent)
        self.variant = variant
        self._radius = radius
        self._apply_variant(variant)
        self._progress = 0.0
        self._pressed = False
        self._paint_alpha = 1.0
        self._ripple_progress = 1.0
        self._ripple_origin = QPointF(0.0, 0.0)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        font = _base_font(10.5, QFont.Weight.DemiBold)
        self.setFont(font)
        metrics = QFontMetrics(font)
        self.setMinimumWidth(metrics.horizontalAdvance(text) + padding + 8)
        self.resize(self.minimumWidth(), height)

        self._anim = QPropertyAnimation(self, b'progress', self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._ripple_anim = QPropertyAnimation(self, b'rippleProgress', self)
        self._ripple_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _apply_variant(self, variant):
        spec = BUTTON_VARIANTS[variant]
        self._idle_bg = QColor(spec['bg'])
        self._hover_bg = QColor(spec['hover'])
        self._press_bg = QColor(spec['press'])
        self._idle_border = QColor(spec['border'])
        self._hover_border = QColor(spec['hover_border'])
        self._text_color = QColor(spec['text'])

    def set_variant(self, variant):
        """Switch colour palette (used by the segmented control)."""
        self.variant = variant
        self._apply_variant(variant)
        self.update()

    def refresh_theme(self):
        """Re-read the variant colours after a live palette swap."""
        self._apply_variant(self.variant)
        self.update()

    def _get_progress(self):
        return self._progress

    def _set_progress(self, value):
        self._progress = float(value)
        self.update()

    progress = pyqtProperty(float, fget=_get_progress, fset=_set_progress)

    def _current_text_color(self):
        if not self.isEnabled():
            return QColor(PALETTE['overlay0'])
        return QColor(self._text_color)

    def set_paint_alpha(self, alpha):
        """Multiply the alpha of everything this button paints.

        Used to fade the hover-only icon buttons without attaching a second
        QGraphicsOpacityEffect (nested effects break Qt's painter).
        """
        self._paint_alpha = max(0.0, min(1.0, float(alpha)))
        self.update()

    def _apply_paint_alpha(self, color):
        if self._paint_alpha >= 1.0:
            return QColor(color)
        faded = QColor(color)
        faded.setAlphaF(faded.alphaF() * self._paint_alpha)
        return faded

    def _animate_to(self, target):
        duration = CARD_HOVER_MS
        self._anim.stop()
        if duration <= 0:
            self._set_progress(target)
            return
        self._anim.setDuration(duration)
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, event):
        self._animate_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._pressed = False
        self._animate_to(0.0)
        super().leaveEvent(event)

    # -- ripple ------------------------------------------------------------- #
    def _get_ripple_progress(self):
        return self._ripple_progress

    def _set_ripple_progress(self, value):
        self._ripple_progress = max(0.0, min(1.0, float(value)))
        self.update()

    rippleProgress = pyqtProperty(float, fget=_get_ripple_progress, fset=_set_ripple_progress)

    def _animate_ripple(self):
        duration = RIPPLE_MS
        self._ripple_anim.stop()
        if duration <= 0:
            # Skip alive markers entirely: no ripple frames in instant mode.
            self._set_ripple_progress(1.0)
            return
        self._set_ripple_progress(0.0)
        self._ripple_anim.setDuration(duration)
        self._ripple_anim.setStartValue(0.0)
        self._ripple_anim.setEndValue(1.0)
        self._ripple_anim.start()

    def mousePressEvent(self, event):
        self._pressed = True
        self._ripple_origin = event.position()
        self._animate_ripple()
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def stop_animations(self):
        self._anim.stop()
        self._ripple_anim.stop()

    def paintEvent(self, event):
        if self._paint_alpha <= 0.0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._radius is not None:
            radius = float(self._radius)
        else:
            radius = 10.0 if self.height() >= 34 else 8.0
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if not self.isEnabled():
            bg = QColor(PALETTE['surface0'])
            border = QColor(PALETTE['surface1'])
        else:
            bg = QColor(blend_hex(self._idle_bg.name(), self._hover_bg.name(), self._progress))
            border = QColor(blend_hex(self._idle_border.name(), self._hover_border.name(), self._progress))
            if self._pressed:
                bg = QColor(blend_hex(bg.name(), self._press_bg.name(), 0.65))

        painter.setPen(QPen(self._apply_paint_alpha(border), 1))
        painter.setBrush(self._apply_paint_alpha(bg))
        painter.drawRoundedRect(rect, radius, radius)

        if 0.0 < self._ripple_progress < 1.0:
            self._paint_ripple(painter, rect, radius, bg.name())

        if self.hasFocus():
            painter.setPen(QPen(self._apply_paint_alpha(QColor(PALETTE['lavender'])), 1))
            painter.setBrush(_NO_BRUSH)
            painter.drawRoundedRect(rect.adjusted(2.5, 2.5, -2.5, -2.5), radius - 2, radius - 2)

        if self.text():
            painter.setPen(self._apply_paint_alpha(self._current_text_color()))
            painter.setFont(self.font())
            painter.drawText(self.rect(), _ALIGN_CENTER, self.text())

    def _paint_ripple(self, painter, rect, radius, surface):
        """A soft expanding disc from the click point, clipped to the pill."""
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        origin = self._ripple_origin
        reach = max(
            math.hypot(origin.x() - rect.left(), origin.y() - rect.top()),
            math.hypot(origin.x() - rect.right(), origin.y() - rect.top()),
            math.hypot(origin.x() - rect.left(), origin.y() - rect.bottom()),
            math.hypot(origin.x() - rect.right(), origin.y() - rect.bottom()),
        )
        tint = QColor(contrast_tint(surface))
        tint.setAlphaF(0.18 * (1.0 - self._ripple_progress))
        fade = QColor(tint)
        fade.setAlphaF(0.0)
        current = max(reach * self._ripple_progress, 1.0)
        # Radial falloff so the disc never shows a hard moving edge.
        gradient = QRadialGradient(origin, current)
        gradient.setColorAt(0.0, self._apply_paint_alpha(tint))
        gradient.setColorAt(0.55, self._apply_paint_alpha(tint))
        gradient.setColorAt(1.0, self._apply_paint_alpha(fade))
        painter.save()
        painter.setClipPath(path)
        painter.setPen(_NO_PEN)
        painter.setBrush(gradient)
        painter.drawEllipse(origin, current, current)
        painter.restore()


class ToggleSwitch(QAbstractButton):
    """Small animated on/off pill switch (mauve track when checked)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedSize(42, 22)
        self._offset = 0.0
        self._pulse = 0.0

        self._anim = QPropertyAnimation(self, b'offset', self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pulse_anim = QPropertyAnimation(self, b'pulse', self)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_to_state)
        self.toggled.connect(self._animate_pulse)

    def _get_offset(self):
        return self._offset

    def _set_offset(self, value):
        self._offset = max(0.0, min(1.0, float(value)))
        self.update()

    offset = pyqtProperty(float, fget=_get_offset, fset=_set_offset)

    def _get_pulse(self):
        return self._pulse

    def _set_pulse(self, value):
        self._pulse = max(0.0, min(1.0, float(value)))
        self.update()

    pulse = pyqtProperty(float, fget=_get_pulse, fset=_set_pulse)

    def _animate_pulse(self, *_args):
        """One expanding ring from the knob each time the state flips."""
        duration = PULSE_MS
        self._pulse_anim.stop()
        if duration <= 0:
            self._set_pulse(1.0)
            return
        self._set_pulse(0.0)
        self._pulse_anim.setDuration(duration)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.start()

    def _animate_to_state(self, checked):
        target = 1.0 if checked else 0.0
        duration = TOGGLE_ANIM_MS
        self._anim.stop()
        if duration <= 0:
            self._set_offset(target)
            return
        self._anim.setDuration(duration)
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(target)
        self._anim.start()

    def stop_animations(self):
        self._anim.stop()
        self._pulse_anim.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        radius = self.height() / 2.0
        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        track_color = QColor(blend_hex(
            PALETTE['surface1'], PALETTE['mauve'], self._offset))

        painter.setPen(_NO_PEN)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, radius, radius)

        knob_radius = radius - 3.0
        knob_x = 3.0 + knob_radius + (self.width() - 6.0 - 2.0 * knob_radius) * self._offset
        knob = QRectF(0.0, 0.0, knob_radius * 2.0, knob_radius * 2.0)
        knob.moveCenter(QPointF(knob_x, self.height() / 2.0))
        painter.setBrush(QColor(PALETTE['base']))
        painter.drawEllipse(knob)

        if 0.0 < self._pulse < 1.0:
            ring = QColor(PALETTE['mauve'])
            ring.setAlphaF(0.40 * (1.0 - self._pulse))
            painter.setPen(QPen(ring, 2.0))
            painter.setBrush(_NO_BRUSH)
            grow = knob_radius + 4.0 * self._pulse
            painter.drawEllipse(
                QPointF(knob_x, self.height() / 2.0), grow, grow)

        if self.hasFocus():
            painter.setPen(QPen(QColor(PALETTE['lavender']), 1))
            painter.setBrush(_NO_BRUSH)
            painter.drawRoundedRect(
                track.adjusted(2.5, 2.5, -2.5, -2.5), radius - 2.5, radius - 2.5)


def _paint_pencil(painter, box, color):
    """Draw a small pencil glyph inside ``box`` (rotated 45 degrees)."""
    painter.save()
    painter.translate(box.center())
    painter.rotate(-45)
    painter.setPen(_NO_PEN)
    painter.setBrush(color)
    # Tip triangle pointing down.
    painter.drawPolygon(QPolygonF([
        QPointF(0.0, 7.4),
        QPointF(-2.4, 2.6),
        QPointF(2.4, 2.6),
    ]))
    # Body.
    painter.drawRect(QRectF(-2.4, -6.0, 4.8, 8.6))
    # Cap line separating the eraser end.
    pen = QPen(color, 1.4)
    pen.setCapStyle(_ROUND_CAP)
    painter.setPen(pen)
    painter.setBrush(_NO_BRUSH)
    painter.drawLine(QPointF(-2.4, -2.0), QPointF(2.4, -2.0))
    painter.restore()


def _paint_trash(painter, box, color):
    """Draw a small trash-can glyph inside ``box``."""
    pen = QPen(color, 1.6)
    pen.setCapStyle(_ROUND_CAP)
    pen.setJoinStyle(_ROUND_JOIN)
    painter.setPen(pen)
    painter.setBrush(_NO_BRUSH)

    center_x = box.center().x()
    painter.drawLine(
        QPointF(box.left() + 2.0, box.top() + 4.6),
        QPointF(box.right() - 2.0, box.top() + 4.6),
    )
    painter.drawLine(
        QPointF(center_x - 2.4, box.top() + 2.6),
        QPointF(center_x - 2.4, box.top() + 4.6),
    )
    painter.drawLine(
        QPointF(center_x + 2.4, box.top() + 2.6),
        QPointF(center_x + 2.4, box.top() + 4.6),
    )
    painter.drawLine(
        QPointF(center_x - 2.4, box.top() + 2.6),
        QPointF(center_x + 2.4, box.top() + 2.6),
    )
    painter.drawRoundedRect(
        QRectF(box.left() + 4.0, box.top() + 6.4, box.width() - 8.0, box.height() - 8.6),
        1.6, 1.6,
    )
    painter.drawLine(
        QPointF(center_x - 1.6, box.top() + 9.2),
        QPointF(center_x - 1.6, box.bottom() - 3.4),
    )
    painter.drawLine(
        QPointF(center_x + 1.6, box.top() + 9.2),
        QPointF(center_x + 1.6, box.bottom() - 3.4),
    )


def _paint_gear(painter, box, color):
    """Draw a small six-tooth gear glyph inside ``box``."""
    center = box.center()
    pen = QPen(color, 1.6)
    pen.setCapStyle(_ROUND_CAP)
    painter.setPen(pen)
    painter.setBrush(_NO_BRUSH)
    outer = QRectF(0.0, 0.0, box.width() * 0.52, box.height() * 0.52)
    outer.moveCenter(center)
    painter.drawEllipse(outer)

    inner_radius = box.width() * 0.26
    outer_radius = box.width() * 0.40
    for step in range(6):
        angle = math.radians(step * 60)
        dx, dy = math.cos(angle), math.sin(angle)
        painter.drawLine(
            QPointF(center.x() + dx * inner_radius, center.y() + dy * inner_radius),
            QPointF(center.x() + dx * outer_radius, center.y() + dy * outer_radius),
        )

    painter.setPen(_NO_PEN)
    painter.setBrush(color)
    hub = QRectF(0.0, 0.0, box.width() * 0.14, box.height() * 0.14)
    hub.moveCenter(center)
    painter.drawEllipse(hub)


def _paint_play(painter, box, color):
    """Draw a small filled 'launch' triangle inside ``box``."""
    painter.setPen(_NO_PEN)
    painter.setBrush(color)
    center = box.center()
    radius = box.width() * 0.40
    painter.drawPolygon(QPolygonF([
        QPointF(center.x() - radius * 0.55, center.y() - radius),
        QPointF(center.x() - radius * 0.55, center.y() + radius),
        QPointF(center.x() + radius * 0.85, center.y()),
    ]))


def _paint_folder(painter, box, color):
    """Draw a small folder outline inside ``box``."""
    pen = QPen(color, 1.6)
    pen.setCapStyle(_ROUND_CAP)
    pen.setJoinStyle(_ROUND_JOIN)
    painter.setPen(pen)
    painter.setBrush(_NO_BRUSH)

    left = box.left() + 1.0
    right = box.right() - 1.0
    top = box.top() + 1.6
    bottom = box.bottom() - 1.6
    width = right - left

    # Tab on top of the body.
    tab = QPainterPath()
    tab.moveTo(left + 1.0, top + 3.4)
    tab.lineTo(left + 1.0, top + 0.6)
    tab.lineTo(left + width * 0.40, top + 0.6)
    tab.lineTo(left + width * 0.50, top + 3.4)
    tab.closeSubpath()
    painter.drawPath(tab)

    # Body.
    painter.drawRoundedRect(
        QRectF(left, top + 3.0, width, bottom - top - 3.0), 2.0, 2.0)


def _paint_gamepad(painter, box, color):
    """Draw a small controller outline inside ``box`` (GameMode badge)."""
    pen = QPen(color, 1.4)
    pen.setCapStyle(_ROUND_CAP)
    pen.setJoinStyle(_ROUND_JOIN)
    painter.setPen(pen)
    painter.setBrush(_NO_BRUSH)

    body = QRectF(box.left() + 0.8, box.top() + box.height() * 0.24,
                  box.width() - 1.6, box.height() * 0.52)
    painter.drawRoundedRect(body, body.height() * 0.48, body.height() * 0.48)
    center = body.center()

    # D-pad on the left.
    painter.drawLine(
        QPointF(center.x() - box.width() * 0.22, center.y()),
        QPointF(center.x() - box.width() * 0.08, center.y()))
    painter.drawLine(
        QPointF(center.x() - box.width() * 0.15, center.y() - box.height() * 0.075),
        QPointF(center.x() - box.width() * 0.15, center.y() + box.height() * 0.075))

    # Face buttons on the right.
    painter.setPen(_NO_PEN)
    painter.setBrush(color)
    for dx, dy in ((0.10, 0.02), (0.16, -0.06), (0.22, 0.02), (0.16, 0.10)):
        dot = QRectF(0.0, 0.0, box.width() * 0.07, box.width() * 0.07)
        dot.moveCenter(QPointF(center.x() + box.width() * dx,
                               center.y() + box.height() * dy))
        painter.drawEllipse(dot)


def _paint_gpu_chip(painter, box, color):
    """Draw a small chip outline inside ``box`` (NVIDIA offload badge)."""
    pen = QPen(color, 1.3)
    pen.setCapStyle(_ROUND_CAP)
    painter.setPen(pen)
    painter.setBrush(_NO_BRUSH)

    chip = QRectF(box.left() + box.width() * 0.24, box.top() + box.height() * 0.24,
                  box.width() * 0.52, box.height() * 0.52)
    painter.drawRoundedRect(chip, 1.6, 1.6)

    painter.setPen(_NO_PEN)
    painter.setBrush(color)
    core = QRectF(0.0, 0.0, box.width() * 0.20, box.height() * 0.20)
    core.moveCenter(chip.center())
    painter.drawRoundedRect(core, 0.8, 0.8)

    painter.setPen(pen)
    for frac in (0.38, 0.62):
        painter.drawLine(
            QPointF(box.width() * frac, box.height() * 0.10),
            QPointF(box.width() * frac, box.height() * 0.24))
        painter.drawLine(
            QPointF(box.width() * frac, box.height() * 0.76),
            QPointF(box.width() * frac, box.height() * 0.90))
        painter.drawLine(
            QPointF(box.width() * 0.10, box.height() * frac),
            QPointF(box.width() * 0.24, box.height() * frac))
        painter.drawLine(
            QPointF(box.width() * 0.76, box.height() * frac),
            QPointF(box.width() * 0.90, box.height() * frac))


def _perf_badge_pixmap(kind, size):
    """Rendered badge pixmap: peach gamepad or green chip (DPR-aware)."""
    ratio = _dpr()
    pixmap = QPixmap(max(1, round(size * ratio)), max(1, round(size * ratio)))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(_TRANSPARENT)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    color = QColor(PALETTE['peach'] if kind == 'gamemode' else PALETTE['green'])
    box = QRectF(0.0, 0.0, float(size), float(size))
    if kind == 'gamemode':
        _paint_gamepad(painter, box, color)
    else:
        _paint_gpu_chip(painter, box, color)
    painter.end()
    return pixmap


class IconButton(AnimatedButton):
    """Compact square button that renders a vector glyph.

    Glyphs: ``edit``, ``delete``, ``gear``, ``play``, ``folder``.
    """

    def __init__(self, glyph, variant='ghost', parent=None):
        super().__init__('', variant, parent, height=30, padding=0)
        self.glyph = glyph
        self.setFixedSize(30, 30)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._paint_alpha <= 0.0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = self._apply_paint_alpha(self._current_text_color())
        box = QRectF(0, 0, 16, 16)
        box.moveCenter(QRectF(self.rect()).center())
        if self.glyph == 'edit':
            _paint_pencil(painter, box, color)
        elif self.glyph == 'play':
            _paint_play(painter, box, color)
        elif self.glyph == 'folder':
            _paint_folder(painter, box, color)
        elif self.glyph == 'gear':
            _paint_gear(painter, box, color)
        else:
            _paint_trash(painter, box, color)


class AppCard(QWidget):
    """Rounded application card.

    * hover: background/border animate toward mauve with a soft lavender
      outer glow over 150ms, and the quick actions fade in
    * filtering: opacities fade in/out via QGraphicsOpacityEffect
    """

    def __init__(self, app_data, on_edit=None, on_delete=None, on_launch=None,
                 on_open_dir=None, parent=None):
        super().__init__(parent)
        self.app_data = app_data
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.on_launch = on_launch
        self.on_open_dir = on_open_dir

        self._full_name = app_data.get('name', '') or ''
        self._full_path = (app_data.get('path') or '').strip()
        self._full_exec = (app_data.get('exec_path') or self._full_path).strip()

        self._hover_progress = 0.0
        self._fade_anim = None
        self._opacity_effect = None
        self._actions_visible = False
        self._actions_opacity = 0.0
        self._appear_progress = 1.0

        self.setFixedHeight(CARD_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._hover_anim = QPropertyAnimation(self, b'hoverProgress', self)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._appear_anim = QPropertyAnimation(self, b'appearProgress', self)
        self._appear_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Elevation: a QGraphicsDropShadowEffect animated via shadowProgress.
        # A widget can host only one graphics effect, so the shadow is dropped
        # whenever a fade (filter or window theme swap) needs the slot.
        self._shadow_effect = None
        self._shadow_progress = 0.0
        self._shadow_anim = QPropertyAnimation(self, b'shadowProgress', self)
        self._shadow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._shadow_anim.finished.connect(self._on_shadow_anim_finished)

        # Coalesced elide: text is re-elided after resize storms settle, never
        # synchronously inside the resize callback.
        self._elide_timer = QTimer(self)
        self._elide_timer.setSingleShot(True)
        self._elide_timer.setInterval(0)
        self._elide_timer.timeout.connect(self._update_elided_texts)

        self.setup_ui()
        self._elide_timer.start()

    # -- construction ------------------------------------------------------- #
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.icon_label.setStyleSheet('background: transparent;')
        self.load_icon()
        layout.addWidget(self.icon_label, 0, _ALIGN_VCENTER)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(5)

        self.name_label = QLabel(self._full_name)
        self.name_label.setObjectName('appName')
        self.name_label.setToolTip(self._full_name)
        # Ignored horizontal policy so the label can shrink below its text
        # width; eliding is handled explicitly in _update_elided_texts.
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info.addWidget(self.name_label)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(8)

        self.category_label = QLabel(self.app_data.get('category', 'Utility'))
        self.category_label.setAlignment(_ALIGN_CENTER)
        self.category_label.setStyleSheet(self._badge_style(self.app_data.get('category', 'Utility')))
        meta.addWidget(self.category_label, 0)

        self.path_label = QLabel(self._full_path)
        self.path_label.setObjectName('appPath')
        self.path_label.setToolTip(self._full_exec)
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        meta.addWidget(self.path_label, 1)

        # Small performance badges (GameMode / NVIDIA offload), right-aligned.
        self.perf_badges = {}
        for kind, tooltip in (
            ('gamemode', 'Launches with GameMode'),
            ('prime_gpu', 'Renders on the discrete NVIDIA GPU'),
        ):
            badge = QLabel()
            badge.setObjectName('perfBadge')
            badge.setToolTip(tooltip)
            badge.setStyleSheet('background: transparent;')
            meta.addWidget(badge, 0)
            self.perf_badges[kind] = badge
        self._update_perf_badges()

        info.addLayout(meta)
        layout.addLayout(info, 1)

        # Hover-only icon actions; the container keeps its layout footprint so
        # nothing jumps when the buttons fade in. Their fade is done by
        # painting the buttons with animated alpha (a nested
        # QGraphicsOpacityEffect would conflict with the card's filter fade).
        self.actions_widget = QWidget(self)
        actions_layout = QHBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)

        self.launch_button = IconButton('play')
        self.launch_button.setToolTip('Launch')
        self.launch_button.clicked.connect(self._on_launch)
        actions_layout.addWidget(self.launch_button)

        self.edit_button = IconButton('edit', 'ghost')
        self.edit_button.setToolTip('Edit')
        self.edit_button.clicked.connect(self._on_edit)
        actions_layout.addWidget(self.edit_button)

        self.open_dir_button = IconButton('folder')
        self.open_dir_button.setToolTip('Open Directory')
        self.open_dir_button.clicked.connect(self._on_open_dir)
        actions_layout.addWidget(self.open_dir_button)

        self.delete_button = IconButton('delete', 'danger')
        self.delete_button.setToolTip('Delete')
        self.delete_button.clicked.connect(self._on_delete)
        actions_layout.addWidget(self.delete_button)

        self._action_buttons = (
            self.launch_button, self.edit_button,
            self.open_dir_button, self.delete_button,
        )
        self._actions_anim = QPropertyAnimation(self, b'actionsOpacity', self)
        self._actions_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._actions_anim.finished.connect(self._on_actions_anim_finished)

        self._set_actions_interactive(False)
        self._apply_actions_opacity()
        layout.addWidget(self.actions_widget, 0, _ALIGN_VCENTER)

    def _badge_style(self, category):
        tint = CATEGORY_COLORS.get(category, CATEGORY_COLORS['Utility'])
        return (
            f"color: {tint['text']};"
            f" background-color: {tint['bg']};"
            f" border: 1px solid {tint['border']};"
            " border-radius: 9px;"
            " padding: 1px 9px;"
            " font-size: 10px;"
            " font-weight: 600;"
        )

    def load_icon(self):
        self.icon_label.setPixmap(build_icon_pixmap(self.app_data, ICON_SIZE))

    def _update_perf_badges(self):
        """Show/hide the GameMode and GPU badges from the entry's flags."""
        for kind in ('gamemode', 'prime_gpu'):
            badge = self.perf_badges[kind]
            badge.setPixmap(_perf_badge_pixmap(kind, PERF_BADGE_SIZE))
            badge.setVisible(bool(self.app_data.get(kind)))

    def refresh_theme(self):
        """Re-tint everything baked in at construction time after a palette swap.

        The category badge stylesheet, the icon (its fallback badge and
        hairline follow the palette), the performance badges, the hover
        elevation colour and the hover-action buttons all carry colours
        captured before the change.
        """
        self.category_label.setStyleSheet(
            self._badge_style(self.app_data.get('category', 'Utility')))
        self.load_icon()
        self._update_perf_badges()
        if self._shadow_effect is not None:
            color = QColor(CARD_COLORS['hover_shadow'])
            color.setAlphaF(SHADOW_ALPHA)
            self._shadow_effect.setColor(color)
        for button in self._action_buttons:
            button.refresh_theme()
        self.update()

    # -- hover animation ---------------------------------------------------- #
    def _get_hover_progress(self):
        return self._hover_progress

    def _set_hover_progress(self, value):
        self._hover_progress = float(value)
        self.update()

    hoverProgress = pyqtProperty(float, fget=_get_hover_progress, fset=_set_hover_progress)

    def _animate_hover(self, target):
        duration = CARD_HOVER_MS
        self._hover_anim.stop()
        if duration <= 0:
            self._set_hover_progress(target)
            return
        self._hover_anim.setDuration(duration)
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    # -- appear settle ------------------------------------------------------ #
    def _get_appear_progress(self):
        return self._appear_progress

    def _set_appear_progress(self, value):
        self._appear_progress = max(0.0, min(1.0, float(value)))
        self.update()

    appearProgress = pyqtProperty(float, fget=_get_appear_progress, fset=_set_appear_progress)

    def start_appear_settle(self):
        """Ease the card body out from a small inset (paint-only, no layout)."""
        duration = CARD_APPEAR_MS
        self._appear_anim.stop()
        if duration <= 0:
            self._set_appear_progress(1.0)
            return
        self._set_appear_progress(0.0)
        self._appear_anim.setDuration(duration)
        self._appear_anim.setStartValue(0.0)
        self._appear_anim.setEndValue(1.0)
        self._appear_anim.start()

    # -- hover elevation ---------------------------------------------------- #
    def _get_shadow_progress(self):
        return self._shadow_progress

    def _set_shadow_progress(self, value):
        self._shadow_progress = max(0.0, min(1.0, float(value)))
        if self._shadow_effect is not None:
            self._shadow_effect.setBlurRadius(SHADOW_MAX_BLUR * self._shadow_progress)

    shadowProgress = pyqtProperty(float, fget=_get_shadow_progress, fset=_set_shadow_progress)

    def _can_elevate(self):
        """Elevation yields the (single) graphics-effect slot to any fade."""
        if self._opacity_effect is not None:
            return False
        return getattr(self.window(), '_theme_effect', None) is None

    def _ensure_hover_shadow(self):
        if self._shadow_effect is not None:
            return self._shadow_effect
        if not self._can_elevate():
            return None
        effect = QGraphicsDropShadowEffect(self)
        effect.setOffset(0.0, SHADOW_OFFSET_Y)
        color = QColor(CARD_COLORS['hover_shadow'])
        color.setAlphaF(SHADOW_ALPHA)
        effect.setColor(color)
        effect.setBlurRadius(0.0)
        self._shadow_effect = effect
        self.setGraphicsEffect(effect)
        return effect

    def _animate_shadow(self, target):
        self._shadow_anim.stop()
        if target > 0.0 and self._ensure_hover_shadow() is None:
            return
        duration = SHADOW_ANIM_MS
        if duration <= 0:
            self._set_shadow_progress(target)
            self._on_shadow_anim_finished()
            return
        self._shadow_anim.setDuration(duration)
        self._shadow_anim.setStartValue(self._shadow_progress)
        self._shadow_anim.setEndValue(target)
        self._shadow_anim.start()

    def _on_shadow_anim_finished(self):
        if self._shadow_progress <= 0.01:
            self._drop_hover_shadow()

    def _drop_hover_shadow(self):
        self._shadow_anim.stop()
        if self._shadow_effect is None:
            return
        self._shadow_effect = None
        if self._opacity_effect is None:
            self.setGraphicsEffect(None)

    def sync_hover_shadow(self):
        """Reconcile elevation with the current hover state.

        Called when a competing graphics effect (filter fade, window theme
        cross-fade) is removed, since only one effect fits per widget.
        """
        if self._shadow_progress <= 0.01 or not self._can_elevate():
            self._drop_hover_shadow()
            return
        effect = self._ensure_hover_shadow()
        if effect is not None:
            effect.setBlurRadius(SHADOW_MAX_BLUR * self._shadow_progress)

    # -- hover-only actions ------------------------------------------------- #
    def _set_actions_interactive(self, enabled):
        for button in self._action_buttons:
            button.setEnabled(enabled)

    def _get_actions_opacity(self):
        return self._actions_opacity

    def _set_actions_opacity(self, value):
        self._actions_opacity = float(value)
        self._apply_actions_opacity()

    actionsOpacity = pyqtProperty(float, fget=_get_actions_opacity, fset=_set_actions_opacity)

    def _apply_actions_opacity(self):
        for button in self._action_buttons:
            button.set_paint_alpha(self._actions_opacity)

    def _set_actions_visible(self, visible):
        self._actions_visible = visible
        if visible:
            self._set_actions_interactive(True)
        duration = CARD_HOVER_MS
        self._actions_anim.stop()
        if duration <= 0:
            self._set_actions_opacity(1.0 if visible else 0.0)
            if not visible:
                self._set_actions_interactive(False)
            return
        self._actions_anim.setDuration(duration)
        self._actions_anim.setStartValue(self._actions_opacity)
        self._actions_anim.setEndValue(1.0 if visible else 0.0)
        self._actions_anim.start()

    def _on_actions_anim_finished(self):
        # On fade-out completion the (invisible) buttons must not be clickable.
        self._set_actions_interactive(self._actions_visible)

    def enterEvent(self, event):
        self._animate_hover(1.0)
        self._animate_shadow(1.0)
        self._set_actions_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        self._animate_shadow(0.0)
        self._set_actions_visible(False)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = self._hover_progress
        # Inset by 2px so the hover glow ring has room inside the widget and
        # the geometry never changes (paint-only effect, no layout thrash);
        # a freshly appeared card starts slightly deeper inset and settles.
        inset = 2.0 + CARD_APPEAR_INSET * (1.0 - self._appear_progress)
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        if t > 0.0:
            glow = QColor(CARD_COLORS['hover_glow'])
            glow.setAlphaF(0.35 * t)
            painter.setPen(QPen(glow, 2.0))
            painter.setBrush(_NO_BRUSH)
            painter.drawRoundedRect(
                rect.adjusted(-0.75, -0.75, 0.75, 0.75),
                CARD_RADIUS + 0.75, CARD_RADIUS + 0.75)
        # Glassmorphic surface: the body is translucent and composites over
        # the window chrome; the alpha deepens toward opacity on hover.
        bg = QColor(blend_hex(CARD_COLORS['bg'], CARD_COLORS['hover_bg'], t))
        bg.setAlphaF(
            CARD_COLORS['bg_alpha']
            + (CARD_COLORS['hover_bg_alpha'] - CARD_COLORS['bg_alpha']) * t)
        border = QColor(blend_hex(CARD_COLORS['border'], CARD_COLORS['hover_border'], t))
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

    # -- elided text -------------------------------------------------------- #
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._elide_timer.start()

    def _update_elided_texts(self):
        name_width = self.name_label.width()
        if name_width > 0:
            self.name_label.setText(_elide(
                self.name_label.fontMetrics(), self._full_name, name_width))
        path_width = self.path_label.width()
        if path_width > 0:
            self.path_label.setText(_elide(
                self.path_label.fontMetrics(), self._full_path, path_width, middle=True))

    # -- filter fade -------------------------------------------------------- #
    def _ensure_opacity_effect(self):
        # Elevation must yield first: one graphics effect per widget.
        self._drop_hover_shadow()
        if self._opacity_effect is None:
            self._opacity_effect = QGraphicsOpacityEffect(self)
            self._opacity_effect.setOpacity(1.0)
            self.setGraphicsEffect(self._opacity_effect)
        return self._opacity_effect

    def _clear_opacity_effect(self):
        if self._opacity_effect is not None:
            self._opacity_effect = None
            self.setGraphicsEffect(None)
        self.sync_hover_shadow()

    def set_filter_visible(self, visible, duration, on_done=None):
        """Show/hide this card, optionally fading over ``duration`` ms."""
        if self._fade_anim is not None:
            self._fade_anim.stop()
            self._fade_anim = None

        if visible:
            was_visible = not self.isHidden()
            self.setVisible(True)
            if duration <= 0 or was_visible:
                self._clear_opacity_effect()
                if on_done:
                    on_done()
                return
            effect = self._ensure_opacity_effect()
            effect.setOpacity(0.0)
            self.start_appear_settle()
            anim = QPropertyAnimation(effect, b'opacity', self)
            anim.setDuration(duration)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(self._on_fade_in_finished)
            self._fade_anim = anim
            anim.start()
        else:
            if self.isHidden():
                if on_done:
                    on_done()
                return
            if duration <= 0:
                self.setVisible(False)
                self._clear_opacity_effect()
                if on_done:
                    on_done()
                return
            effect = self._ensure_opacity_effect()
            anim = QPropertyAnimation(effect, b'opacity', self)
            anim.setDuration(duration)
            anim.setStartValue(effect.opacity())
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda: self._on_fade_out_finished(on_done))
            self._fade_anim = anim
            anim.start()

    def _on_fade_in_finished(self):
        self._fade_anim = None
        self._clear_opacity_effect()

    def _on_fade_out_finished(self, on_done):
        self._fade_anim = None
        self.setVisible(False)
        self._clear_opacity_effect()
        if on_done:
            on_done()

    def stop_animations(self):
        if self._fade_anim is not None:
            self._fade_anim.stop()
            self._fade_anim = None
        self._hover_anim.stop()
        self._actions_anim.stop()
        self._appear_anim.stop()
        self._shadow_anim.stop()
        if self._opacity_effect is not None:
            self._opacity_effect = None
            self.setGraphicsEffect(None)
        self._drop_hover_shadow()

    def stop_filter_animation(self):
        """Cancel a running filter fade and drop any graphics effect.

        Used by the *window-level* theme transition: nested effects in one
        subtree break Qt's painter ("painted by one painter" corruption), so
        both the filter fade and the hover elevation yield their slot.
        """
        if self._fade_anim is not None:
            self._fade_anim.stop()
            self._fade_anim = None
        if self._opacity_effect is not None:
            self._opacity_effect = None
            self.setGraphicsEffect(None)
        self._drop_hover_shadow()

    # -- actions ------------------------------------------------------------ #
    def _on_edit(self):
        if self.on_edit:
            self.on_edit(self.app_data)

    def _on_delete(self):
        if self.on_delete:
            self.on_delete(self.app_data)

    def _on_launch(self):
        if self.on_launch:
            self.on_launch(self.app_data)

    def _on_open_dir(self):
        if self.on_open_dir:
            self.on_open_dir(self.app_data)


class SearchBar(QLineEdit):
    """Pill-shaped search field (styling lives in the global QSS).

    Carries an integrated leading magnifier icon and an instant, themed
    trailing clear button that only appears while there is text.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('searchBar')
        self.setPlaceholderText('Search applications...')
        self.setFixedHeight(44)

        # Integrated leading magnifier (decorative - never steals input).
        self._search_action = self.addAction(
            self._search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self._search_action.setToolTip('Search')

        # Themed clear action, replacing the stock red clear icon.
        self._clear_action = self.addAction(
            self._clear_icon(), QLineEdit.ActionPosition.TrailingPosition)
        self._clear_action.setToolTip('Clear')
        self._clear_action.triggered.connect(self.clear)
        self._clear_action.setVisible(False)
        self.textChanged.connect(
            lambda text: self._clear_action.setVisible(bool(text.strip())))

    def _magnifier_icon(self):
        """A small magnifier drawn at the device pixel ratio of the screen."""
        dpr = _dpr()
        physical = max(1, int(round(16 * dpr)))
        canvas = QPixmap(physical, physical)
        canvas.fill(_TRANSPARENT)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(PALETTE['overlay1']), 1.5 * dpr)
        pen.setCapStyle(_ROUND_CAP)
        painter.setPen(pen)
        painter.setBrush(_NO_BRUSH)
        lens = physical * 0.62
        painter.drawEllipse(QRectF(1.0 * dpr, 1.0 * dpr, lens, lens))
        painter.drawLine(
            QPointF(lens + 0.4 * dpr, lens + 0.4 * dpr),
            QPointF(physical - 1.4 * dpr, physical - 1.4 * dpr))
        painter.end()
        canvas.setDevicePixelRatio(dpr)
        return QIcon(canvas)

    def _search_icon(self):
        return self._magnifier_icon()

    def _clear_icon(self):
        dpr = _dpr()
        physical = max(1, int(round(16 * dpr)))
        canvas = QPixmap(physical, physical)
        canvas.fill(_TRANSPARENT)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(PALETTE['overlay1']), 1.5 * dpr)
        pen.setCapStyle(_ROUND_CAP)
        painter.setPen(pen)
        painter.setBrush(_NO_BRUSH)
        margin = 1.8 * dpr
        painter.drawEllipse(
            QRectF(margin, margin, physical - 2 * margin, physical - 2 * margin))
        inset = 5.0 * dpr
        painter.drawLine(QPointF(inset, inset), QPointF(physical - inset, physical - inset))
        painter.drawLine(QPointF(physical - inset, inset), QPointF(inset, physical - inset))
        painter.end()
        canvas.setDevicePixelRatio(dpr)
        return QIcon(canvas)

    def refresh_theme(self):
        """Re-render the magnifier and clear icons with the new palette."""
        self._search_action.setIcon(self._search_icon())
        self._clear_action.setIcon(self._clear_icon())


class SegmentedControl(QWidget):
    """Two-segment pill toggle (Custom Apps / All System Apps)."""

    changed = pyqtSignal(int)

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        self.setObjectName('segmented')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._buttons = []
        for index, label in enumerate(labels):
            button = AnimatedButton(label, 'segment', height=36, padding=26)
            button.clicked.connect(lambda _=False, idx=index: self.set_index(idx))
            self._buttons.append(button)
            layout.addWidget(button)

        self._index = 0
        self._apply_variants()

    def index(self):
        return self._index

    def set_index(self, index):
        if index == self._index:
            return
        self._index = index
        self._apply_variants()
        self.changed.emit(index)

    def _apply_variants(self):
        for position, button in enumerate(self._buttons):
            button.set_variant('primary' if position == self._index else 'segment')


class CategoryPills(QWidget):
    """Row of floating-tab category filters shown above the grid.

    Exactly one pill is active; clicking another slides a small underline
    indicator over to it and emits ``changed(name)`` so the window re-filters
    the grid with a quick fade.
    """

    changed = pyqtSignal(str)

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._current = labels[0]
        self._buttons = {}
        for label in labels:
            button = AnimatedButton(label, 'segment', height=30, padding=22, radius=15)
            button.clicked.connect(
                lambda _=False, name=label: self.set_current(name))
            self._buttons[label] = button
            layout.addWidget(button)
        self._apply_variants()

        # Sliding underline: from/to pill rectangles interpolated by
        # indicatorProgress (self._indicator_* hold the raw rects).
        self._indicator_from = QRectF()
        self._indicator_to = QRectF()
        self._indicator_progress = 1.0
        self._slide_anim = QPropertyAnimation(self, b'indicatorProgress', self)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def current(self):
        return self._current

    def set_current(self, label):
        if label not in self._buttons or label == self._current:
            return
        self._current = label
        self._apply_variants()
        self._slide_indicator()
        self.changed.emit(label)

    def _apply_variants(self):
        for label, button in self._buttons.items():
            button.set_variant('primary' if label == self._current else 'segment')

    def _get_indicator_progress(self):
        return self._indicator_progress

    def _set_indicator_progress(self, value):
        self._indicator_progress = max(0.0, min(1.0, float(value)))
        self.update()

    indicatorProgress = pyqtProperty(
        float, fget=_get_indicator_progress, fset=_set_indicator_progress)

    def _pill_rect(self, label):
        button = self._buttons.get(label)
        if button is None or button.width() <= 0:
            return QRectF()
        return QRectF(button.geometry())

    def _painted_indicator(self):
        if self._indicator_progress >= 1.0 or self._indicator_from.isNull():
            return self._indicator_to
        t = self._indicator_progress
        start, end = self._indicator_from, self._indicator_to
        return QRectF(
            start.x() + (end.x() - start.x()) * t,
            start.y() + (end.y() - start.y()) * t,
            start.width() + (end.width() - start.width()) * t,
            start.height() + (end.height() - start.height()) * t)

    def _slide_indicator(self):
        """Glide the underline from the previously painted spot to the pill."""
        target = self._pill_rect(self._current)
        if target.isNull():
            return
        start = self._painted_indicator()
        if start.isNull():
            start = target
        self._slide_anim.stop()
        duration = PILL_SLIDE_MS
        if duration <= 0:
            self._indicator_from = target
            self._indicator_to = target
            self._set_indicator_progress(1.0)
            return
        self._indicator_from = start
        self._indicator_to = target
        self._set_indicator_progress(0.0)
        self._slide_anim.setDuration(duration)
        self._slide_anim.setStartValue(0.0)
        self._slide_anim.setEndValue(1.0)
        self._slide_anim.start()

    def _settle_indicator(self):
        """Snap the underline onto the active pill (first layout, resize)."""
        target = self._pill_rect(self._current)
        if target.isNull():
            return
        self._slide_anim.stop()
        self._indicator_from = target
        self._indicator_to = target
        self._set_indicator_progress(1.0)

    def stop_animations(self):
        self._slide_anim.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self._settle_indicator()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._settle_indicator()

    def paintEvent(self, event):
        rect = self._painted_indicator()
        if rect.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bar = QRectF(rect)
        bar.setLeft(rect.left() + 9.0)
        bar.setRight(rect.right() - 9.0)
        bar.setTop(rect.bottom() - 4.5)
        bar.setHeight(2.5)
        color = QColor(contrast_tint(PALETTE['mauve']))
        color.setAlphaF(0.85)
        painter.setPen(_NO_PEN)
        painter.setBrush(color)
        painter.drawRoundedRect(bar, 1.25, 1.25)


def _empty_state_pixmap(size=EMPTY_ICON_SIZE):
    """A friendly 2x2 app-tile illustration for the empty state (HiDPI aware)."""
    dpr = _dpr()
    physical = max(1, int(round(size * dpr)))
    canvas = QPixmap(physical, physical)
    canvas.fill(_TRANSPARENT)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor(PALETTE['surface1']), 1.0))
    painter.setBrush(QColor(PALETTE['surface0']))
    painter.drawRoundedRect(
        QRectF(0.5, 0.5, physical - 1.0, physical - 1.0),
        14.0 * dpr, 14.0 * dpr)

    tile = physical * 0.275
    gap = physical * 0.075
    origin = (physical - (tile * 2 + gap)) / 2.0
    colors = (PALETTE['mauve'], PALETTE['lavender'],
              PALETTE['blue'], PALETTE['green'])
    for index, color in enumerate(colors):
        row, column = divmod(index, 2)
        painter.setPen(_NO_PEN)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(
            QRectF(origin + column * (tile + gap),
                   origin + row * (tile + gap), tile, tile),
            3.5 * dpr, 3.5 * dpr)

    painter.end()
    canvas.setDevicePixelRatio(dpr)
    return canvas


class EmptyState(QWidget):
    """Centered 'nothing here' panel with a dashed drop-target frame.

    Doubles as a drag & drop affordance: the dashed outline frames the panel
    and the hint text invites dropping AppImages anywhere on the window.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('emptyStatePanel')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        layout.addStretch(1)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(_ALIGN_CENTER)
        self.icon_label.setPixmap(_empty_state_pixmap())
        layout.addWidget(self.icon_label, 0, _ALIGN_CENTER)

        self.title_label = QLabel('No Applications Found')
        self.title_label.setObjectName('emptyTitle')
        self.title_label.setAlignment(_ALIGN_CENTER)
        layout.addWidget(self.title_label, 0)

        self.hint_label = QLabel('')
        self.hint_label.setObjectName('emptyState')
        self.hint_label.setAlignment(_ALIGN_CENTER)
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label, 0)

        self.drop_hint = QLabel('or drop an AppImage, script or icon anywhere on this window')
        self.drop_hint.setObjectName('dropHint')
        self.drop_hint.setAlignment(_ALIGN_CENTER)
        layout.addWidget(self.drop_hint, 0)

        layout.addStretch(1)

        # Breathing pulse for the dashed frame: 0 -> 1 -> 0, forever, but
        # only while the panel is actually visible.
        self._breath = 0.0
        rise = QPropertyAnimation(self, b'breath', self)
        rise.setDuration(max(1, BREATH_MS // 2))
        rise.setStartValue(0.0)
        rise.setEndValue(1.0)
        rise.setEasingCurve(QEasingCurve.Type.InOutSine)
        fall = QPropertyAnimation(self, b'breath', self)
        fall.setDuration(max(1, BREATH_MS // 2))
        fall.setStartValue(1.0)
        fall.setEndValue(0.0)
        fall.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._breath_anim = QSequentialAnimationGroup(self)
        self._breath_anim.addAnimation(rise)
        self._breath_anim.addAnimation(fall)
        self._breath_anim.setLoopCount(-1)

    def set_hint(self, text):
        self.hint_label.setText(text)

    def refresh_theme(self):
        self.icon_label.setPixmap(_empty_state_pixmap())
        self.update()

    def _get_breath(self):
        return self._breath

    def _set_breath(self, value):
        self._breath = max(0.0, min(1.0, float(value)))
        self.update()

    breath = pyqtProperty(float, fget=_get_breath, fset=_set_breath)

    def stop_animations(self):
        self._breath_anim.stop()
        self._set_breath(0.0)

    def showEvent(self, event):
        super().showEvent(event)
        # NB: compare against the enum explicitly - PyQt6 enum members are
        # truthy even when their value is zero, so ``not state()`` is wrong.
        if BREATH_MS > 0 and self._breath_anim.state() != _ANIM_RUNNING:
            self._breath_anim.start()

    def hideEvent(self, event):
        self._breath_anim.stop()
        self._set_breath(0.0)
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(PALETTE['overlay0'])
        color.setAlphaF(0.50 + 0.12 * self._breath)
        pen = QPen(color, 1.5)
        pen.setStyle(_DASH_LINE)
        painter.setPen(pen)
        painter.setBrush(_NO_BRUSH)
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0), 16, 16)


# --------------------------------------------------------------------------- #
# Add / edit dialog
# --------------------------------------------------------------------------- #
class CategoryDialog(QDialog):
    """Modal used to add or edit an application entry."""

    def __init__(self, parent=None, app_data=None):
        super().__init__(parent)
        self.app_data = app_data
        self._fade_anim = None
        self._inspect_proc = None
        self.setWindowTitle('Add Application' if not app_data else 'Edit Application')
        self.setFixedSize(560, 440)
        self.setup_ui()
        # Results arrive from a worker thread; the connection is dropped
        # automatically once this dialog is destroyed.
        _icon_bridge_ref().icon_ready.connect(self._on_extracted_icon_ready)

    def setup_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText('e.g. Firefox')
        layout.addRow(self._field_label('Display Name'), self.name_input)

        self.path_input = DropLineEdit('exec')
        self.path_input.setPlaceholderText('Path to an AppImage/executable, or a command')
        self.path_input.dropped.connect(self._on_exec_dropped)
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_row.addWidget(self.path_input, 1)
        browse_button = AnimatedButton('Browse', 'ghost', padding=28)
        browse_button.clicked.connect(self._browse_file)
        path_row.addWidget(browse_button)
        layout.addRow(self._field_label('Executable / AppImage'), path_row)

        # Live icon preview + drop-enabled icon field. The preview follows the
        # icon/name fields and the fallback initial-badge logic.
        self.icon_preview = QLabel()
        self.icon_preview.setObjectName('iconPreview')
        self.icon_preview.setFixedSize(ICON_PREVIEW_SIZE, ICON_PREVIEW_SIZE)
        self.icon_preview.setAlignment(_ALIGN_CENTER)

        self.icon_input = DropLineEdit('icon')
        self.icon_input.setPlaceholderText('Path to a PNG/SVG, or a themed icon name')
        icon_row = QHBoxLayout()
        icon_row.setSpacing(8)
        icon_row.addWidget(self.icon_preview, 0, _ALIGN_VCENTER)
        icon_row.addWidget(self.icon_input, 1)
        icon_browse_button = AnimatedButton('Browse', 'ghost', padding=28)
        icon_browse_button.clicked.connect(self._browse_icon)
        icon_row.addWidget(icon_browse_button)
        layout.addRow(self._field_label('Icon'), icon_row)

        self.icon_input.textChanged.connect(self.update_icon_preview)
        self.name_input.textChanged.connect(self.update_icon_preview)

        self.category_combo = QComboBox()
        self.category_combo.addItems(CATEGORIES)
        layout.addRow(self._field_label('Category'), self.category_combo)

        # StartupWMClass: lets the compositor match the running window to this
        # launcher. "Inspect" lists the classes of open Hyprland windows.
        self.wmclass_input = QLineEdit()
        self.wmclass_input.setPlaceholderText('Optional, e.g. firefox')
        self.wmclass_input.setToolTip(
            'StartupWMClass: the window class the compositor uses to match '
            'the running window against this launcher.')
        self.inspect_button = AnimatedButton('Inspect', 'ghost', padding=24)
        self.inspect_button.setToolTip(
            'List the window class of every open app (needs Hyprland)')
        self.inspect_button.clicked.connect(self._inspect_window_class)
        wmclass_row = QHBoxLayout()
        wmclass_row.setSpacing(8)
        wmclass_row.addWidget(self.wmclass_input, 1)
        wmclass_row.addWidget(self.inspect_button)
        layout.addRow(self._field_label('Window Class'), wmclass_row)

        # Performance wrappers: GameMode and NVIDIA PRIME render offload.
        self.gamemode_toggle = ToggleSwitch()
        gamemode_tip = ('Launch through gamemoderun (GameMode) to optimise '
                        'system performance while this app runs.')
        if shutil.which(GAMEMODE_WRAPPER) is None:
            gamemode_tip += ('\ngamemoderun is not installed yet, so launching '
                             'will fail until it is.')
        self.gamemode_toggle.setToolTip(gamemode_tip)
        self.prime_toggle = ToggleSwitch()
        self.prime_toggle.setToolTip(
            'Run on the discrete NVIDIA GPU via PRIME render offload '
            '(sets __NV_PRIME_RENDER_OFFLOAD=1 and '
            '__GLX_VENDOR_LIBRARY_NAME=nvidia).')

        perf_row = QHBoxLayout()
        perf_row.setSpacing(8)
        perf_row.addWidget(self.gamemode_toggle)
        perf_row.addWidget(QLabel('GameMode'))
        perf_row.addSpacing(14)
        perf_row.addWidget(self.prime_toggle)
        perf_row.addWidget(QLabel('NVIDIA GPU'))
        perf_row.addStretch(1)
        layout.addRow(self._field_label('Performance'), perf_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)

        cancel_button = AnimatedButton('Cancel', 'ghost')
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)

        self.save_button = AnimatedButton(
            'Add App' if not self.app_data else 'Save', 'primary')
        self.save_button.clicked.connect(self.accept)
        self.save_button.setDefault(True)
        self.save_button.setAutoDefault(True)
        buttons.addWidget(self.save_button)
        layout.addRow(buttons)

        # Populate fields if editing.
        if self.app_data:
            self.name_input.setText(self.app_data.get('name', ''))
            # Show the full Exec line (command + arguments) so editing never
            # silently drops arguments. Performance wrappers are peeled off
            # and represented by the toggles instead.
            self.path_input.setText(
                self.app_data.get('exec_path') or self.app_data.get('path', ''))
            self.icon_input.setText(self.app_data.get('icon', ''))
            self.category_combo.setCurrentText(self.app_data.get('category', 'Utility'))
            self.wmclass_input.setText(
                self.app_data.get('startup_wm_class', '') or '')
            self.gamemode_toggle.setChecked(bool(self.app_data.get('gamemode')))
            self.prime_toggle.setChecked(bool(self.app_data.get('prime_gpu')))

        self.update_icon_preview()

    # -- drag & drop + live preview ------------------------------------------ #
    def _on_exec_dropped(self, path):
        """Exec drop: fill the path; pre-fill name/icon while they are empty."""
        if not self.name_input.text().strip():
            self.name_input.setText(suggest_app_name(path))
        if not self.icon_input.text().strip():
            detected = detect_icon_for_path(path, self.name_input.text())
            if detected:
                self.icon_input.setText(detected)
            else:
                self._request_appimage_icon(path)

    def _request_appimage_icon(self, path):
        """Ask for the AppImage's embedded icon while the field stays empty."""
        if not self.icon_input.text().strip() and request_appimage_icon(path):
            return True
        return False

    def _on_extracted_icon_ready(self, appimage_path, icon_path):
        """Background extraction finished: fill the field if still relevant."""
        if self.icon_input.text().strip():
            return
        if self.path_input.text().strip() != appimage_path:
            return
        self.icon_input.setText(icon_path)  # textChanged refreshes the preview

    def apply_prefill(self, prefill):
        """Fill the form from a dropped file (path / name / icon hints)."""
        if prefill.get('path'):
            self.path_input.setText(prefill['path'])
        if prefill.get('name'):
            self.name_input.setText(prefill['name'])
        if prefill.get('icon'):
            self.icon_input.setText(prefill['icon'])
        elif self.path_input.text().strip():
            self._request_appimage_icon(self.path_input.text().strip())
        self.update_icon_preview()

    def update_icon_preview(self):
        """Re-render the icon preview from the current field contents."""
        self.icon_preview.setPixmap(build_icon_pixmap({
            'icon': self.icon_input.text().strip(),
            'name': self.name_input.text().strip() or 'App',
        }, ICON_PREVIEW_SIZE))

    def _field_label(self, text):
        label = QLabel(text)
        label.setObjectName('fieldLabel')
        return label

    # -- fade-in ------------------------------------------------------------ #
    def showEvent(self, event):
        super().showEvent(event)
        duration = DIALOG_FADE_MS
        if duration <= 0:
            return
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b'opacity', self)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self._end_fade_in)
        self._fade_anim = anim
        anim.start()

    def _end_fade_in(self):
        self._fade_anim = None
        self.setGraphicsEffect(None)

    # -- browsing ----------------------------------------------------------- #
    def _browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 'Select Application',
            '', 'AppImages and Executables (*.AppImage *.app *.sh *.exe)',
        )
        if file_path:
            self.path_input.setText(file_path)
            self._request_appimage_icon(file_path)

    def _browse_icon(self):
        icon_path, _ = QFileDialog.getOpenFileName(
            self, 'Select Icon', '', 'PNG/SVG Images (*.png *.svg)',
        )
        if icon_path:
            self.icon_input.setText(icon_path)

    def get_data(self):
        """Get form data, preserving the source file path when editing."""
        return {
            'name': self.name_input.text().strip(),
            'path': self.path_input.text().strip(),
            'icon': self.icon_input.text().strip(),
            'category': self.category_combo.currentText(),
            'gamemode': self.gamemode_toggle.isChecked(),
            'prime_gpu': self.prime_toggle.isChecked(),
            'startup_wm_class': self.wmclass_input.text().strip(),
            'file_path': self.app_data.get('file_path') if self.app_data else None,
        }

    # -- window-class inspection --------------------------------------------- #
    def _inspect_window_class(self):
        """Ask Hyprland for the open windows and offer their classes."""
        program = _hyprctl_program()
        if not program:
            self._show_warning(
                'Inspect Window Class',
                'hyprctl was not found; this feature needs Hyprland.')
            return
        if (self._inspect_proc is not None
                and self._inspect_proc.state() != _PROCESS_NOT_RUNNING):
            return

        self._inspect_proc = QProcess(self)
        self._inspect_proc.finished.connect(self._on_inspect_finished)
        self._inspect_proc.errorOccurred.connect(self._on_inspect_error)
        self.inspect_button.setEnabled(False)
        self._inspect_proc.start(program, ['clients', '-j'])

    def _on_inspect_finished(self, exit_code, exit_status):
        self.inspect_button.setEnabled(True)
        process = self._inspect_proc
        if process is None:
            return
        output = bytes(process.readAllStandardOutput()).decode('utf-8', 'replace')
        error = bytes(process.readAllStandardError()).decode('utf-8', 'replace').strip()
        if exit_code != 0:
            self._show_warning(
                'Inspect Window Class',
                f'hyprctl exited with an error:\n{error or exit_code}')
            return
        self._present_window_classes(output)

    def _on_inspect_error(self, error):
        self.inspect_button.setEnabled(True)
        if error == _PROCESS_FAILED_TO_START:
            self._show_warning('Inspect Window Class', 'Could not run hyprctl.')

    def _present_window_classes(self, payload):
        """Offer the parsed window classes in a menu; fill the field on choice."""
        entries = _window_classes_from_clients(payload)
        if not entries:
            self._show_warning(
                'Inspect Window Class',
                'No open windows reported a window class.')
            return

        menu = QMenu(self)
        for wm_class, title in entries:
            label = wm_class
            if title:
                label = f'{wm_class}  —  {_elide(menu.fontMetrics(), title, 320)}'
            action = menu.addAction(label)
            action.setData(wm_class)

        chosen = _choose_from_menu(menu, self.inspect_button)
        if chosen is not None and chosen.data():
            self.wmclass_input.setText(str(chosen.data()))

    def _show_warning(self, title, text):
        """Warning popup (indirection so tests can silence dialogs)."""
        QMessageBox.warning(self, title, text)


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class OmarchyAppManager(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.apps = []
        self._cards = []
        self._columns = 0
        self.show_all_system = False
        self._active_category = 'All'
        self._theme_effect = None
        self._theme_anims = ()
        self._drop_overlay = None
        self._integration_menu = None
        self._first_run_bridge = _FirstRunBridge()
        self._first_run_bridge.finished.connect(self._refresh_integration_menu)
        self.setup_ui()
        self.load_apps()
        self._setup_theme_watcher()
        # First launch: register the launcher exactly once, in the background,
        # and refresh the toggles again the moment that finishes.
        schedule_first_run_integration(self._first_run_bridge)
        self._refresh_integration_menu()

    def setup_ui(self):
        self.setWindowTitle('Omarchy App Manager')
        self.resize(1180, 720)
        self.setMinimumSize(700, 480)

        icon_source = integration.app_icon_source()
        if icon_source.is_file():
            self.setWindowIcon(QIcon(str(icon_source)))

        self._apply_theme()

        central = QWidget()
        central.setObjectName('centralWidget')
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # Header row 1: sleek centered search bar.
        search_row = QHBoxLayout()
        search_row.setSpacing(0)
        self.search_bar = SearchBar()
        self.search_bar.setMaximumWidth(560)
        self.search_bar.textChanged.connect(self._filter_apps)
        search_row.addStretch(1)
        search_row.addWidget(self.search_bar, 1)
        search_row.addStretch(1)
        layout.addLayout(search_row)

        # Header row 2: counter left, view toggle + gear + add button right.
        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.counter_label = QLabel('Showing 0 Apps')
        self.counter_label.setObjectName('counterTag')
        self.counter_label.setAlignment(_ALIGN_CENTER)
        controls.addWidget(self.counter_label, 0, _ALIGN_VCENTER)
        controls.addStretch(1)

        self.view_toggle = SegmentedControl(['Custom Apps', 'All System Apps'])
        self.view_toggle.changed.connect(self._on_view_changed)
        controls.addWidget(self.view_toggle, 0, _ALIGN_VCENTER)

        self.integration_button = IconButton('gear')
        self.integration_button.setToolTip('System integration')
        self.integration_button.clicked.connect(self._show_integration_menu)
        controls.addWidget(self.integration_button, 0, _ALIGN_VCENTER)

        self.add_button = AnimatedButton('+ Add App', 'primary', height=44, padding=44)
        self.add_button.clicked.connect(self._show_add_dialog)
        controls.addWidget(self.add_button, 0, _ALIGN_VCENTER)

        layout.addLayout(controls)

        # Category filter pills above the grid.
        pills_row = QHBoxLayout()
        pills_row.setSpacing(0)
        self.category_pills = CategoryPills(CATEGORY_PILLS)
        self.category_pills.changed.connect(self._on_category_changed)
        pills_row.addWidget(self.category_pills, 0)
        pills_row.addStretch(1)
        layout.addLayout(pills_row)

        # Empty state (shown instead of the grid) with a dashed drop target.
        self.empty_state = EmptyState()
        self.empty_state.setVisible(False)
        #: Legacy alias kept for tests / integrations poking at the hint text.
        self.empty_label = self.empty_state.hint_label
        layout.addWidget(self.empty_state, 1)

        self.apps_scroll = QScrollArea()
        self.apps_scroll.setWidgetResizable(True)
        self.apps_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.apps_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.apps_container = QWidget()
        self.apps_container.setObjectName('appsContainer')
        self.apps_grid = QGridLayout(self.apps_container)
        self.apps_grid.setContentsMargins(0, 0, 8, 0)
        self.apps_grid.setHorizontalSpacing(16)
        self.apps_grid.setVerticalSpacing(16)
        self.apps_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.apps_scroll.setWidget(self.apps_container)
        self.apps_scroll.viewport().installEventFilter(self)
        layout.addWidget(self.apps_scroll, 1)

        self.setCentralWidget(central)

        # Dashboard drop target: files can be dropped anywhere on the window
        # (header, empty space) or on the card area itself.
        self.setAcceptDrops(True)
        self.apps_scroll.viewport().setAcceptDrops(True)
        self.apps_container.setAcceptDrops(True)
        self.apps_container.installEventFilter(self)

        self._drop_overlay = DropOverlay(central)
        self._drop_overlay.setGeometry(central.rect())

    def _apply_theme(self):
        # Match the live desktop theme (Omarchy / pywal / Qt / GTK), falling
        # back to Catppuccin Mocha when nothing is detected.
        load_theme()
        self._apply_theme_styles()

    def _apply_theme_styles(self):
        app = QApplication.instance()
        if app is None:
            return
        app.setStyleSheet(build_app_qss())
        app.setPalette(dark_palette())
        app.setFont(_base_font(10.5))

    # -- live theme reloading ------------------------------------------------ #
    def _setup_theme_watcher(self):
        """Watch the active theme file so disk changes hot-reload the palette."""
        self._theme_watcher = QFileSystemWatcher(self)
        self._theme_watcher.fileChanged.connect(self._on_theme_source_changed)
        self._theme_watcher.directoryChanged.connect(self._on_theme_source_changed)

        self._theme_debounce = QTimer(self)
        self._theme_debounce.setSingleShot(True)
        self._theme_debounce.setInterval(THEME_DEBOUNCE_MS)
        self._theme_debounce.timeout.connect(self._reload_theme)

        self._refresh_theme_watch()

    def _refresh_theme_watch(self, path=None):
        """(Re)point the watcher at the file behind the current theme.

        Theme files are frequently replaced wholesale (write-to-temp +
        rename), which drops inotify watches, so paths are re-registered after
        every event; parent directories are watched as well to catch those
        replacements and symlink swaps.
        """
        watcher = self._theme_watcher
        watched = watcher.files() + watcher.directories()
        if watched:
            watcher.removePaths(watched)

        if theme_reload_disabled():
            return
        target = path or last_theme_file()
        if not target:
            return
        for candidate in watch_paths(target):
            if os.path.exists(candidate):
                watcher.addPath(candidate)

    def _on_theme_source_changed(self, *_args):
        """Debounced handler for watcher signals (files are often written in chunks)."""
        if self._theme_debounce.isActive():
            self._theme_debounce.stop()
        self._theme_debounce.start()

    def _reload_theme(self):
        """Re-resolve the desktop theme and animate to it when it changed."""
        self._theme_debounce.stop()
        palette, source, path = resolve_theme()
        self._refresh_theme_watch(path)
        if source == styles.PALETTE_SOURCE and palette == styles.PALETTE:
            return
        if THEME_FADE_MS > 0:
            self._start_theme_transition(palette, source)
        else:
            self._apply_palette_and_styles(palette, source)

    def _apply_palette_and_styles(self, palette, source):
        """Swap in a resolved palette and repaint everything that cached colors."""
        styles.apply_palette(palette, source)
        self._apply_theme_styles()
        for card in self._cards:
            card.refresh_theme()
        self.search_bar.refresh_theme()
        self.empty_state.refresh_theme()
        for button in self.findChildren(AnimatedButton):
            button.refresh_theme()
        self.update()

    def _clear_card_filter_effects(self):
        """Drop card-level opacity effects before installing the window fade.

        Qt paints a subtree through at most one QGraphicsOpacityEffect;
        nesting a window fade over the cards' filter-fade effects corrupts the
        painter, so any in-flight filter fade is finalized first.
        """
        for card in self._cards:
            card.stop_filter_animation()

    def _start_theme_transition(self, palette, source):
        """Cross-fade the window: 1 -> 0, swap palette, 0 -> 1 (THEME_FADE_MS total)."""
        self._finish_theme_transition()
        container = self.centralWidget() or self

        effect = QGraphicsOpacityEffect()
        effect.setOpacity(1.0)
        container.setGraphicsEffect(effect)
        # Arm the flag first: the card cleanup below consults it to keep any
        # graphics effect (filter fade, hover elevation) out of the subtree.
        self._theme_effect = effect
        self._clear_card_filter_effects()

        half = max(1, int(THEME_FADE_MS) // 2)
        fade_out = QPropertyAnimation(effect, b'opacity', self)
        fade_out.setDuration(half)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InCubic)

        fade_in = QPropertyAnimation(effect, b'opacity', self)
        fade_in.setDuration(half)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._theme_anims = (fade_out, fade_in)

        def swap_palette_and_fade_in():
            # Recolour at the darkest point so the shift is never visible as a snap.
            self._apply_palette_and_styles(palette, source)
            fade_in.start()

        fade_out.finished.connect(swap_palette_and_fade_in)
        fade_in.finished.connect(self._finish_theme_transition)
        fade_out.start()

    def _finish_theme_transition(self, *_args):
        """Stop any running transition, remove the effect and free the animations."""
        if self._theme_effect is None:
            return
        self._theme_effect = None
        anims, self._theme_anims = self._theme_anims, ()
        for anim in anims:
            try:
                anim.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                anim.stop()
                anim.deleteLater()
            except RuntimeError:
                continue
        container = self.centralWidget() or self
        container.setGraphicsEffect(None)
        for card in self._cards:
            card.sync_hover_shadow()
        self.update()

    # -- shutdown ------------------------------------------------------------ #
    def closeEvent(self, event):
        """Quiesce every animation before teardown begins."""
        self._stop_all_animations()
        super().closeEvent(event)

    def _stop_all_animations(self):
        """Stop every animation rooted in this window.

        Closing mid-tick lets a running animation touch half-destroyed C++
        objects during teardown (PyQt escalates that to qFatal), so both the
        group-driven effects and the property animations are halted here.
        """
        self._finish_theme_transition()
        for group in self.findChildren(QSequentialAnimationGroup):
            try:
                group.stop()
            except RuntimeError:
                continue
        for animation in self.findChildren(QPropertyAnimation):
            try:
                animation.stop()
            except RuntimeError:
                continue
        for widget in self.findChildren(QWidget):
            stopper = getattr(widget, 'stop_animations', None)
            if callable(stopper):
                try:
                    stopper()
                except RuntimeError:
                    continue

    # -- drag & drop (quick app creation) ------------------------------------ #
    def dragEnterEvent(self, event):
        self._handle_drop_event(event)

    def dragMoveEvent(self, event):
        self._handle_drop_event(event)

    def dragLeaveEvent(self, event):
        self._set_drop_feedback(False)

    def dropEvent(self, event):
        self._handle_drop_event(event)

    def _first_drop_candidate(self, event):
        """First dropped file that qualifies as an application."""
        for path in _local_paths(event.mimeData()):
            if is_executable_drop(path):
                return path
        return None

    def _handle_drop_event(self, event):
        """Shared DragEnter / DragMove / Drop logic for all drop targets."""
        if event.type() == _DROP:
            candidate = self._first_drop_candidate(event)
            self._set_drop_feedback(False)
            if candidate is None:
                event.ignore()
                return
            event.acceptProposedAction()
            self._handle_dropped_file(candidate)
            return

        if self._first_drop_candidate(event) is not None:
            self._set_drop_feedback(True)
            event.acceptProposedAction()
        else:
            self._set_drop_feedback(False)
            event.ignore()

    def _set_drop_feedback(self, active):
        """Show/hide the dashed drop-target frame over the dashboard."""
        if self._drop_overlay is None:
            return
        if active:
            self._drop_overlay.setGeometry(self.centralWidget().rect())
            self._drop_overlay.show()
            self._drop_overlay.raise_()
        else:
            self._drop_overlay.hide()

    def _handle_dropped_file(self, path):
        """Quick-create flow: open Add prefilled from a dropped executable."""
        name = suggest_app_name(path)
        icon = detect_icon_for_path(path, name)
        self._show_add_dialog(prefill={'path': path, 'name': name, 'icon': icon})

    # -- responsive grid ----------------------------------------------------- #
    def resizeEvent(self, event):
        super().resizeEvent(event)
        central = self.centralWidget()
        if self._drop_overlay is not None and central is not None:
            self._drop_overlay.setGeometry(central.rect())

    def eventFilter(self, obj, event):
        # A collected window has its instance dict cleared before its C++
        # children are destroyed, and Qt >= 6.9 re-parents (and therefore
        # notifies) children during destruction.  Bail out while that runs.
        if 'apps_scroll' not in self.__dict__:
            return False
        try:
            if obj is self.apps_scroll.viewport() and event.type() == _RESIZE_EVENT:
                self._update_columns()
            elif obj is self.apps_scroll.viewport() or obj is self.apps_container:
                event_type = event.type()
                if event_type in _DROP_EVENT_TYPES:
                    if event_type == _DRAG_LEAVE:
                        self._set_drop_feedback(False)
                    else:
                        self._handle_drop_event(event)
                    return True
            return super().eventFilter(obj, event)
        except RuntimeError:
            # The watched widget or one of ours was deleted mid-teardown.
            return False

    def _grid_columns_for_width(self, width):
        spacing = self.apps_grid.horizontalSpacing()
        if width <= 0:
            return 1
        fit = (width + spacing) // (CARD_MIN_WIDTH + spacing)
        return max(1, min(MAX_GRID_COLUMNS, int(fit)))

    def _update_columns(self):
        viewport_width = self.apps_scroll.viewport().width()
        columns = self._grid_columns_for_width(viewport_width)
        if columns == self._columns:
            return
        self._columns = columns
        for column in range(MAX_GRID_COLUMNS):
            self.apps_grid.setColumnStretch(column, 1 if column < columns else 0)
        self._reflow_grid()

    def _reflow_grid(self):
        """Re-pack all visible cards into the responsive grid."""
        for card in self._cards:
            self.apps_grid.removeWidget(card)

        columns = max(1, self._columns)
        row = 0
        column = 0
        for card in self._cards:
            if card.isHidden():
                continue
            self.apps_grid.addWidget(card, row, column)
            column += 1
            if column >= columns:
                column = 0
                row += 1

    # -- loading ------------------------------------------------------------- #
    def load_apps(self):
        """Load installed applications for the active view."""
        self.apps = get_installed_apps(include_system=self.show_all_system)
        self._populate_apps()

    def _populate_apps(self):
        """Rebuild all cards from ``self.apps``."""
        for card in self._cards:
            card.stop_animations()
            self.apps_grid.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = []

        for app_data in reversed(self.apps):
            card = AppCard(
                app_data,
                on_edit=self._show_edit_dialog,
                on_delete=self._on_delete_app,
                on_launch=self._launch_app,
                on_open_dir=self._open_app_dir,
                parent=self.apps_container,
            )
            self._cards.append(card)
            card.start_appear_settle()

        self._update_columns()
        # Respect the current search text (no animation on a fresh load).
        self._filter_apps(self.search_bar.text(), animate=False)

    def _on_view_changed(self, index):
        show_all = index == 1
        if show_all == self.show_all_system:
            return
        self.show_all_system = show_all
        self.load_apps()

    def _update_empty_state(self, match_count):
        if self._cards and match_count > 0:
            self.empty_state.setVisible(False)
            self.apps_scroll.setVisible(True)
            return
        if not self._cards:
            if self.show_all_system:
                hint = 'No applications found'
            else:
                hint = ('No custom apps yet - click "+ Add App" or switch to '
                        'All System Apps')
        else:
            hint = 'No applications match your search'
        self.empty_state.set_hint(hint)
        self.apps_scroll.setVisible(False)
        self.empty_state.setVisible(True)

    def _update_counter(self, visible_count):
        if visible_count == 1:
            self.counter_label.setText('Showing 1 App')
        else:
            self.counter_label.setText(f'Showing {visible_count} Apps')

    # -- filtering ---------------------------------------------------------- #
    def _on_category_changed(self, category):
        """Re-filter the grid when a category pill is clicked (quick fade)."""
        self._active_category = category
        self._filter_apps(self.search_bar.text())

    def _card_matches(self, app_data, needle):
        """True when ``app_data`` passes both the search and pill filters."""
        if needle and needle not in app_data.get('name', '').lower():
            return False
        category = self._active_category
        if category == 'All':
            return True
        if category == 'System':
            return is_system_entry(app_data)
        return app_data.get('category') == PILL_CATEGORY_MAP.get(category)

    def _filter_apps(self, text, animate=True):
        """Filter cards by name + category pill, fading matches in/out."""
        # Card fades use QGraphicsOpacityEffect; nesting those under the
        # window-level theme-transition effect corrupts Qt's painter, so
        # filtering falls back to instant show/hide mid-transition.
        animate = animate and self._theme_effect is None
        needle = (text or '').strip().lower()
        match_count = 0

        for card in self._cards:
            is_match = self._card_matches(card.app_data, needle)
            if is_match:
                match_count += 1
                card.set_filter_visible(True, FILTER_FADE_IN_MS if animate else 0)
            else:
                card.set_filter_visible(
                    False,
                    FILTER_FADE_OUT_MS if animate else 0,
                    on_done=self._reflow_grid,
                )

        self._reflow_grid()
        self._update_empty_state(match_count)
        self._update_counter(match_count)

    # -- CRUD flows --------------------------------------------------------- #
    def _launch_app(self, app_data):
        """Start the application detached (performance wrappers applied)."""
        command_text = compose_exec_line(app_data)
        program, args_text = split_exec(command_text)
        if not program:
            self._show_warning('Launch', 'No command is configured for this application.')
            return
        if not command_is_available(command_text):
            if (os.path.basename(program) == GAMEMODE_WRAPPER
                    and shutil.which(GAMEMODE_WRAPPER) is None):
                self._show_warning(
                    'Launch',
                    'GameMode (gamemoderun) is not installed.\n'
                    'Install gamemode or turn off the GameMode toggle for '
                    'this app.')
            else:
                self._show_warning(
                    'Launch',
                    f"Executable not found:\n{first_exec_token(command_text)}")
            return
        try:
            args = [token for token in shlex.split(args_text)
                    if not _FIELD_CODE_RE.fullmatch(token)]
        except ValueError:
            args = []
        if not _start_detached(program, args):
            self._show_warning('Launch', f'Could not start:\n{program}')

    def _open_app_dir(self, app_data):
        """Open the directory containing this application's executable."""
        program, _args = split_exec(
            (app_data.get('path') or '').strip())
        candidate = Path(program) if program else None
        if candidate is None or not candidate.is_absolute():
            self._show_warning(
                'Open Directory',
                'This entry has no file location on disk.')
            return
        target = candidate if candidate.is_dir() else candidate.parent
        if not _open_in_file_manager(target):
            self._show_warning('Open Directory', f'Could not open:\n{target}')

    def _show_add_dialog(self, prefill=None):
        """Show add application dialog (optionally prefilled from a drop)."""
        dialog = CategoryDialog(self)
        if prefill:
            dialog.apply_prefill(prefill)
        if not dialog.exec():
            return
        app_data = dialog.get_data()
        if not self._validate_app_data(app_data):
            return
        try:
            # Auto chmod +x an AppImage/executable when it is saved.
            ensure_appimage_executable(first_exec_token(app_data['path']))
            create_desktop_file(app_data)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create application:\n{e}")
        finally:
            # Always refresh so the view matches what is actually on disk.
            self.load_apps()

    def _show_edit_dialog(self, app_data):
        """Show edit application dialog and persist changes in place."""
        dialog = CategoryDialog(self, app_data)
        if not dialog.exec():
            return
        updated_data = dialog.get_data()
        if not self._validate_app_data(updated_data):
            return
        try:
            # Write back to the *exact* file the entry was loaded from.
            target = updated_data.get('file_path') or app_data.get('file_path')
            update_desktop_file(updated_data, target)
            ensure_appimage_executable(first_exec_token(updated_data['path']))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update application:\n{e}")
        finally:
            self.load_apps()

    def _on_delete_app(self, app_data):
        """Handle app deletion."""
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete '{app_data['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_desktop_file(app_data)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete application:\n{e}")
        finally:
            self.load_apps()

    def _validate_app_data(self, app_data):
        """Validate application form data before writing it to disk."""
        if not app_data.get('name') or not app_data.get('path'):
            QMessageBox.warning(self, "Warning", "Please fill all required fields")
            return False

        if not command_is_available(app_data['path']):
            QMessageBox.warning(
                self, "Warning",
                f"Executable not found:\n{first_exec_token(app_data['path'])}",
            )
            return False

        return True

    # -- system integration ------------------------------------------------- #
    def _show_integration_menu(self):
        """Popup the system-integration checklist below the gear button."""
        self._refresh_integration_menu()
        menu = self._ensure_integration_menu()
        menu.popup(self.integration_button.mapToGlobal(
            self.integration_button.rect().bottomLeft()))

    def _ensure_integration_menu(self):
        if self._integration_menu is not None:
            return self._integration_menu
        menu = QMenu(self)
        self.desktop_action = menu.addAction('Install to Applications Menu')
        self.desktop_action.setCheckable(True)
        self.desktop_action.triggered.connect(self._toggle_desktop_entry)
        self.waybar_action = menu.addAction('Enable Waybar Shortcut')
        self.waybar_action.setCheckable(True)
        self.waybar_action.triggered.connect(self._toggle_waybar_module)
        self.omarchy_action = menu.addAction('Enable Omarchy Bar Widget')
        self.omarchy_action.setCheckable(True)
        self.omarchy_action.triggered.connect(self._toggle_omarchy_widget)
        menu.addSeparator()
        self.copy_waybar_action = menu.addAction('Copy Waybar Snippet')
        self.copy_waybar_action.triggered.connect(self._copy_waybar_snippet)
        self._integration_menu = menu
        return menu

    def _refresh_integration_menu(self):
        self._ensure_integration_menu()
        self.desktop_action.setChecked(integration.is_desktop_entry_installed())
        self.waybar_action.setChecked(integration.is_waybar_module_installed())
        self.omarchy_action.setChecked(integration.is_omarchy_widget_installed())

    def _toggle_desktop_entry(self, checked):
        try:
            if checked:
                integration.install_desktop_entry()
                self._show_info(
                    'Applications Menu',
                    'Omarchy App Manager was added to your applications menu.')
            else:
                integration.uninstall_desktop_entry()
                # An explicit uncheck is also an opt-out: make sure the
                # first-run logic never re-registers the launcher.
                integration.mark_first_run_complete()
        except integration.IntegrationError as exc:
            self.desktop_action.setChecked(not checked)
            self._show_warning('Applications Menu', str(exc))

    def _toggle_waybar_module(self, checked):
        try:
            if checked:
                target = integration.install_waybar_module()
                QApplication.clipboard().setText(integration.waybar_module_json())
                self._show_info(
                    'Waybar Shortcut',
                    f'Module written to {target} and copied to your clipboard.\n\n'
                    'Reference it as "custom/app-manager" in your Waybar '
                    'modules list.')
            else:
                integration.uninstall_waybar_module()
        except integration.IntegrationError as exc:
            self.waybar_action.setChecked(not checked)
            self._show_warning('Waybar Shortcut', str(exc))

    def _toggle_omarchy_widget(self, checked):
        try:
            if checked:
                integration.install_omarchy_widget()
                self._show_info(
                    'Omarchy Bar Widget',
                    'The App Manager widget was added to your top bar. '
                    'It may take a moment to appear.')
            else:
                integration.uninstall_omarchy_widget()
        except integration.IntegrationError as exc:
            self.omarchy_action.setChecked(not checked)
            self._show_warning('Omarchy Bar Widget', str(exc))

    def _copy_waybar_snippet(self):
        QApplication.clipboard().setText(integration.waybar_module_json())

    def _show_info(self, title, text):
        """Informational popup (indirection so tests can silence dialogs)."""
        QMessageBox.information(self, title, text)

    def _show_warning(self, title, text):
        """Warning popup (indirection so tests can silence dialogs)."""
        QMessageBox.warning(self, title, text)
