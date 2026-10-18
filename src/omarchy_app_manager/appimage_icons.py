"""
Omarchy App Manager - AppImage icon extraction.

AppImages embed a SquashFS filesystem containing the application's desktop
entry and icon artwork.  Their runtime answers ``--appimage-extract <pattern>``
by unpacking matching files into ``squashfs-root/`` (no FUSE required), which
we use to lift the best available icon out of the bundle and cache it under
``$XDG_CACHE_HOME/omarchy_app_manager/icons`` (override with
``OMARCHY_APPIMAGE_ICON_CACHE``, used by the test-suite).

Some runtimes (electron-builder builds such as LM Studio) answer the wildcard
patterns with a dangling root-level symlink — ``app.png ->
usr/share/icons/.../app.png`` — without unpacking the target; those targets
are re-requested explicitly by their exact path.  Bundled desktop files are
extracted as well so ``Icon=`` hints can pick among several icons.  Symlinks
are never followed outside ``squashfs-root``.

Everything here is plain stdlib and synchronous: the UI layer is responsible
for running :func:`extract_appimage_icon` off the main thread.  All failure
modes (not an AppImage, missing icon, extraction error or timeout) return
``None`` so callers can fall back to the initial-badge artwork.
"""

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

APPIMAGE_SUFFIX = '.appimage'
EXTRACT_TIMEOUT_SECONDS = 30.0
EXTRACTED_ROOT = 'squashfs-root'
ICON_SUFFIXES = ('.png', '.svg')

_ICON_KEY_RE = re.compile(r'^\s*Icon\s*=\s*(.+?)\s*$', re.IGNORECASE | re.MULTILINE)
_SIZE_DIR_RE = re.compile(r'^(\d+)x\d+$')
_SCALABLE_SCORE = 10_000


def is_appimage(path):
    """True when the path is named like an AppImage (``*.AppImage``)."""
    return str(path).lower().endswith(APPIMAGE_SUFFIX)


def get_icon_cache_dir():
    """Directory holding extracted AppImage icons."""
    override = os.environ.get('OMARCHY_APPIMAGE_ICON_CACHE')
    if override:
        return Path(override)
    base = os.environ.get('XDG_CACHE_HOME') or (Path.home() / '.cache')
    return Path(base) / 'omarchy_app_manager' / 'icons'


def cached_appimage_icon_path(appimage_path, cache_dir=None):
    """Return the already-cached icon for this AppImage build, or ``None``.

    Pure lookup: the AppImage is never executed.
    """
    if not is_appimage(appimage_path):
        return None
    try:
        stem, digest = _cache_key(appimage_path)
    except OSError:
        return None
    cached = _cached_icon(cache_dir if cache_dir is not None else get_icon_cache_dir(),
                          stem, digest)
    return str(cached) if cached is not None else None


def extract_appimage_icon(appimage_path, cache_dir=None, timeout=EXTRACT_TIMEOUT_SECONDS):
    """Extract the best icon from an AppImage into the icon cache.

    The AppImage runtime is asked to unpack its PNG artwork first; only when
    that yields nothing are SVGs considered.  The winner is copied into the
    cache (keyed by path + mtime + size, so rebuilding the AppImage produces
    a fresh entry) and every temporary artifact is removed.

    Returns the cached icon path, or ``None`` when the file is not an
    AppImage, cannot be inspected, or has no embedded icon — callers then
    fall back to the initial-badge artwork.
    """
    path = Path(appimage_path)
    if not is_appimage(path) or not path.is_file():
        return None
    try:
        stem, digest = _cache_key(path)
    except OSError:
        return None

    cache = Path(cache_dir) if cache_dir is not None else get_icon_cache_dir()
    cached = _cached_icon(cache, stem, digest)
    if cached is not None:
        return str(cached)

    data, suffix = _extract_best_icon(appimage_path=path, timeout=timeout)
    if data is None:
        return None

    try:
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / f'{stem}-{digest}{suffix}'
        partial = target.with_name(target.name + '.part')
        partial.write_bytes(data)
        os.replace(partial, target)
    except OSError:
        return None

    # Keep exactly one cached icon per AppImage build.
    for stale in cache.glob(f'{stem}-*'):
        if stale != target:
            try:
                stale.unlink()
            except OSError:
                pass
    return str(target)


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _safe_stem(name):
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', name).strip('-._')
    return stem or 'appimage'


def _cache_key(appimage_path):
    """``(stem, digest)`` tying a cache entry to this exact AppImage build."""
    path = Path(appimage_path).resolve()
    info = path.stat()
    fingerprint = f'{path}|{info.st_mtime_ns}|{info.st_size}'
    return _safe_stem(path.stem), hashlib.sha1(fingerprint.encode()).hexdigest()[:12]


def _cached_icon(cache_dir, stem, digest):
    for candidate in sorted(Path(cache_dir).glob(f'{stem}-{digest}.*')):
        if candidate.suffix.lower() in ICON_SUFFIXES and candidate.is_file():
            return candidate
    return None


def _extract_best_icon(appimage_path, timeout=EXTRACT_TIMEOUT_SECONDS):
    """Run ``--appimage-extract`` and return the best icon's bytes + suffix.

    Returns ``(None, None)`` when the AppImage yields no usable icon.  The
    icon is read before the temporary extraction directory is removed, so
    callers never see a path into the (deleted) scratch space.
    """
    workdir = Path(tempfile.mkdtemp(prefix='omarchy-appimage-extract-'))
    try:
        for pattern in ('*.png', '*.svg'):
            root = workdir / EXTRACTED_ROOT
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)
            # Best effort: the Icon= hints of bundled desktop entries then
            # let _choose_icon prefer the intended artwork.
            _run_extract(appimage_path, '*.desktop', workdir, timeout)
            if not _run_extract(appimage_path, pattern, workdir, timeout):
                continue
            _extract_symlink_targets(appimage_path, root, workdir, timeout)
            files = _icon_files(root)
            if not files:
                continue
            best = _choose_icon(root, files)
            if best is not None:
                return best.read_bytes(), best.suffix.lower()
        return None, None
    except OSError:
        return None, None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _extract_symlink_targets(appimage_path, root, workdir, timeout):
    """Fetch files that a runtime left behind only as dangling symlinks.

    Some runtimes answer ``*.png`` with a root-level symlink such as
    ``app.png -> usr/share/icons/.../app.png`` without unpacking the target.
    Re-requesting the exact target path extracts the real bytes.
    """
    for _ in range(2):
        targets = _dangling_icon_targets(root)
        if not targets:
            return
        for target in targets[:4]:
            _run_extract(appimage_path, str(target), workdir, timeout)


def _dangling_icon_targets(root):
    """Safe relative targets of dangling icon symlinks inside ``root``."""
    if not root.is_dir():
        return []
    targets = []
    seen = set()
    for entry in root.rglob('*'):
        if entry.suffix.lower() not in ICON_SUFFIXES or not entry.is_symlink():
            continue
        if entry.is_file():
            continue
        try:
            raw = os.readlink(entry)
        except OSError:
            continue
        target = PurePosixPath(raw)
        if target.is_absolute() or '..' in target.parts:
            continue
        key = str(target)
        if key in seen or (root / target).exists():
            continue
        seen.add(key)
        targets.append(target)
    return targets


def _is_safe_icon(root, candidate):
    """True for an icon-suffixed file whose real path stays inside ``root``."""
    if candidate.suffix.lower() not in ICON_SUFFIXES or not candidate.is_file():
        return False
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _run_extract(appimage_path, pattern, workdir, timeout):
    """Execute ``AppImage --appimage-extract <pattern>``; True on success."""
    if not os.access(appimage_path, os.X_OK):
        try:
            mode = os.stat(appimage_path).st_mode
            os.chmod(appimage_path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            return False
    try:
        completed = subprocess.run(
            [str(appimage_path), '--appimage-extract', pattern],
            cwd=str(workdir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _icon_files(root):
    if not root.is_dir():
        return []
    return [
        candidate
        for candidate in root.rglob('*')
        if _is_safe_icon(root, candidate)
    ]


def _choose_icon(root, files):
    """Best icon among the extracted files (desktop-entry hint first)."""
    hinted = [
        candidate
        for candidate in _icons_from_desktop_entries(root, files)
        if _is_safe_icon(root, candidate)
    ]
    pool = hinted or files
    if not pool:
        return None
    return max(pool, key=lambda candidate: _icon_score(root, candidate))


def _icons_from_desktop_entries(root, files):
    """Icon files referenced by ``Icon=`` keys of bundled desktop entries."""
    matches = []
    for entry in sorted(root.glob('*.desktop')):
        try:
            text = entry.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for value in _ICON_KEY_RE.findall(text):
            matches.extend(_resolve_icon_value(root, value, files))
    return matches


def _resolve_icon_value(root, value, files):
    """Map a desktop ``Icon=`` value onto extracted icon files."""
    value = value.strip().strip('"').strip("'")
    if not value:
        return []
    wanted = PurePosixPath(value.lstrip('/'))
    if '..' in wanted.parts:
        return []

    resolved = []
    direct = root / wanted
    if direct.is_file() and direct.suffix.lower() in ICON_SUFFIXES:
        resolved.append(direct)
    for suffix in ICON_SUFFIXES:
        with_ext = root / f'{wanted}{suffix}'
        if with_ext.is_file():
            resolved.append(with_ext)

    # ``Icon=foo`` usually lives in a size directory
    # (hicolor/256x256/apps/foo.png), so fall back to a stem match.
    if wanted.suffix == '' or wanted.suffix.lower() in ICON_SUFFIXES:
        exact = [f for f in files if f.stem == wanted.stem]
        if not exact:
            exact = [f for f in files if f.stem.lower() == wanted.stem.lower()]
        resolved.extend(exact)

    unique = []
    seen = set()
    for candidate in resolved:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _icon_score(root, candidate):
    """Rank icons: bigger declared size first, then ``apps/``, then bytes."""
    bucket = 0
    parts = [part.lower() for part in candidate.relative_to(root).parts]
    for part in parts:
        match = _SIZE_DIR_RE.match(part)
        if match:
            bucket = max(bucket, int(match.group(1)))
        elif part == 'scalable':
            bucket = max(bucket, _SCALABLE_SCORE)
    in_apps_dir = 1 if 'apps' in parts else 0
    try:
        size = candidate.stat().st_size
    except OSError:
        size = 0
    return (bucket, in_apps_dir, size)
