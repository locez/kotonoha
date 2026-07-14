import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QApplication

from kotonoha.config import Config
from kotonoha.native import LayerShellController
from kotonoha.overlay import LyricsOverlay
from kotonoha.state import LyricsState


class UnavailableController(LayerShellController):
    def __init__(self) -> None:
        super().__init__("", "wayland", "GNOME")


class RecordingOverlay(LyricsOverlay):
    def __init__(self, *args, **kwargs):
        self.paint_calls = 0
        super().__init__(*args, **kwargs)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        self.paint_calls += 1
        super().paintEvent(a0)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


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


def test_container_move_repaints_translucent_surface(qapp):
    overlay = RecordingOverlay(
        LyricsState(),
        Config(passthrough=False, panel_style="pill"),
        UnavailableController(),
    )
    overlay.show()
    qapp.processEvents()
    overlay.paint_calls = 0

    overlay.eventFilter(overlay._container, QEvent(QEvent.Type.Move))
    qapp.processEvents()

    assert overlay.paint_calls > 0
    overlay._render_timer.stop()
    overlay.close()
    overlay.deleteLater()
    qapp.processEvents()
