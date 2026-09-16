"""Persistent settings and selection helpers for Bear Audio Limiter."""

from copy import deepcopy

DEFAULT_CONFIG = {
    "THRESHOLD": 0.20,
    "SAFE_LEVEL": 0.15,
    "MUTE_DURATION": 1.5,
    "USE_MUTE": False,
    "LOWER_PERCENT": 0.10,
    "LIMIT_ONLY_SELECTED": False,
    "SELECTED_APPS": [],
    "DARK_MODE": False,
}

LIGHT_THEME = {
    "bg": "#f4f6f8",
    "fg": "#1f2933",
    "muted_fg": "#52606d",
    "surface": "#ffffff",
    "entry_bg": "#ffffff",
    "accent": "#2e7d32",
    "select_bg": "#d9eadb",
}

DARK_THEME = {
    "bg": "#12161c",
    "fg": "#f2f4f8",
    "muted_fg": "#aeb8c4",
    "surface": "#1d242d",
    "entry_bg": "#28313d",
    "accent": "#66bb6a",
    "select_bg": "#34495e",
}


def normalize_config(saved_config):
    """Merge saved values with defaults so older config files keep working."""
    normalized = deepcopy(DEFAULT_CONFIG)
    if isinstance(saved_config, dict):
        normalized.update({key: deepcopy(saved_config[key]) for key in DEFAULT_CONFIG if key in saved_config})
    return normalized


def should_limit_app(app_name, config):
    """Return whether an audio session is included by the saved app filter."""
    if not config.get("LIMIT_ONLY_SELECTED", False):
        return True
    selected = {name.casefold() for name in config.get("SELECTED_APPS", [])}
    return app_name.casefold() in selected


def get_theme(dark_mode):
    """Return a copy of the requested UI color palette."""
    return (DARK_THEME if dark_mode else LIGHT_THEME).copy()


def app_checkbox_text(app_name, checked, is_running):
    """Format a clickable checklist row with a visible boxed X."""
    box = "☒" if checked else "☐"
    saved_suffix = "" if is_running else "  (saved)"
    return f"{box}  {app_name}{saved_suffix}"
