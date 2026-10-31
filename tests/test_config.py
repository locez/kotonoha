import json
from pathlib import Path
from typing import cast

import pytest

from kotonoha.config import (
    DEFAULT_LYRICS_SOURCES,
    SETTINGS_CONFIG_FIELDS,
    SETTINGS_PAGE_FIELDS,
    VALID_LYRICS_SOURCES,
    Config,
    FxIntensity,
    FxTransition,
    LyricsScript,
    PanelStyle,
    PanelWidthMode,
    ThemeMode,
    load_config,
    save_config,
)


def test_settings_schema_has_one_ordered_field_contract() -> None:
    """The Settings page grouping and merge order must stay identical."""
    flattened = tuple(field_name for page in SETTINGS_PAGE_FIELDS for field_name in page)

    assert flattened == SETTINGS_CONFIG_FIELDS
    assert len(Config().settings_values()) == len(SETTINGS_CONFIG_FIELDS)


def test_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(port=30000, anchor_top=False, font_size=40, show_translation=False)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.port == 30000
    assert loaded.anchor_top is False
    assert loaded.font_size == 40
    assert loaded.show_translation is False


def test_qqmusic_is_known_but_not_default():
    assert "qqmusic" in VALID_LYRICS_SOURCES
    assert "qqmusic" not in DEFAULT_LYRICS_SOURCES
    assert Config.from_dict({"lyrics_sources": ["qqmusic"]}).lyrics_sources == ["qqmusic"]


@pytest.mark.parametrize(
    "initial_data",
    [None, {}, {"lyrics_sources": None}, {"lyrics_sources": []}, {"lyrics_sources": ["unknown"]}],
)
def test_cider_is_opt_in_and_preserves_saved_selection(
    tmp_path: Path, initial_data: dict[str, object] | None,
) -> None:
    """Fresh or invalid settings omit Cider without overriding a saved opt-in."""
    path = tmp_path / "config.json"
    if initial_data is not None:
        path.write_text(json.dumps(initial_data), encoding="utf-8")

    assert load_config(path).lyrics_sources == ["amll", "netease", "lrclib", "kugou"]

    save_config(Config(lyrics_sources=["cider", "netease"]), path)

    assert load_config(path).lyrics_sources == ["cider", "netease"]


def test_screen_name_roundtrips(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(screen_name="DP-1"), path)
    assert load_config(path).screen_name == "DP-1"


def test_display_sources_roundtrip_preserves_order(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(display_sources=["adapter", "cider"]), path)

    assert load_config(path).display_sources == ["adapter", "cider"]


def test_player_lock_roundtrips_and_clamps():
    assert Config().player_lock == ""
    assert Config(player_lock="org.mpris.MediaPlayer2.youtube").clamped().player_lock == (
        "org.mpris.MediaPlayer2.youtube"
    )
    assert Config.from_dict({"player_lock": 123}).player_lock == ""


def test_cider_api_token_roundtrips_in_config(tmp_path):
    path = tmp_path / "c.json"
    cfg = Config(cider_api_token="  test-token  ")

    assert cfg.clamped().cider_api_token == "test-token"
    save_config(cfg, path)

    assert '"cider_api_token": "  test-token  "' in path.read_text(encoding="utf-8")
    assert load_config(path).cider_api_token == "test-token"
    assert Config.from_dict({"cider_api_token": "from-file"}).cider_api_token == "from-file"


def test_frost_panel_style_survives_clamp():
    assert Config(panel_style=PanelStyle.FROST).clamped().panel_style == "frost"
    assert Config.from_dict({"panel_style": "bogus"}).panel_style == "pill"


def test_panel_accent_tint_roundtrips(tmp_path):
    path = tmp_path / "c.json"
    save_config(Config(panel_accent_tint=True), path)
    assert load_config(path).panel_accent_tint is True


def test_lyrics_script_clamps_unknown_to_off():
    assert Config(lyrics_script=LyricsScript.ZH_HANT).clamped().lyrics_script == "zh-Hant"
    assert Config.from_dict({"lyrics_script": "bogus"}).lyrics_script == "off"


@pytest.mark.parametrize(
    ("legacy", "count", "expected"),
    [(True, 10, 0), (1, 3, 0), (False, 10, 10), (0, 25, 25), ("true", 3, 3)],
)
def test_legacy_context_visibility_migrates_once(
    tmp_path: Path, legacy: object, count: int, expected: int,
) -> None:
    """Old hidden-context settings survive upgrades without persisting two controls."""
    path = tmp_path / "c.json"
    config = Config.from_dict({"current_line_only": legacy, "context_lines": count})
    assert config.context_lines == expected
    save_config(config, path)
    assert "current_line_only" not in json.loads(path.read_text(encoding="utf-8"))
    assert load_config(path).context_lines == expected
    assert Config.from_dict({"current_line_only": True}).context_lines == 0


@pytest.mark.parametrize("strength", [0.0, 0.25, 0.67, 1.0])
def test_context_blur_roundtrips(tmp_path: Path, strength: float) -> None:
    """A chosen blur amount, including disabled blur, survives persistence."""
    path = tmp_path / "c.json"
    config = Config.from_dict({"context_blur": strength})
    save_config(config, path)
    assert load_config(path).context_blur == strength


@pytest.mark.parametrize(("value", "expected"), [(None, 0.0), ("bad", 0.0), (-1, 0.0), (2, 1.0)])
def test_context_blur_validates_external_values(value: object, expected: float) -> None:
    """Malformed settings fall back; numeric strengths stay in the percentage range."""
    assert Config.from_dict({"context_blur": value}).context_blur == expected


def test_typography_and_panel_size_roundtrip(tmp_path):
    path = tmp_path / "c.json"
    cfg = Config(
        font_family="Noto Sans CJK SC",
        context_font_size=18, translation_font_size=11,
        panel_width_mode=PanelWidthMode.FIXED, panel_width=880,
    )
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.font_family == "Noto Sans CJK SC"
    assert loaded.context_font_size == 18
    assert loaded.translation_font_size == 11
    assert loaded.panel_width_mode == "fixed"
    assert loaded.panel_width == 880


def test_typography_and_panel_size_defaults_and_clamps():
    # New keys default sanely and coerce out-of-range values.
    assert Config().panel_width_mode == "fit"
    assert Config(context_font_size=1).clamped().context_font_size == 8
    assert Config(panel_width=99999).clamped().panel_width == 2400
    assert Config.from_dict({"panel_width_mode": "bogus"}).panel_width_mode == "fit"


def test_all_font_sizes_clamp_to_the_spin_box_range():
    # All three sizes clamp to 8..120 — the same range the Appearance spin boxes
    # offer — so opening Settings and pressing Apply can never truncate them.
    assert Config(font_size=999).clamped().font_size == 120
    assert Config(context_font_size=200).clamped().context_font_size == 120
    assert Config(translation_font_size=200).clamped().translation_font_size == 120


def test_effects_defaults_clamp_and_roundtrip(tmp_path):
    # Calm defaults: animations on, glow / word-pop off.
    assert Config().fx_animate is True
    assert Config().fx_glow is False
    assert Config().fx_word_pop is False
    assert Config().fx_intensity == "subtle"
    assert Config(fx_intensity=FxIntensity.EXPRESSIVE).clamped().fx_intensity == "expressive"
    assert Config.from_dict({"fx_intensity": "bogus"}).fx_intensity == "subtle"
    # Line-change transition: "rise" default, known values kept, junk falls back.
    assert Config().fx_transition == "rise"
    assert Config(fx_transition=FxTransition.ZOOM).clamped().fx_transition == "zoom"
    assert Config.from_dict({"fx_transition": "bogus"}).fx_transition == "rise"
    # Fuzzy matching: on by default, coerced to bool.
    assert Config().fuzzy_match is True
    assert Config(fuzzy_match=cast(bool, 0)).clamped().fuzzy_match is False
    # Settings-window opacity: a touch see-through by default, clamped to 0.0..1.0.
    assert Config().settings_opacity == 0.80
    assert Config(settings_opacity=2.0).clamped().settings_opacity == 1.0
    assert Config(settings_opacity=-0.5).clamped().settings_opacity == 0.0
    path = tmp_path / "c.json"
    save_config(
        Config(fx_animate=False, fx_glow=False, fx_word_pop=False, fx_intensity=FxIntensity.EXPRESSIVE), path
    )
    loaded = load_config(path)
    assert not loaded.fx_animate and not loaded.fx_glow and not loaded.fx_word_pop
    assert loaded.fx_intensity == "expressive"


def test_theme_and_white_panel_clamp_and_roundtrip(tmp_path):
    assert Config().theme == "auto"
    assert Config(theme=ThemeMode.LIGHT).clamped().theme == "light"
    assert Config.from_dict({"theme": "bogus"}).theme == "auto"
    assert Config(panel_style=PanelStyle.WHITE).clamped().panel_style == "white"
    path = tmp_path / "c.json"
    save_config(Config(theme=ThemeMode.DARK, panel_style=PanelStyle.WHITE), path)
    loaded = load_config(path)
    assert loaded.theme == "dark"
    assert loaded.panel_style == "white"


def test_frost_window_defaults_and_roundtrips(tmp_path):
    assert Config().frost_window is True
    assert Config(frost_window=cast(bool, 0)).clamped().frost_window is False  # coerced to bool
    path = tmp_path / "c.json"
    save_config(Config(frost_window=False), path)
    assert load_config(path).frost_window is False


def test_frost_opacity_and_full_transparency(tmp_path):
    path = tmp_path / "c.json"
    save_config(Config(opacity=0.0, frost_opacity=0.35), path)
    loaded = load_config(path)
    assert loaded.opacity == 0.0  # black panel may now be fully transparent
    assert loaded.frost_opacity == 0.35


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
    assert Config(opacity=-1.0).clamped().opacity == 0.0  # 0..1 now (fully transparent allowed)
    assert Config(opacity=0.0).clamped().opacity == 0.0
    assert Config(font_size=1).clamped().font_size == 8
    assert Config.from_dict({"panel_style": "weird"}).panel_style == "pill"


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


def test_every_lyric_source_has_a_display_name_in_every_language():
    # Adding a source without its string leaves the settings list showing the raw
    # key, e.g. "src.qqmusic". This is the guard for that.
    from kotonoha.strings import STRINGS

    missing = []
    for source in VALID_LYRICS_SOURCES:
        entry = STRINGS.get(f"src.{source}")
        if entry is None:
            missing.append(f"src.{source} (no entry)")
            continue
        for language in ("en", "zh-Hans", "zh-Hant", "ja"):
            if not entry.get(language):
                missing.append(f"src.{source} [{language}]")
    assert not missing, f"lyric sources without a display name: {missing}"


def test_track_offsets_are_not_stored_in_json_config(tmp_path):
    path = tmp_path / "config.json"
    loaded = Config.from_dict({"track_offsets": {"legacy": 50}})

    assert "track_offsets" not in loaded.to_dict()
    save_config(loaded, path)
    assert "track_offsets" not in json.loads(path.read_text(encoding="utf-8"))


def test_a_failed_save_leaves_the_previous_configuration_intact(tmp_path, monkeypatch):
    # The point of writing to a sibling and renaming: the target is only ever
    # replaced by a file that is already complete. Written in place, a save that
    # died partway — a logout, a full disk — left truncated JSON behind.
    path = tmp_path / "config.json"
    save_config(Config(lead_ms=250), path)

    def no_space(*_args, **_kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "replace", no_space)
    try:
        save_config(Config(lead_ms=999), path)
    except OSError:
        pass
    else:
        raise AssertionError("the save reported success without replacing the file")

    assert load_config(path).lead_ms == 250, "the previous configuration was destroyed"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.json"], "a temporary was left behind"


def test_an_unreadable_config_is_kept_rather_than_overwritten(tmp_path):
    # Defaults let the app start, but the next save — a drag release is enough —
    # used to write them over the damaged file, turning one interrupted write into
    # permanent loss of every setting the user had chosen.
    path = tmp_path / "config.json"
    save_config(Config(margin_x=-1100, lead_ms=250), path)
    whole = path.read_text(encoding="utf-8")
    path.write_text(whole[: len(whole) // 2], encoding="utf-8")

    recovered = load_config(path)

    assert recovered.lead_ms == Config().lead_ms, "a damaged file must not be trusted"
    salvaged = tmp_path / "config.json.corrupt"
    assert salvaged.exists(), "the unreadable file was destroyed instead of set aside"
    assert "margin_x" in salvaged.read_text(encoding="utf-8")

    save_config(recovered, path)
    assert salvaged.exists(), "the salvaged copy must survive the next save"


def test_a_config_that_is_not_utf8_does_not_end_startup(tmp_path):
    # load_config runs before there is any window to report a problem in, so an
    # escaping UnicodeDecodeError took the whole application down rather than
    # costing the settings in the file.
    path = tmp_path / "config.json"
    path.write_bytes(b'{"lead_ms": 1' + bytes([0xFF, 0xFE]) + b"}")

    assert load_config(path).lead_ms == Config().lead_ms
    assert (tmp_path / "config.json.corrupt").exists(), "the unreadable file was not kept"


def test_an_oversized_but_valid_json_config_is_not_accepted(tmp_path, monkeypatch):
    # A byte cap must reject a complete object followed by enough whitespace to
    # make the file oversized. Reading only the first cap bytes could otherwise
    # mistake that truncated prefix for a valid JSON document.
    import kotonoha.config.store as config_store

    monkeypatch.setattr(config_store, "MAX_CONFIG_BYTES", 16)
    path = tmp_path / "config.json"
    path.write_bytes(b'{"port": 1234}' + b" " * 8)

    assert load_config(path) == Config()
    assert path.exists(), "an oversized file should be left intact for inspection"


def test_a_pipe_at_the_config_path_does_not_block_startup(tmp_path):
    import os
    import threading

    path = tmp_path / "config.json"
    os.mkfifo(path)
    finished = threading.Event()

    def read() -> None:
        load_config(path)
        finished.set()

    # Joined rather than left running: if this regresses the thread blocks forever,
    # and an unowned one would keep the interpreter's thread state alive for the
    # rest of the session with nothing to report it.
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        assert finished.wait(5.0), "startup is blocked on a pipe left at the config path"
    finally:
        reader.join(timeout=5.0)


def test_a_number_too_large_for_an_int_falls_back_to_the_default(tmp_path):
    # JSON accepts 1e400 and int() raises OverflowError on it. Unhandled on the
    # startup path, that meant the application did not start at all.
    path = tmp_path / "config.json"
    path.write_text('{"lead_ms": 1e400, "panel_width": 900}', encoding="utf-8")

    loaded = load_config(path)

    assert loaded.lead_ms == Config().lead_ms
    assert loaded.panel_width == 900, "the rest of the file must still be read"
