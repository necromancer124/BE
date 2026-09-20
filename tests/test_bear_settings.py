from bear_settings import (
    DEFAULT_CONFIG,
    app_checkbox_text,
    app_status_icons,
    app_uses_local_settings,
    default_selected_apps,
    effective_app_config,
    get_app_overrides,
    get_theme,
    normalize_config,
    save_app_overrides,
    should_limit_app,
)


def test_normalize_config_migrates_existing_config_with_new_defaults():
    old_config = {"THRESHOLD": 0.35, "USE_MUTE": True}

    migrated = normalize_config(old_config)

    assert migrated["THRESHOLD"] == 0.35
    assert migrated["USE_MUTE"] is True
    assert migrated["LIMIT_ONLY_SELECTED"] is False
    assert migrated["SELECTED_APPS"] == []
    assert migrated["APP_SETTINGS"] == {}
    assert migrated["DARK_MODE"] is False
    assert set(migrated) == set(DEFAULT_CONFIG)


def test_normalize_config_does_not_share_the_default_app_list():
    first = normalize_config({})
    second = normalize_config({})
    saved = {"SELECTED_APPS": ["game.exe"]}
    migrated_saved = normalize_config(saved)

    first["SELECTED_APPS"].append("music.exe")
    migrated_saved["SELECTED_APPS"].append("voice.exe")

    assert second["SELECTED_APPS"] == []
    assert DEFAULT_CONFIG["SELECTED_APPS"] == []
    assert saved["SELECTED_APPS"] == ["game.exe"]


def test_should_limit_every_app_when_selection_mode_is_disabled():
    config = normalize_config({"LIMIT_ONLY_SELECTED": False, "SELECTED_APPS": ["music.exe"]})

    assert should_limit_app("game.exe", config) is True


def test_should_limit_only_saved_apps_when_selection_mode_is_enabled():
    config = normalize_config({"LIMIT_ONLY_SELECTED": True, "SELECTED_APPS": ["Music.EXE"]})

    assert should_limit_app("music.exe", config) is True
    assert should_limit_app("game.exe", config) is False


def test_empty_selected_apps_means_all_apps_are_checked_by_default():
    config = normalize_config({"LIMIT_ONLY_SELECTED": True, "SELECTED_APPS": []})

    assert default_selected_apps(["game.exe", "music.exe"], config) == ["game.exe", "music.exe"]
    assert should_limit_app("new.exe", config) is True


def test_effective_app_config_uses_global_defaults_without_local_overrides():
    config = normalize_config({"THRESHOLD": 0.25, "USE_MUTE": False})

    effective = effective_app_config("game.exe", config)

    assert effective["THRESHOLD"] == 0.25
    assert effective["USE_MUTE"] is False


def test_effective_app_config_applies_only_configured_local_overrides():
    config = normalize_config({
        "THRESHOLD": 0.25,
        "SAFE_LEVEL": 0.15,
        "APP_SETTINGS": {"Game.EXE": {"THRESHOLD": 0.4, "UNKNOWN": "ignored"}},
    })

    effective = effective_app_config("game.exe", config)

    assert effective["THRESHOLD"] == 0.4
    assert effective["SAFE_LEVEL"] == 0.15
    assert "UNKNOWN" not in get_app_overrides("game.exe", config)


def test_save_app_overrides_saves_only_local_values_and_removes_empty_overrides():
    config = normalize_config({})

    save_app_overrides("game.exe", {"THRESHOLD": 0.4}, config)
    assert config["APP_SETTINGS"] == {"game.exe": {"THRESHOLD": 0.4}}
    assert app_uses_local_settings("GAME.exe", config) is True

    save_app_overrides("GAME.exe", {}, config)
    assert config["APP_SETTINGS"] == {}
    assert app_uses_local_settings("game.exe", config) is False


def test_dark_theme_uses_dark_background_and_readable_foreground():
    theme = get_theme(True)

    assert theme["bg"] == "#12161c"
    assert theme["fg"] == "#f2f4f8"
    assert theme["entry_bg"] != theme["fg"]


def test_app_checkbox_text_shows_an_x_without_tiny_inline_status_icons():
    assert app_checkbox_text("Music.EXE", checked=True, is_running=True) == "☒  Music.EXE"
    assert app_checkbox_text("game.exe", checked=False, is_running=False, has_local_settings=True) == "☐  game.exe"


def test_app_status_icons_show_global_local_and_remembered_state():
    assert app_status_icons(is_running=True, has_local_settings=False) == "🌐"
    assert app_status_icons(is_running=True, has_local_settings=True) == "🔧"
    assert app_status_icons(is_running=False, has_local_settings=True) == "💤 🔧"
