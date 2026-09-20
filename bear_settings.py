"""Persistent settings and selection helpers for Bear Audio Limiter."""

from copy import deepcopy

PROTECTION_SETTING_KEYS = (
    "THRESHOLD",
    "SAFE_LEVEL",
    "MUTE_DURATION",
    "USE_MUTE",
    "LOWER_PERCENT",
)

DEFAULT_CONFIG = {
    "THRESHOLD": 0.20,
    "SAFE_LEVEL": 0.15,
    "MUTE_DURATION": 1.5,
    "USE_MUTE": False,
    "LOWER_PERCENT": 0.10,
    "LIMIT_ONLY_SELECTED": False,
    "SELECTED_APPS": [],
    "APP_SETTINGS": {},
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


def normalize_app_settings(app_settings):
    """Return only explicit per-app overrides for known protection settings."""
    normalized = {}
    if not isinstance(app_settings, dict):
        return normalized

    for app_name, overrides in app_settings.items():
        if not isinstance(app_name, str) or not app_name.strip() or not isinstance(overrides, dict):
            continue
        clean_overrides = {
            key: deepcopy(overrides[key])
            for key in PROTECTION_SETTING_KEYS
            if key in overrides
        }
        if clean_overrides:
            normalized[app_name] = clean_overrides
    return normalized


def normalize_config(saved_config):
    """Merge saved values with defaults so older config files keep working."""
    normalized = deepcopy(DEFAULT_CONFIG)
    if isinstance(saved_config, dict):
        normalized.update({key: deepcopy(saved_config[key]) for key in DEFAULT_CONFIG if key in saved_config})
    normalized["APP_SETTINGS"] = normalize_app_settings(normalized.get("APP_SETTINGS", {}))
    return normalized


def default_selected_apps(shown_apps, config):
    """Return the selected apps to show when selective mode starts empty."""
    saved = list(config.get("SELECTED_APPS", []))
    if saved:
        return saved
    return list(shown_apps)


def should_limit_app(app_name, config):
    """Return whether an audio session is included by the saved app filter."""
    if not config.get("LIMIT_ONLY_SELECTED", False):
        return True
    selected = {name.casefold() for name in config.get("SELECTED_APPS", [])}
    return not selected or app_name.casefold() in selected


def find_app_settings_key(app_name, config):
    """Find a saved per-app settings key case-insensitively while preserving JSON names."""
    app_settings = config.get("APP_SETTINGS", {})
    if not isinstance(app_settings, dict):
        return None
    folded_name = app_name.casefold()
    for saved_name in app_settings:
        if isinstance(saved_name, str) and saved_name.casefold() == folded_name:
            return saved_name
    return None


def get_app_overrides(app_name, config):
    """Return explicit local overrides for an app, or an empty dict when it uses global defaults."""
    saved_key = find_app_settings_key(app_name, config)
    if saved_key is None:
        return {}
    return deepcopy(config.get("APP_SETTINGS", {}).get(saved_key, {}))


def effective_app_config(app_name, config):
    """Return global protection settings plus any explicit per-app local overrides."""
    effective = {key: deepcopy(config[key]) for key in PROTECTION_SETTING_KEYS}
    effective.update(get_app_overrides(app_name, config))
    return effective


def save_app_overrides(app_name, overrides, config):
    """Store only configured local app overrides; remove the app when no overrides remain."""
    app_settings = config.setdefault("APP_SETTINGS", {})
    saved_key = find_app_settings_key(app_name, config)
    if saved_key and saved_key != app_name:
        app_settings.pop(saved_key, None)

    clean_overrides = normalize_app_settings({app_name: overrides}).get(app_name, {})
    if clean_overrides:
        app_settings[app_name] = clean_overrides
    else:
        app_settings.pop(app_name, None)
    config["APP_SETTINGS"] = normalize_app_settings(app_settings)


def app_uses_local_settings(app_name, config):
    """Return True when an app has at least one explicit local override."""
    return bool(get_app_overrides(app_name, config))


def get_theme(dark_mode):
    """Return a copy of the requested UI color palette."""
    return (DARK_THEME if dark_mode else LIGHT_THEME).copy()


def app_status_icons(is_running, has_local_settings=False):
    """Return compact status icons for a settings row."""
    running_icon = "" if is_running else "💤"
    settings_icon = "🔧" if has_local_settings else "🌐"
    return f"{running_icon} {settings_icon}".strip()


def app_checkbox_text(app_name, checked, is_running, has_local_settings=False):
    """Format the clickable checklist text without tiny inline status icons."""
    box = "☒" if checked else "☐"
    return f"{box}  {app_name}"
