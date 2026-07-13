from kotonoha.config import Config, load_config, save_config


def test_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(port=30000, anchor_top=False, font_size=40, show_translation=False)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.port == 30000
    assert loaded.anchor_top is False
    assert loaded.font_size == 40
    assert loaded.show_translation is False


def test_frost_panel_style_survives_clamp():
    assert Config(panel_style="frost").clamped().panel_style == "frost"
    assert Config(panel_style="bogus").clamped().panel_style == "pill"


def test_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.json")
    assert cfg == Config()


def test_invalid_json_returns_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")
    assert load_config(path) == Config()


def test_unknown_keys_ignored_and_defaults_filled():
    cfg = Config.from_dict({"port": 40000, "totally_unknown": 5})
    assert cfg.port == 40000
    assert cfg.karaoke is True  # default preserved


def test_clamping():
    assert Config(port=99999).clamped().port == 65535  # clamped to max, not reset
    assert Config(opacity=5.0).clamped().opacity == 1.0
    assert Config(opacity=0.0).clamped().opacity == 0.3
    assert Config(font_size=1).clamped().font_size == 8
    assert Config(panel_style="weird").clamped().panel_style == "pill"


def test_from_dict_non_dict():
    assert Config.from_dict("nope") == Config()
    assert Config.from_dict(None) == Config()


def test_cache_enabled_defaults_true_and_roundtrips(tmp_path):
    assert Config().cache_enabled is True
    path = tmp_path / "config.json"
    save_config(Config(cache_enabled=False), path)
    assert load_config(path).cache_enabled is False


def test_cache_enabled_is_clamped_to_bool():
    assert Config.from_dict({"cache_enabled": 0}).cache_enabled is False
    assert Config.from_dict({"cache_enabled": 1}).cache_enabled is True


def test_icon_name_roundtrips_and_rejects_paths(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(icon_name="leaf-pink.svg"), path)
    assert load_config(path).icon_name == "leaf-pink.svg"
    assert Config.from_dict({"icon_name": "../outside.svg"}).icon_name == "default"
