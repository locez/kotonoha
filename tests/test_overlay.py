import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest
from overlay_helpers import (
    UnavailableController,
    _freeze_media_clock,
)
from PyQt6.QtCore import QEvent, QPointF, QRect, Qt
from PyQt6.QtGui import QMouseEvent

from kotonoha.config import Config
from kotonoha.overlay import LyricsOverlay
from kotonoha.state import LyricsState


def test_fixed_panel_pins_pill_width_independent_of_text(qapp):
    overlay = LyricsOverlay(
        LyricsState(),
        Config(panel_width_mode="fixed", panel_width=680),
        UnavailableController(),
    )
    overlay.apply_config(overlay._config)
    # The container is pinned to (about) the configured width, so it does not grow
    # or shrink with the line length.
    assert overlay._container.maximumWidth() <= 680
    assert overlay._container.minimumWidth() == overlay._container.maximumWidth()
    # Fit mode releases the pin so the pill hugs its content again.
    overlay.apply_config(Config(panel_width_mode="fit"))
    assert overlay._container.maximumWidth() > 5000
    overlay.deleteLater()
    qapp.processEvents()


def test_font_fallback_chain_keeps_cjk_after_a_latin_family(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(font_family="Inter"), UnavailableController())
    families = overlay._font_families()
    assert families[0] == "Inter"  # the chosen family leads
    assert any("CJK" in name for name in families)  # CJK fallback still present
    overlay.deleteLater()
    qapp.processEvents()


def test_idle_shows_default_text_so_the_panel_is_not_empty(qapp):
    from kotonoha.model import EMPTY_SNAPSHOT

    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._on_snapshot(EMPTY_SNAPSHOT)  # nothing playing
    assert overlay._current.text  # a default line is shown, not a blank box
    assert "♪" in overlay._current.text
    overlay.deleteLater()
    qapp.processEvents()


def test_effects_apply_to_current_line_only_and_paint_safely(qapp):
    from kotonoha.model import LyricLine, LyricsSnapshot, LyricWord

    overlay = LyricsOverlay(
        LyricsState(),
        Config(fx_glow=True, fx_word_pop=True, fx_intensity="expressive"),
        UnavailableController(),
    )
    # Effects land on the main line; the translation stays plain.
    assert overlay._current._glow is True and overlay._current._word_pop is True
    assert overlay._translation._glow is False and overlay._translation._word_pop is False
    # A word-timed line paints (glow + pop path) without raising.
    line = LyricLine(
        index=1, id="c", start=0.0, end=6.0, text="あの日の 空へ", translation="",
        words=(LyricWord(0.0, 3.0, "あの日の"), LyricWord(3.0, 6.0, "空へ")),
    )
    overlay._on_snapshot(LyricsSnapshot(found=True, current=line, current_time=2.0, is_playing=True, timing="Word"))
    overlay._current.set_media_time(2.0)
    overlay._current.grab()  # force a paint pass through the effect code
    overlay.deleteLater()
    qapp.processEvents()


def test_current_line_only_hides_context_and_keeps_current_translation(qapp):
    from kotonoha.model import LyricLine, LyricsSnapshot

    previous = LyricLine(0, "p", 0.0, 2.0, "previous", "", ())
    current = LyricLine(1, "c", 2.0, 4.0, "current", "译文", ())
    next_line = LyricLine(2, "n", 4.0, 6.0, "next", "", ())
    snapshot = LyricsSnapshot(
        found=True,
        current=current,
        previous=previous,
        next=next_line,
        current_time=2.5,
        is_playing=True,
    )
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._on_snapshot(snapshot)
    full_height = overlay._band_height()
    assert overlay._prev_label.text() == "previous"
    assert overlay._next_label.text() == "next"
    assert overlay._translation.text == "译文"

    overlay.apply_config(Config(current_line_only=True))
    assert overlay._prev_label.isHidden() is True
    assert overlay._next_label.isHidden() is True
    assert overlay._current.text == "current"
    assert overlay._translation.text == "译文"
    assert overlay._band_height() < full_height

    overlay.apply_config(Config())
    assert overlay._prev_label.isHidden() is False
    assert overlay._next_label.isHidden() is False
    assert overlay._prev_label.text() == "previous"
    assert overlay._next_label.text() == "next"
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_long_title_marquee_scrolls_then_holds(qapp):
    from kotonoha.karaoke_label import _MARQUEE_PAUSE_S, _MARQUEE_SPEED_PX_S, KaraokeLabel
    from kotonoha.model import LyricLine

    label = KaraokeLabel()
    label.resize(100, 40)
    label.set_line(LyricLine(0, "title", 0.0, 1e9, "A very very very long now-playing title", "", ()), False)
    overflow = 300.0  # pretend the text is 300px wider than the 100px label
    # The opening pause holds the title at the left...
    label.set_media_time(0.0)
    assert label._marquee_offset(overflow) == 0.0
    # ...then it glides partway...
    travel = overflow / _MARQUEE_SPEED_PX_S
    label.set_media_time(_MARQUEE_PAUSE_S + travel / 2.0)
    assert 0.0 < label._marquee_offset(overflow) < overflow
    # ...and reaches the far end fully scrolled.
    label.set_media_time(_MARQUEE_PAUSE_S + travel)
    assert label._marquee_offset(overflow) == overflow
    # Holds at the far end through the second pause...
    label.set_media_time(_MARQUEE_PAUSE_S + travel + _MARQUEE_PAUSE_S / 2.0)
    assert label._marquee_offset(overflow) == overflow
    # ...then glides back on the return leg (partway back, not at either end).
    label.set_media_time(2 * _MARQUEE_PAUSE_S + travel + travel / 2.0)
    assert 0.0 < label._marquee_offset(overflow) < overflow
    # No media clock yet (truly idle) -> no scrolling.
    label.set_media_time(None)
    assert label._marquee_offset(overflow) == 0.0
    assert label._is_title() is True
    label._total_w = 400.0
    label.grab()  # paints through the title/marquee branch without raising
    label.deleteLater()
    qapp.processEvents()


def test_transition_styles_paint_without_raising(qapp):
    from kotonoha.karaoke_label import KaraokeLabel
    from kotonoha.model import LyricLine

    label = KaraokeLabel()
    label.resize(200, 40)
    for style in ("fade", "rise", "slide", "zoom"):
        label.set_effects(glow=False, word_pop=False, intensity="subtle", animate=True, transition=style)
        assert label._transition == style
        label.set_line(LyricLine(0, style, 0.0, 3.0, "line", "", ()), False)
        label._reveal = 0.4  # mid-transition
        label.grab()
    label.deleteLater()
    qapp.processEvents()


def test_disabling_animations_reveals_lines_instantly(qapp):
    from kotonoha.karaoke_label import KaraokeLabel
    from kotonoha.model import LyricLine

    label = KaraokeLabel()
    label.set_effects(glow=False, word_pop=False, intensity="subtle", animate=False)
    label.set_line(LyricLine(0, "a", 0.0, 3.0, "x", "", ()), False)
    label.set_line(LyricLine(1, "b", 0.0, 3.0, "y", "", ()), False)  # a line change
    assert label._reveal == 1.0  # animations off -> shown immediately, no fade/rise
    label.deleteLater()
    qapp.processEvents()


def test_white_panel_flips_text_and_context_shadow_to_light(qapp):
    from PyQt6.QtWidgets import QGraphicsDropShadowEffect

    overlay = LyricsOverlay(LyricsState(), Config(panel_style="white"), UnavailableController())
    base, shadow, context_css = overlay._text_colors()
    assert base.lightness() < 90  # dark lyric text on the near-white slab
    assert shadow.lightness() > 160  # light halo, not a black smudge
    effect = overlay._prev_label.graphicsEffect()
    assert isinstance(effect, QGraphicsDropShadowEffect)
    assert effect.color().lightness() > 160  # context halo follows the panel too
    # A dark panel keeps light text with a dark halo.
    overlay.apply_config(Config(panel_style="pill"))
    assert overlay._text_colors()[0].lightness() > 160
    effect = overlay._prev_label.graphicsEffect()
    assert isinstance(effect, QGraphicsDropShadowEffect)
    assert effect.color().lightness() < 100
    overlay.deleteLater()
    qapp.processEvents()


def test_untimed_word_does_not_freeze_sweep(qapp):
    from PyQt6.QtGui import QFont

    from kotonoha.karaoke_label import KaraokeLabel
    from kotonoha.model import LyricLine, LyricWord

    label = KaraokeLabel()
    label.set_style(QFont(), "#FF4FA3", "#FF8FCB", "#FF6EC7")
    line = LyricLine(
        index=0, id="L", start=0.0, end=3.0, text="? word", translation="",
        words=(LyricWord(None, None, "?"), LyricWord(1.0, 2.0, "word")),
    )
    label.set_line(line, True)
    label.set_media_time(1.5)  # halfway through the *timed* word

    sweep_x, active = label._compute_sweep(0.0, label._total_w)

    # Before the fix, the leading untimed word froze the sweep at text_left (0.0).
    assert sweep_x > 0.0
    assert active is not None  # the timed word is actively sweeping
    label.deleteLater()
    qapp.processEvents()


def test_panel_visibility_follows_style_not_lock(qapp):
    # Locking must not force-hide the panel; that is the panel-style setting's job.
    locked_pill = LyricsOverlay(
        LyricsState(), Config(passthrough=True, panel_style="pill"), UnavailableController()
    )
    assert locked_pill._should_paint_panel() is True  # Glass panel stays while locked
    locked_text = LyricsOverlay(
        LyricsState(), Config(passthrough=True, panel_style="text"), UnavailableController()
    )
    assert locked_text._should_paint_panel() is False  # Text-only is immersive
    for overlay in (locked_pill, locked_text):
        overlay._render_timer.stop()
        overlay.deleteLater()
    qapp.processEvents()


def test_lyric_script_converts_displayed_line(qapp):
    from kotonoha.model import LyricLine, LyricWord

    line = LyricLine(0, "L", 0.0, 3.0, "简体字", translation="翻译", words=(LyricWord(0.0, 1.0, "简"),))
    converted = LyricsOverlay(
        LyricsState(), Config(lyrics_script="zh-Hant"), UnavailableController()
    )
    out = converted._convert_line(line)
    assert out is not None
    assert out.text == "簡體字"  # display converted to Traditional
    assert out.words[0].text == "簡"  # words converted too (for the karaoke sweep)
    off = LyricsOverlay(LyricsState(), Config(lyrics_script="off"), UnavailableController())
    assert off._convert_line(line) is line  # untouched when disabled
    for overlay in (converted, off):
        overlay._render_timer.stop()
        overlay.deleteLater()
    qapp.processEvents()


def test_accent_tinted_black_panel_uses_accent_hue(qapp):
    from PyQt6.QtGui import QColor

    overlay = LyricsOverlay(
        LyricsState(),
        Config(panel_style="pill", panel_accent_tint=True, accent_start="#FF4FA3"),
        UnavailableController(),
    )
    colour = overlay._panel_base_color()
    assert colour != QColor(15, 17, 22)  # not the flat near-black
    assert colour.red() > colour.blue()  # tinted toward the pink accent
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_frosted_panel_paints_and_keeps_window_opaque(qapp):
    overlay = LyricsOverlay(
        LyricsState(), Config(panel_style="frost", opacity=0.6), UnavailableController()
    )
    assert overlay._should_paint_panel() is True  # frosted panel is drawn
    assert overlay.windowOpacity() == pytest.approx(1.0, abs=0.01)  # text stays crisp
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_panel_alpha_tracks_opacity(qapp):
    overlay = LyricsOverlay(
        LyricsState(),
        Config(panel_style="pill", opacity=1.0),
        UnavailableController(),
    )
    assert overlay._panel_alpha() == 255  # 100% -> solid, not the old 150 cap
    overlay.apply_config(Config(panel_style="pill", opacity=0.3))
    assert overlay._panel_alpha() == round(255 * 0.3)
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_window_stays_opaque_and_frost_uses_its_own_opacity(qapp):
    # Opacity is the panel's own fill (window always opaque so text stays crisp),
    # and the black and frosted panels keep independent opacity values.
    black = LyricsOverlay(
        LyricsState(), Config(panel_style="pill", opacity=0.0, frost_opacity=0.6), UnavailableController()
    )
    assert black.windowOpacity() == pytest.approx(1.0, abs=0.01)
    assert black._panel_alpha() == 0  # black panel can go fully transparent
    frost = LyricsOverlay(
        LyricsState(), Config(panel_style="frost", opacity=0.0, frost_opacity=0.6), UnavailableController()
    )
    assert frost.windowOpacity() == pytest.approx(1.0, abs=0.01)
    assert frost._panel_alpha() == round(255 * 0.6)  # frost uses frost_opacity, not opacity
    for overlay in (black, frost):
        overlay._render_timer.stop()
        overlay.deleteLater()
    qapp.processEvents()


def test_click_without_motion_does_not_persist_a_new_horizontal_offset(qapp):
    overlay = LyricsOverlay(
        LyricsState(), Config(margin_x=37), UnavailableController()
    )
    emitted: list[tuple[int, int, str]] = []
    overlay.position_changed.connect(lambda edge, margin_x, name: emitted.append((edge, margin_x, name)))
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    overlay.mousePressEvent(press)
    overlay.mouseReleaseEvent(release)

    assert overlay._config.margin_x == 37
    assert emitted == []
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_offset_buttons_shift_sweep_and_hide_with_lock(qapp):
    from kotonoha.model import LyricLine, LyricsSnapshot

    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    snapshot = LyricsSnapshot(
        found=True, title="Song", artist="Artist", duration_s=180.0,
        current=LyricLine(0, "line", 0.0, 4.0, "line", "", ()), current_time=1.0, is_playing=True,
    )
    overlay._on_snapshot(snapshot)
    overlay._clock.sync(1.0, True)
    _freeze_media_clock(overlay, 1.0)
    overlay._render_tick()
    before = overlay._current._media_time
    assert before is not None
    overlay._earlier_btn.click()
    assert overlay._config.track_offsets[overlay._track_key] == 50
    assert overlay._current._media_time == pytest.approx(before + 0.05)
    assert overlay._current.text == "Sync offset: +50 ms"
    overlay.set_passthrough(True)
    assert overlay._earlier_btn.isHidden() is True
    assert overlay._later_btn.isHidden() is True
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_track_without_offset_uses_global_lead(qapp):
    from kotonoha.model import LyricLine, LyricsSnapshot

    overlay = LyricsOverlay(LyricsState(), Config(lead_ms=120), UnavailableController())
    overlay._clock.sync(1.0, True)
    _freeze_media_clock(overlay, 1.0)
    overlay._on_snapshot(LyricsSnapshot(
        found=True, title="Song", artist="Artist",
        current=LyricLine(0, "line", 0.0, 4.0, "line", "", ()), current_time=1.0, is_playing=True,
    ))
    overlay._render_tick()
    assert overlay._current._media_time == pytest.approx(1.12)
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()






def test_turning_off_word_highlight_stops_the_word_sweep(qapp):
    # Only the snapshot's own timing flag was consulted, so the settings checkbox
    # saved, translated into four languages, and changed nothing.
    from kotonoha.model import LyricLine, LyricsSnapshot, LyricWord

    words = (LyricWord(0.0, 0.5, "你"), LyricWord(0.5, 1.0, "好"))
    line = LyricLine(0, "L0", 0.0, 4.0, "你好", "", words)
    snapshot = LyricsSnapshot(
        found=True, timing="Word", title="Song", artist="Artist", duration_s=100.0,
        current=line, current_time=0.2, is_playing=True,
    )

    on = LyricsOverlay(LyricsState(), Config(karaoke=True), UnavailableController())
    off = LyricsOverlay(LyricsState(), Config(karaoke=False), UnavailableController())
    on._on_snapshot(snapshot)
    off._on_snapshot(snapshot)

    assert on._current._word_mode is True
    assert off._current._word_mode is False, "the word-highlight setting did nothing"
    for overlay in (on, off):
        overlay._render_timer.stop()
        overlay.deleteLater()


def test_fit_mode_gives_a_large_font_room_for_a_whole_line(qapp, monkeypatch):
    # Fit mode capped the window at a flat 1100px, which was room for a line only at
    # the default font size. At font_size 80 an ordinary English lyric measures about
    # 2000px, so half of every line sat outside the window and scrolled away.
    class WideScreen:
        def geometry(self):
            return QRect(0, 0, 5120, 1440)

    def widths(font_size):
        overlay = LyricsOverlay(
            LyricsState(), Config(panel_width_mode="fit", font_size=font_size), UnavailableController()
        )
        monkeypatch.setattr(overlay, "_target_screen", lambda: WideScreen())
        width = overlay._window_size()[0]
        overlay.deleteLater()
        return width

    assert widths(20) == 1100, "the default font size lost its established width"
    assert widths(80) - 56 >= 2023, "a 2023px line still does not fit at font_size 80"
    qapp.processEvents()
