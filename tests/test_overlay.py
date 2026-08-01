import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from kotonoha.config import Config
from kotonoha.native import LayerShellController
from kotonoha.overlay import LyricsOverlay
from kotonoha.state import LyricsState


class UnavailableController(LayerShellController):
    def __init__(self) -> None:
        super().__init__("", "wayland", "GNOME")


class AvailableController(UnavailableController):
    @property
    def available(self):
        return True


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


def _mouse_event(event_type, local, global_pos, *, pressed):
    button = Qt.MouseButton.NoButton if event_type == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.LeftButton if pressed else Qt.MouseButton.NoButton
    return QMouseEvent(
        event_type,
        QPointF(*local),
        QPointF(*local),
        QPointF(*global_pos),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_plain_click_does_not_persist_or_move_overlay(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._layer_pos = QPoint(100, 100)

    with (
        patch.object(overlay, "_apply_layer_position") as apply_position,
        patch.object(overlay, "_commit_drag_position") as commit_position,
    ):
        overlay.mousePressEvent(
            _mouse_event(QEvent.Type.MouseButtonPress, (300, 60), (1000, 500), pressed=True)
        )
        overlay.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (302, 61), (1002, 501), pressed=True))
        overlay.mouseReleaseEvent(
            _mouse_event(QEvent.Type.MouseButtonRelease, (302, 61), (1002, 501), pressed=False)
        )

    assert overlay._layer_pos == QPoint(100, 100)
    apply_position.assert_not_called()
    commit_position.assert_not_called()
    overlay.deleteLater()
    qapp.processEvents()


def test_drag_tracks_global_delta_live_without_accumulating_local_feedback(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._layer_pos = QPoint(100, 100)

    with (
        patch.object(overlay, "_clamp_drag_panel_position", side_effect=lambda pos: pos),
        patch.object(overlay, "_apply_layer_position") as apply_position,
        patch.object(overlay, "_commit_drag_position") as commit_position,
        patch.object(overlay, "_apply_input_region") as apply_input_region,
    ):
        overlay.mousePressEvent(
            _mouse_event(QEvent.Type.MouseButtonPress, (300, 60), (1000, 500), pressed=True)
        )
        overlay.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (330, 85), (1030, 525), pressed=True))

        assert overlay._layer_pos == QPoint(130, 125)
        apply_position.assert_called_once_with()

        # A compositor-driven local-coordinate change at the same global pointer
        # position must not be accumulated as another movement.
        overlay.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (300, 60), (1030, 525), pressed=True))
        assert overlay._layer_pos == QPoint(130, 125)
        apply_position.assert_called_once_with()

        overlay.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (990, 700), (1060, 540), pressed=True))
        assert overlay._layer_pos == QPoint(160, 140)
        assert apply_position.call_count == 2

        overlay.mouseReleaseEvent(
            _mouse_event(QEvent.Type.MouseButtonRelease, (990, 700), (1060, 540), pressed=False)
        )

    # Release persists the already-visible live position and repairs the native
    # input region; it does not perform a deferred jump.
    assert overlay._layer_pos == QPoint(160, 140)
    assert apply_position.call_count == 2
    commit_position.assert_called_once_with()
    apply_input_region.assert_called_once_with()
    overlay.deleteLater()
    qapp.processEvents()


def test_drag_compensates_when_compositor_shrinks_surface_around_panel(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._layer_pos = QPoint(100, 100)
    overlay._container.setGeometry(400, 20, 200, 100)

    with (
        patch.object(overlay, "_clamp_drag_panel_position", side_effect=lambda pos: pos),
        patch.object(overlay, "_apply_layer_position") as apply_position,
    ):
        overlay.mousePressEvent(
            _mouse_event(QEvent.Type.MouseButtonPress, (500, 60), (1000, 500), pressed=True)
        )

        # niri configures a narrower surface near an edge, shifting the centered
        # panel 100 px left inside its transparent parent.
        overlay._container.setGeometry(300, 20, 200, 100)
        overlay.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (530, 60), (1030, 500), pressed=True))

    # The layer origin compensates for the local shift, so the visible panel moves
    # by exactly the same 30 px as the pointer.
    assert overlay._layer_pos == QPoint(230, 100)
    assert overlay._layer_pos.x() + overlay._container.x() == 530
    apply_position.assert_called_once_with()
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_drag_discards_edge_overdrag_so_reverse_motion_is_immediate(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._layer_pos = QPoint(100, 100)
    panel_x = overlay._container.x()

    def clamp_right_edge(pos):
        return QPointF(min(pos.x(), 150 + panel_x), pos.y())

    with (
        patch.object(overlay, "_clamp_drag_panel_position", side_effect=clamp_right_edge),
        patch.object(overlay, "_apply_layer_position") as apply_position,
    ):
        overlay.mousePressEvent(
            _mouse_event(QEvent.Type.MouseButtonPress, (300, 60), (1000, 500), pressed=True)
        )
        overlay.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (400, 60), (1100, 500), pressed=True))
        assert overlay._layer_pos == QPoint(150, 100)

        # Each outward event is discarded at once. A one-pixel reversal therefore
        # moves the panel immediately instead of paying back stale overdrag.
        overlay.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (399, 60), (1099, 500), pressed=True))
        assert overlay._layer_pos == QPoint(149, 100)
        assert apply_position.call_count == 2

    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_drag_release_retargeted_to_control_does_not_trigger_control(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    passthrough_requests = []
    settings_requests = []
    overlay.passthrough_toggle_requested.connect(lambda: passthrough_requests.append(True))
    overlay.settings_requested.connect(lambda: settings_requests.append(True))

    with (
        patch.object(overlay, "_commit_drag_position") as commit_position,
        patch.object(overlay, "_apply_input_region") as apply_input_region,
    ):
        overlay._dragging = True
        overlay._drag_moved = True
        overlay._on_lock_button_clicked()

        assert passthrough_requests == []
        assert overlay._dragging is False
        commit_position.assert_called_once_with()
        apply_input_region.assert_called_once_with()

        qapp.processEvents()  # clear the one-event-loop click suppression
        overlay._on_lock_button_clicked()
        assert passthrough_requests == [True]

        overlay._dragging = True
        overlay._drag_moved = True
        overlay._on_settings_button_clicked()
        assert settings_requests == []

    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_clamp_keeps_visible_panel_on_screen_not_transparent_surface(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._container.setGeometry(400, 40, 300, 100)

    class Screen:
        @staticmethod
        def geometry():
            return QRect(0, 0, 1000, 700)

    with (
        patch.object(overlay, "_target_screen", return_value=Screen()),
        patch.object(overlay, "_window_size", return_value=(1100, 140)),
    ):
        clamped = overlay._clamp_to_screen(QPoint(-10_000, 10_000))

    assert clamped == QPoint(-400, 560)
    assert clamped.x() + overlay._container.x() == 0
    assert clamped.y() + overlay._container.y() + overlay._container.height() == 700
    overlay.deleteLater()
    qapp.processEvents()


def test_live_position_uses_layer_shell_bridge_on_wayland(qapp):
    class Controller(AvailableController):
        def __init__(self):
            super().__init__()
            self.positions = []

        def set_anchor_position(self, ptr, x, y):
            self.positions.append((ptr, x, y))

    controller = Controller()
    overlay = LyricsOverlay(LyricsState(), Config(), controller)
    overlay._layer_pos = QPoint(120, 80)

    with patch.object(overlay, "_window_ptr", return_value=123):
        overlay._apply_layer_position()

    assert controller.positions == [(123, 120, 80)]
    overlay.deleteLater()
    qapp.processEvents()


def test_layer_shell_placement_stays_on_original_output(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), AvailableController())
    original_output = object()
    adjacent_output = object()
    overlay._layer_screen = None

    with (
        patch.object(QApplication, "screens", return_value=[original_output, adjacent_output]),
        patch.object(QApplication, "primaryScreen", return_value=original_output),
        patch.object(overlay, "screen", side_effect=[original_output, adjacent_output]),
    ):
        first = overlay._target_screen()
        after_qt_switch = overlay._target_screen()

    assert first is original_output
    assert after_qt_switch is original_output

    # Hot-unplugging the bound output safely selects the remaining primary output.
    with (
        patch.object(QApplication, "screens", return_value=[adjacent_output]),
        patch.object(QApplication, "primaryScreen", return_value=adjacent_output),
        patch.object(overlay, "screen", return_value=adjacent_output),
    ):
        assert overlay._target_screen() is adjacent_output

    overlay.deleteLater()
    qapp.processEvents()


def test_live_position_uses_screen_global_coordinates_without_layer_shell(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._layer_pos = QPoint(120, 80)

    class Screen:
        @staticmethod
        def geometry():
            return QRect(3440, 40, 1920, 1080)

    with (
        patch.object(overlay, "_target_screen", return_value=Screen()),
        patch.object(overlay, "move") as move,
    ):
        overlay._apply_layer_position()

    move.assert_called_once_with(3560, 120)
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


@pytest.mark.parametrize("event_type", (QEvent.Type.Move, QEvent.Type.Resize))
def test_container_geometry_change_schedules_surface_repaint(qapp, event_type):
    overlay = LyricsOverlay(
        LyricsState(),
        Config(passthrough=False, panel_style="pill"),
        UnavailableController(),
    )

    with patch.object(overlay, "update") as update:
        overlay.eventFilter(overlay._container, QEvent(event_type))

    update.assert_called_once_with()
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()
