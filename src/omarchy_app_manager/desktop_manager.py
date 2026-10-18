"""
OmaApp Manager - Desktop Entry backend.

Reads and writes freedesktop.org ``.desktop`` files in
``~/.local/share/applications/`` (overridable via the ``OMARCHY_APPS_DIR``
environment variable, which is used by the test-suite).

Key behaviours:
  * ``configparser`` is configured with ``optionxform = str`` so keys such as
    ``Name``, ``Exec``, ``Icon`` and ``Categories`` keep their exact case, and
    with ``interpolation=None`` so values containing ``%`` (e.g. ``Exec=foo %U``)
    survive a read/write round-trip.
  * Every file is read/written through the ``[Desktop Entry]`` section.
  * Updates modify the *exact* file that was opened, preserving any extra keys
    instead of regenerating (and thereby orphaning) the entry.
"""

import configparser
import os
import shlex
import shutil
import stat
from pathlib import Path

DESKTOP_SECTION = "Desktop Entry"

# Single source of truth for category <-> freedesktop Categories mapping
CATEGORY_MAP = {
    'Game': 'Game;Application;',
    'AudioVideo': 'AudioVideo;Application;',
    'Utility': 'Utility;Application;',
    'Development': 'Development;Application;',
}


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def get_applications_dir():
    """Return the directory holding user .desktop files.

    Honours ``OMARCHY_APPS_DIR`` so tests can use a sandbox.
    """
    override = os.environ.get("OMARCHY_APPS_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local/share/applications"


def _slug(name):
    """Turn a display name into a safe .desktop filename stem."""
    stem = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in (name or ""))
    stem = stem.replace(" ", "_").lower().strip("_")
    return stem or "application"


# --------------------------------------------------------------------------- #
# Category helpers
# --------------------------------------------------------------------------- #
def parse_category(categories_str):
    """Map a raw Categories= value back to a friendly category name."""
    parts = [p.strip() for p in (categories_str or "").split(';') if p.strip()]
    for friendly in CATEGORY_MAP:
        if friendly in parts:
            return friendly
    return 'Utility'


def split_exec(exec_line):
    """Split an Exec= line into ``(command, args)``.

    Tolerates the two styles found in the wild:
      * correctly quoted paths with spaces:  ``"/my path/app" --flag``
      * legacy unquoted paths with spaces:   ``/my path/app --flag``
        (invalid per the freedesktop spec, but produced by older versions of
        this tool).  We resolve those by matching the longest existing path.
    """
    line = (exec_line or "").strip()
    if not line:
        return "", ""

    # 1. Properly quoted command.
    if line.startswith('"'):
        end_quote = line.find('"', 1)
        if end_quote != -1:
            return line[1:end_quote], line[end_quote + 1:].strip()
        return line[1:], ""

    # 2. The whole line is itself an existing path (no args).
    if "/" in line and os.path.exists(line):
        return line, ""

    tokens = line.split()
    if "/" in tokens[0]:
        # 3. Unquoted path with spaces (optionally followed by args): find the
        #    longest leading token sequence that names an existing file.
        for i in range(len(tokens), 0, -1):
            candidate = " ".join(tokens[:i])
            if os.path.exists(candidate):
                return candidate, " ".join(tokens[i:])
    # 4. Plain command (optionally followed by args).
    return tokens[0], " ".join(tokens[1:])


def first_exec_token(exec_line):
    """Return just the executable portion of an Exec= line."""
    return split_exec(exec_line)[0]


def quote_command(command):
    """Wrap a command containing spaces in double quotes (spec compliance)."""
    command = (command or "").strip()
    if " " in command and not (command.startswith('"') and command.endswith('"')):
        return f'"{command}"'
    return command


def normalize_exec(exec_line):
    """Rewrite an Exec line so any spaced path is correctly quoted."""
    command, args = split_exec(exec_line)
    if not command:
        return ""
    normalized = quote_command(command)
    return f"{normalized} {args}".strip() if args else normalized


# --------------------------------------------------------------------------- #
# Performance wrappers (GameMode / NVIDIA PRIME render offload)
# --------------------------------------------------------------------------- #
#: Boolean markers written alongside ``Exec`` so the wrappers survive a
#: parse -> edit -> write round-trip even if the launch line is hand-edited.
PERF_GAMEMODE_KEY = "X-OmarchyAppManager-GameMode"
PERF_PRIME_KEY = "X-OmarchyAppManager-PrimeRenderOffload"

GAMEMODE_WRAPPER = "gamemoderun"
PRIME_ENV_VALUE = "__NV_PRIME_RENDER_OFFLOAD=1"
PRIME_GLX_VALUE = "__GLX_VENDOR_LIBRARY_NAME=nvidia"
_PRIME_ENV_TOKENS = frozenset({PRIME_ENV_VALUE, PRIME_GLX_VALUE})


def wrap_exec_command(exec_line, gamemode=False, prime_render_offload=False):
    """Compose an Exec line with the requested performance wrappers.

    ``gamemoderun`` stays outermost so the environment variables are applied
    to the wrapped application::

        gamemoderun env __NV_PRIME_RENDER_OFFLOAD=1 \
            __GLX_VENDOR_LIBRARY_NAME=nvidia <command>
    """
    line = normalize_exec(exec_line)
    if not line:
        return ""
    if prime_render_offload:
        line = f"env {PRIME_ENV_VALUE} {PRIME_GLX_VALUE} {line}"
    if gamemode:
        line = f"{GAMEMODE_WRAPPER} {line}"
    return line


def _split_leading_token(line):
    """Return ``(first_token, rest)`` without tokenising the remainder."""
    parts = line.split(None, 1)
    if not parts:
        return "", ""
    return parts[0], (parts[1] if len(parts) > 1 else "")


def unwrap_exec_command(exec_line):
    """Peel known performance wrappers off an Exec line.

    Returns ``(inner_exec, gamemode, prime_render_offload)``.  Prefixes are
    recognised in any order.  The prime ``env`` prefix is only peeled when
    *both* NV variables lead the environment; any foreign ``VAR=value``
    entry leaves the line completely untouched.
    """
    line = (exec_line or "").strip()
    gamemode = False
    prime = False

    while line:
        token, rest = _split_leading_token(line)
        if os.path.basename(token) == GAMEMODE_WRAPPER:
            gamemode = True
            line = rest
            continue
        if os.path.basename(token) != "env":
            break
        # Walk only the leading VAR=value entries of the env prefix.
        found = set()
        remaining = rest
        while remaining:
            lead, tail = _split_leading_token(remaining)
            if lead in _PRIME_ENV_TOKENS:
                found.add(lead)
                remaining = tail
                continue
            if "=" in lead and not lead.startswith(('"', "'")):
                found = set()  # foreign variable: refuse to peel anything
            break
        if found == _PRIME_ENV_TOKENS and remaining:
            prime = True
            line = remaining
            continue
        break

    return line, gamemode, prime


def compose_exec_line(app_data):
    """Exec line to launch/write for ``app_data`` (wrapper flags applied)."""
    base = (app_data.get("exec_path") or app_data.get("path") or "").strip()
    return wrap_exec_command(
        base,
        gamemode=bool(app_data.get("gamemode")),
        prime_render_offload=bool(app_data.get("prime_gpu")),
    )


# --------------------------------------------------------------------------- #
# System / helper entry detection
# --------------------------------------------------------------------------- #
# Wine extension shims and generic interpreter wrappers clutter the app list;
# they are hidden behind the "All System Apps" toggle.
SYSTEM_ENTRY_NAMES = {
    'wscript', 'rundll32', 'winhlp32', 'hh',
    'python', 'python2', 'python3',
}
SYSTEM_EXEC_COMMANDS = SYSTEM_ENTRY_NAMES


def _effective_command(exec_line):
    """The command that actually runs, skipping ``env`` and ``VAR=value`` prefixes."""
    command = first_exec_token(exec_line)
    if not command:
        return ""
    if os.path.basename(command) != 'env':
        return command
    _, args = split_exec(exec_line)
    try:
        tokens = shlex.split(args)
    except ValueError:
        tokens = args.split()
    for token in tokens:
        if '=' not in token:
            return token
    return command


def is_system_entry(app_info):
    """True for NoDisplay entries and Wine/Python helper shims.

    Detects three signals: ``NoDisplay=true``, a helper display name
    (wscript, rundll32, winhlp32, hh, Python...), or a helper executable
    (looked up past any ``env``/``VAR=value`` prefix).
    """
    if app_info.get('no_display'):
        return True
    name = (app_info.get('name') or '').strip().lower()
    if name in SYSTEM_ENTRY_NAMES:
        return True
    command = _effective_command(app_info.get('exec_path') or app_info.get('path') or '')
    return os.path.basename(command).lower() in SYSTEM_EXEC_COMMANDS


# --------------------------------------------------------------------------- #
# configparser plumbing
# --------------------------------------------------------------------------- #
def _read_config(desktop_file):
    """Parse a .desktop file, preserving key case and literal ``%`` values."""
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    cfg.optionxform = str  # keep exact key case
    try:
        with open(desktop_file, 'r', encoding='utf-8') as fh:
            cfg.read_file(fh)
    except (configparser.Error, UnicodeDecodeError, OSError):
        # Malformed file: start from an empty config so callers get defaults.
        cfg = configparser.ConfigParser(interpolation=None, strict=False)
        cfg.optionxform = str
    return cfg


def _write_config(cfg, desktop_file):
    """Write a ConfigParser to disk with no spaces around ``=`` (per spec)."""
    desktop_file = Path(desktop_file)
    desktop_file.parent.mkdir(parents=True, exist_ok=True)
    with open(desktop_file, 'w', encoding='utf-8') as fh:
        cfg.write(fh, space_around_delimiters=False)


def _ensure_section(cfg):
    if not cfg.has_section(DESKTOP_SECTION):
        cfg.add_section(DESKTOP_SECTION)
    return cfg[DESKTOP_SECTION]


def _apply_defaults(section):
    """Fill in required/typical keys if they are missing."""
    defaults = {
        "Version": "1.0",
        "Type": "Application",
        "Terminal": "false",
        "StartupNotify": "true",
    }
    for key, value in defaults.items():
        if key not in section:
            section[key] = value


def _key_is_true(value):
    """True for freedesktop-style boolean strings (``true``/``1``/``yes``)."""
    return (value or "").strip().lower() in ("true", "1", "yes")


def _apply_perf_keys(section, app_data):
    """Persist performance-wrapper flags and StartupWMClass on ``section``.

    Only keys explicitly present in ``app_data`` are touched, so foreign
    keys set by other tools survive; the form always supplies them all.
    Disabled wrappers are removed (not written as ``false``) so files stay
    clean; a blank window class is likewise removed.
    """
    if "gamemode" in app_data:
        if app_data.get("gamemode"):
            section[PERF_GAMEMODE_KEY] = "true"
        else:
            section.pop(PERF_GAMEMODE_KEY, None)

    if "prime_gpu" in app_data:
        if app_data.get("prime_gpu"):
            section[PERF_PRIME_KEY] = "true"
        else:
            section.pop(PERF_PRIME_KEY, None)

    if "startup_wm_class" in app_data:
        wm_class = (app_data.get("startup_wm_class") or "").strip()
        if wm_class:
            section["StartupWMClass"] = wm_class
        else:
            section.pop("StartupWMClass", None)


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
def parse_desktop_file(desktop_file):
    """Parse a single .desktop file into a dict, or None if unreadable."""
    desktop_file = Path(desktop_file)
    if not desktop_file.exists():
        return None

    cfg = _read_config(desktop_file)
    if not cfg.has_section(DESKTOP_SECTION):
        return None

    section = cfg[DESKTOP_SECTION]
    raw_exec = section.get("Exec", "")
    inner_exec, wrapped_gamemode, wrapped_prime = unwrap_exec_command(raw_exec)
    no_display = _key_is_true(section.get("NoDisplay", ""))

    return {
        "name": section.get("Name", ""),
        "path": first_exec_token(inner_exec),
        "exec_path": inner_exec,  # unwrapped: wrappers live in the flags below
        "raw_exec": raw_exec,
        "icon": section.get("Icon", ""),
        "category": parse_category(section.get("Categories", "")),
        "categories": section.get("Categories", ""),
        "type": section.get("Type", "Application"),
        "no_display": no_display,
        "gamemode": (wrapped_gamemode
                     or _key_is_true(section.get(PERF_GAMEMODE_KEY, ""))),
        "prime_gpu": (wrapped_prime
                      or _key_is_true(section.get(PERF_PRIME_KEY, ""))),
        "startup_wm_class": section.get("StartupWMClass", "").strip(),
        "file_path": desktop_file,
        "exists": True,
    }


def get_installed_apps(include_system=True):
    """Scan the applications directory and return parsed entries.

    With ``include_system=False``, NoDisplay entries and Wine/Python helper
    shims are filtered out (see :func:`is_system_entry`).
    """
    apps_dir = get_applications_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)

    installed_apps = []
    for desktop_file in sorted(apps_dir.glob("*.desktop")):
        try:
            app_info = parse_desktop_file(desktop_file)
            if not app_info:
                continue
            if not include_system and is_system_entry(app_info):
                continue
            installed_apps.append(app_info)
        except Exception as e:  # never let one bad file break the scan
            print(f"Error parsing {desktop_file}: {e}")

    return installed_apps


# --------------------------------------------------------------------------- #
# Write
# --------------------------------------------------------------------------- #
def _target_path_for(app_data):
    """Determine the .desktop path for a new/updated entry."""
    explicit = app_data.get("file_path")
    if explicit:
        return Path(explicit)
    return get_applications_dir() / f"{_slug(app_data.get('name', ''))}.desktop"


def create_desktop_file(app_data):
    """Create a new .desktop file, returning its path.

    If a file with the same slug already exists a numeric suffix is added so an
    unrelated existing entry is never silently overwritten.
    """
    apps_dir = get_applications_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)

    desktop_file = apps_dir / f"{_slug(app_data.get('name', ''))}.desktop"
    counter = 1
    while desktop_file.exists():
        desktop_file = apps_dir / f"{_slug(app_data.get('name', ''))}_{counter}.desktop"
        counter += 1

    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    cfg.optionxform = str
    section = _ensure_section(cfg)
    section["Name"] = app_data.get("name", "")
    section["Exec"] = compose_exec_line(app_data)
    section["Icon"] = app_data.get("icon", "")
    section["Categories"] = CATEGORY_MAP.get(app_data.get("category", "Utility"),
                                             "Utility;Application;")
    _apply_perf_keys(section, app_data)
    _apply_defaults(section)

    _write_config(cfg, desktop_file)
    make_executable(desktop_file)
    return desktop_file


def update_desktop_file(app_data, desktop_file=None):
    """Update an existing .desktop file **in place**.

    ``desktop_file`` should be the path returned by the parser
    (``app_data['file_path']``).  Unknown keys already present in the file are
    preserved.  Returns the path that was written.
    """
    if desktop_file is None:
        desktop_file = app_data.get("file_path") or _target_path_for(app_data)
    desktop_file = Path(desktop_file)

    if desktop_file.exists():
        cfg = _read_config(desktop_file)
        section = _ensure_section(cfg)
    else:
        cfg = configparser.ConfigParser(interpolation=None, strict=False)
        cfg.optionxform = str
        section = _ensure_section(cfg)

    section["Name"] = app_data.get("name", "")
    section["Exec"] = compose_exec_line(app_data)
    section["Icon"] = app_data.get("icon", "")
    section["Categories"] = CATEGORY_MAP.get(app_data.get("category", "Utility"),
                                             "Utility;Application;")
    _apply_perf_keys(section, app_data)
    _apply_defaults(section)

    _write_config(cfg, desktop_file)
    make_executable(desktop_file)
    return desktop_file


def delete_desktop_file(app_data):
    """Delete the .desktop file for ``app_data`` from disk.

    Uses the exact ``file_path`` recorded when the entry was scanned, falling
    back to the slug-derived name.  Raises FileNotFoundError if nothing matched.
    """
    candidates = []
    explicit = app_data.get("file_path")
    if explicit:
        candidates.append(Path(explicit))
    name = app_data.get("name")
    if name:
        candidates.append(get_applications_dir() / f"{_slug(name)}.desktop")

    for candidate in candidates:
        if candidate.exists():
            candidate.unlink()
            return candidate

    raise FileNotFoundError(
        f"No .desktop file found for {app_data.get('name', '<unknown>')!r}"
    )


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
def make_executable(file_path):
    """chmod +x a file (adds the executable bit for all classes)."""
    path = Path(file_path)
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def ensure_appimage_executable(appimage_path):
    """Ensure an AppImage/executable has the +x bit. Returns True if changed."""
    if not appimage_path:
        return False
    path = Path(appimage_path)
    if not path.exists() or not path.is_file():
        return False
    st = os.stat(path)
    if not (st.st_mode & stat.S_IXUSR):
        os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return True
    return False


def command_is_available(exec_line):
    """True if the executable referenced by an Exec= line can be found.

    Absolute/relative paths are checked with ``os.path.exists``; bare command
    names are resolved against ``$PATH``.
    """
    command = first_exec_token(exec_line)
    if not command:
        return False
    if "/" in command:
        return os.path.exists(command)
    return shutil.which(command) is not None
