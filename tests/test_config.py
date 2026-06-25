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
