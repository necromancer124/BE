from bear_settings import DEFAULT_CONFIG, get_theme, normalize_config, should_limit_app


def test_normalize_config_migrates_existing_config_with_new_defaults():
    old_config = {"THRESHOLD": 0.35, "USE_MUTE": True}

    migrated = normalize_config(old_config)

    assert migrated["THRESHOLD"] == 0.35
    assert migrated["USE_MUTE"] is True
    assert migrated["LIMIT_ONLY_SELECTED"] is False
    assert migrated["SELECTED_APPS"] == []
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


def test_dark_theme_uses_dark_background_and_readable_foreground():
    theme = get_theme(True)

    assert theme["bg"] == "#12161c"
    assert theme["fg"] == "#f2f4f8"
    assert theme["entry_bg"] != theme["fg"]
