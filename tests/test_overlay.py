import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest
from overlay_helpers import UnavailableController
from overlay_helpers import build_overlay as LyricsOverlay
from PyQt6.QtCore import QEvent, QPointF, QRect, Qt
from PyQt6.QtGui import QMouseEvent

from kotonoha.config import Config, FxIntensity, PanelStyle, PanelWidthMode, UiLanguage
from kotonoha.display.models import (
    EMPTY_FRAME,
    DisplayFrame,
    DisplayOptions,
    DisplayScript,
    DisplayState,
    Interlude,
    LineProgress,
    ResolutionState,
    WordProgress,
)
from kotonoha.display.offsets import track_offset_key
from kotonoha.display.presentation import DisplayEngine
from kotonoha.lyrics.models import LyricLine, LyricsDocument, LyricWord, TimingKind
from kotonoha.platform.overlay_contracts import SurfaceResult
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from kotonoha.ui.overlay.state import LyricsState


def display_frame(
    *,
    has_lyrics: bool = False,
    source_id: str = "test",
    song_id: str | None = None,
    timing: str | None = None,
    current: LyricLine | None = None,
    previous: LyricLine | None = None,
    next: LyricLine | None = None,
    around: tuple[LyricLine, ...] = (),
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    duration_s: float | None = None,
    current_time: float | None = None,
    is_playing: bool = False,
    interlude: Interlude | None = None,
) -> DisplayFrame:
    candidates = {line.id: line for line in (*around, previous, current, next) if line is not None}
    lines = tuple(sorted(candidates.values(), key=lambda line: line.start))
    resolved_timing = TimingKind(timing) if timing is not None else (
        TimingKind.WORD if any(line.has_word_timing for line in lines) else TimingKind.LINE if lines else None
    )
    document = LyricsDocument(
        source_id=source_id,
        song_id=song_id,
        timing=resolved_timing,
        title=title,
        artist=artist,
        album=album,
        duration_s=duration_s,
        lines=lines,
    )
    track = None
    if any(value is not None for value in (title, artist, album, duration_s)):
        track = TrackIdentity(
            "test",
            "player",
            stable_id=song_id,
            title=title or "",
            artist=artist or "",
            album=album or "",
            duration_s=duration_s,
        )
    state = (
        DisplayState.LYRICS_AVAILABLE
        if has_lyrics
        else DisplayState.NO_TRACK
        if track is None
        else DisplayState.LYRICS_NOT_FOUND
    )
    translation = None
    if current is not None and current.translation:
        translation = LyricLine(
            current.index,
            current.id,
            current.start,
            current.end,
            current.translation,
            "",
            (),
        )
    offset_key = track_offset_key(track, document if has_lyrics else None)
    return DisplayFrame(
        state,
        track=track,
        document=document if has_lyrics else None,
        current_time=current_time,
        is_playing=is_playing,
        previous=previous,
        current=current,
        translation=translation,
        next=next,
        around=around,
        interlude=interlude,
        track_offset_key=offset_key,
    )


def project_document(
    document: LyricsDocument,
    position: float,
    options: DisplayOptions | None = None,
) -> DisplayFrame:
    """Project a test document through the public display input contract."""
    track = TrackIdentity(
        "test",
        "player",
        stable_id=document.song_id,
        title=document.title or "",
        artist=document.artist or "",
        album=document.album or "",
        duration_s=document.duration_s,
    )
    playback = PlaybackObservation(
        "test",
        "player",
        track,
        PlaybackStatus.PLAYING,
        position,
        document.duration_s,
        0.0,
    )
    return DisplayEngine(options).project_observation(playback, document, ResolutionState.AVAILABLE)


def test_fixed_panel_pins_pill_width_independent_of_text(qapp):
    overlay = LyricsOverlay(
        LyricsState(),
        Config(panel_width_mode=PanelWidthMode.FIXED, panel_width=680),
        UnavailableController(),
    )
    overlay.apply_config(overlay._config)
    # The container is pinned to (about) the configured width, so it does not grow
    # or shrink with the line length.
    assert overlay._container.maximumWidth() <= 680
    assert overlay._container.minimumWidth() == overlay._container.maximumWidth()
    # Fit mode releases the pin so the pill hugs its content again.
    overlay.apply_config(Config(panel_width_mode=PanelWidthMode.FIT))
    assert overlay._container.maximumWidth() > 5000
    overlay.deleteLater()
    qapp.processEvents()


def test_font_fallback_chain_keeps_cjk_after_a_latin_family(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(font_family="Inter"), UnavailableController())
    families = overlay._presentation.font_families()
    assert families[0] == "Inter"  # the chosen family leads
    assert any("CJK" in name for name in families)  # CJK fallback still present
    overlay.deleteLater()
    qapp.processEvents()


def test_idle_shows_default_text_so_the_panel_is_not_empty(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._on_frame(EMPTY_FRAME)  # nothing playing
    assert overlay._current.text  # a default line is shown, not a blank box
    assert "♪" in overlay._current.text
    overlay.deleteLater()
    qapp.processEvents()


def test_overlay_shutdown_can_retry_after_surface_release_failure(qapp, monkeypatch):
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    responses = [
        SurfaceResult.failed("temporary release failure", retryable=True),
        SurfaceResult.applied(),
    ]
    monkeypatch.setattr(overlay._surface, "close", lambda: responses.pop(0))

    first = overlay.shutdown()
    assert not first.succeeded
    assert overlay._closed is False
    assert overlay._closing is True

    second = overlay.shutdown()
    assert second.succeeded
    assert overlay._closed is True
    assert overlay._closing is False
    overlay.deleteLater()
    qapp.processEvents()


def test_effects_apply_to_current_line_only_and_paint_safely(qapp):
    overlay = LyricsOverlay(
        LyricsState(),
        Config(fx_glow=True, fx_word_pop=True, fx_intensity=FxIntensity.EXPRESSIVE),
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
    overlay._on_frame(display_frame(has_lyrics=True, current=line, current_time=2.0, is_playing=True, timing="Word"))
    overlay._current.set_media_time(2.0)
    overlay._current.grab()  # force a paint pass through the effect code
    overlay.deleteLater()
    qapp.processEvents()


def test_current_line_only_hides_context_and_keeps_current_translation(qapp):
    previous = LyricLine(0, "p", 0.0, 2.0, "previous", "", ())
    current = LyricLine(1, "c", 2.0, 4.0, "current", "译文", ())
    next_line = LyricLine(2, "n", 4.0, 6.0, "next", "", ())
    snapshot = display_frame(
        has_lyrics=True,
        current=current,
        previous=previous,
        next=next_line,
        current_time=2.5,
        is_playing=True,
    )
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._on_frame(snapshot)
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
    overlay.deleteLater()
    qapp.processEvents()


def test_long_title_marquee_scrolls_then_holds(qapp):
    from kotonoha.ui.overlay.karaoke_label import _MARQUEE_PAUSE_S, _MARQUEE_SPEED_PX_S, KaraokeLabel

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


def test_transition_styles_render_a_visible_line(qapp):
    from kotonoha.ui.overlay.karaoke_label import KaraokeLabel

    label = KaraokeLabel()
    label.resize(200, 40)
    for style in ("fade", "rise", "slide", "zoom"):
        label.set_effects(glow=False, word_pop=False, intensity="subtle", animate=True, transition=style)
        label.set_line(LyricLine(0, style, 0.0, 3.0, "line", "", ()), False)
        label._reveal = 0.4  # mid-transition
        image = label.grab().toImage()
        assert any(
            image.pixelColor(x, y).alpha() > 0
            for x in range(image.width())
            for y in range(image.height())
        ), f"{style} transition rendered no visible pixels"
    label.deleteLater()
    qapp.processEvents()


def test_disabling_animations_reveals_lines_instantly(qapp):
    from kotonoha.ui.overlay.karaoke_label import KaraokeLabel

    label = KaraokeLabel()
    label.set_effects(glow=False, word_pop=False, intensity="subtle", animate=False)
    label.set_line(LyricLine(0, "a", 0.0, 3.0, "x", "", ()), False)
    label.set_line(LyricLine(1, "b", 0.0, 3.0, "y", "", ()), False)  # a line change
    assert label._reveal == 1.0  # animations off -> shown immediately, no fade/rise
    label.deleteLater()
    qapp.processEvents()


def test_rebinding_the_same_line_does_not_restart_its_transition(qapp):
    from kotonoha.ui.overlay.karaoke_label import KaraokeLabel

    label = KaraokeLabel()
    label.set_effects(glow=False, word_pop=False, intensity="subtle", animate=True)
    line = LyricLine(0, "same", 0.0, 3.0, "line", "", ())
    label.set_line(line, False)
    label.reveal = 0.5

    label.set_line(line, False)

    assert label.reveal == pytest.approx(0.5)
    label.deleteLater()
    qapp.processEvents()


def test_white_panel_flips_text_and_context_shadow_to_light(qapp):
    from PyQt6.QtWidgets import QGraphicsDropShadowEffect

    overlay = LyricsOverlay(LyricsState(), Config(panel_style=PanelStyle.WHITE), UnavailableController())
    base, shadow, context_css = overlay._presentation.text_colors()
    assert base.lightness() < 90  # dark lyric text on the near-white slab
    assert shadow.lightness() > 160  # light halo, not a black smudge
    effect = overlay._prev_label.graphicsEffect()
    assert isinstance(effect, QGraphicsDropShadowEffect)
    assert effect.color().lightness() > 160  # context halo follows the panel too
    # A dark panel keeps light text with a dark halo.
    overlay.apply_config(Config(panel_style=PanelStyle.PILL))
    assert overlay._presentation.text_colors()[0].lightness() > 160
    effect = overlay._prev_label.graphicsEffect()
    assert isinstance(effect, QGraphicsDropShadowEffect)
    assert effect.color().lightness() < 100
    overlay.deleteLater()
    qapp.processEvents()


def test_untimed_word_does_not_freeze_sweep(qapp):
    from PyQt6.QtGui import QFont

    from kotonoha.ui.overlay.karaoke_label import KaraokeLabel

    label = KaraokeLabel()
    label.set_style(QFont(), "#FF4FA3", "#FF8FCB", "#FF6EC7")
    line = LyricLine(
        index=0, id="L", start=0.0, end=3.0, text="? word", translation="",
        words=(LyricWord(None, None, "?"), LyricWord(1.0, 2.0, "word")),
    )
    label.set_line(line, True)
    label.set_progress(
        LineProgress("L", 0.5),
        WordProgress("L", (0.0, 0.5), 1),
    )

    sweep_x, active = label._compute_sweep(0.0, label._total_w)

    # Before the fix, the leading untimed word froze the sweep at text_left (0.0).
    assert sweep_x > 0.0
    assert active is not None  # the timed word is actively sweeping
    label.deleteLater()
    qapp.processEvents()


def test_panel_visibility_follows_style_not_lock(qapp):
    # Locking must not force-hide the panel; that is the panel-style setting's job.
    locked_pill = LyricsOverlay(
        LyricsState(), Config(passthrough=True, panel_style=PanelStyle.PILL), UnavailableController()
    )
    assert locked_pill._presentation.should_paint_panel() is True  # Glass panel stays while locked
    locked_text = LyricsOverlay(
        LyricsState(), Config(passthrough=True, panel_style=PanelStyle.TEXT), UnavailableController()
    )
    assert locked_text._presentation.should_paint_panel() is False  # Text-only is immersive
    for overlay in (locked_pill, locked_text):
        overlay.deleteLater()
    qapp.processEvents()


def test_lyric_script_converts_displayed_line(qapp):

    line = LyricLine(0, "L", 0.0, 3.0, "简体字", translation="翻译", words=(LyricWord(0.0, 1.0, "简"),))
    document = LyricsDocument("test", timing=TimingKind.WORD, lines=(line,))
    converted = DisplayEngine(
        DisplayOptions(lyrics_script=DisplayScript.ZH_HANT)
    )
    out = project_document(document, 0.5, converted.options).current
    assert out is not None
    assert out.text == "簡體字"  # display converted to Traditional
    assert out.words[0].text == "簡"  # words converted too (for the karaoke sweep)
    off = DisplayEngine(DisplayOptions(lyrics_script=DisplayScript.OFF))
    assert project_document(document, 0.5, off.options).current is line


def test_accent_tinted_black_panel_uses_accent_hue(qapp):
    from PyQt6.QtGui import QColor

    overlay = LyricsOverlay(
        LyricsState(),
        Config(panel_style=PanelStyle.PILL, panel_accent_tint=True, accent_start="#FF4FA3"),
        UnavailableController(),
    )
    colour = overlay._presentation.panel_base_color()
    assert colour != QColor(15, 17, 22)  # not the flat near-black
    assert colour.red() > colour.blue()  # tinted toward the pink accent
    overlay.deleteLater()
    qapp.processEvents()


def test_frosted_panel_paints_and_keeps_window_opaque(qapp):
    overlay = LyricsOverlay(
        LyricsState(), Config(panel_style=PanelStyle.FROST, opacity=0.6), UnavailableController()
    )
    assert overlay._presentation.should_paint_panel() is True  # frosted panel is drawn
    assert overlay.windowOpacity() == pytest.approx(1.0, abs=0.01)  # text stays crisp
    overlay.deleteLater()
    qapp.processEvents()


def test_panel_alpha_tracks_opacity(qapp):
    overlay = LyricsOverlay(
        LyricsState(),
        Config(panel_style=PanelStyle.PILL, opacity=1.0),
        UnavailableController(),
    )
    assert overlay._presentation.panel_alpha() == 255  # 100% -> solid, not the old 150 cap
    overlay.apply_config(Config(panel_style=PanelStyle.PILL, opacity=0.3))
    assert overlay._presentation.panel_alpha() == round(255 * 0.3)
    overlay.deleteLater()
    qapp.processEvents()


def test_window_stays_opaque_and_frost_uses_its_own_opacity(qapp):
    # Opacity is the panel's own fill (window always opaque so text stays crisp),
    # and the black and frosted panels keep independent opacity values.
    black = LyricsOverlay(
        LyricsState(), Config(panel_style=PanelStyle.PILL, opacity=0.0, frost_opacity=0.6), UnavailableController()
    )
    assert black.windowOpacity() == pytest.approx(1.0, abs=0.01)
    assert black._presentation.panel_alpha() == 0  # black panel can go fully transparent
    frost = LyricsOverlay(
        LyricsState(), Config(panel_style=PanelStyle.FROST, opacity=0.0, frost_opacity=0.6), UnavailableController()
    )
    assert frost.windowOpacity() == pytest.approx(1.0, abs=0.01)
    assert frost._presentation.panel_alpha() == round(255 * 0.6)  # frost uses frost_opacity, not opacity
    for overlay in (black, frost):
        overlay.deleteLater()
    qapp.processEvents()


def test_click_without_motion_does_not_persist_a_new_horizontal_offset(qapp):
    overlay = LyricsOverlay(
        LyricsState(), Config(margin_x=37), UnavailableController()
    )
    emitted = []
    overlay.position_changed.connect(
        lambda change: emitted.append((change.margin_edge, change.margin_x, change.screen_name))
    )
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
    overlay.deleteLater()
    qapp.processEvents()


def test_offset_buttons_shift_sweep_and_hide_with_lock(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(ui_language=UiLanguage.EN), UnavailableController())
    snapshot = display_frame(
        has_lyrics=True, title="Song", artist="Artist", duration_s=180.0,
        current=LyricLine(0, "line", 0.0, 4.0, "line", "", ()), current_time=1.0, is_playing=True,
    )
    overlay._on_frame(snapshot)
    changes = []
    overlay.track_offset_changed.connect(changes.append)
    overlay._earlier_btn.click()
    key = track_offset_key(snapshot.track, snapshot.document)
    assert key is not None
    assert changes[-1].key == key
    assert changes[-1].offset_ms == 50
    assert overlay._current.text == "Sync offset: +50 ms"
    overlay.set_passthrough(True)
    assert overlay._earlier_btn.isHidden() is True
    assert overlay._later_btn.isHidden() is True
    overlay.deleteLater()
    qapp.processEvents()


def test_track_without_offset_uses_global_lead(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(lead_ms=120), UnavailableController())
    document = LyricsDocument(
        "test",
        timing=TimingKind.LINE,
        title="Song",
        artist="Artist",
        lines=(LyricLine(0, "line", 0.0, 4.0, "line", "", ()),),
    )
    frame = project_document(document, 1.0, DisplayOptions(lead_ms=120))
    assert frame.current_time == pytest.approx(1.12)
    overlay.deleteLater()
    qapp.processEvents()






def test_turning_off_word_highlight_stops_the_word_sweep(qapp):
    # Only the snapshot's own timing flag was consulted, so the settings checkbox
    # saved, translated into four languages, and changed nothing.
    words = (LyricWord(0.0, 0.5, "你"), LyricWord(0.5, 1.0, "好"))
    line = LyricLine(0, "L0", 0.0, 4.0, "你好", "", words)
    snapshot = display_frame(
        has_lyrics=True, timing="Word", title="Song", artist="Artist", duration_s=100.0,
        current=line, current_time=0.2, is_playing=True,
    )

    on = LyricsOverlay(LyricsState(), Config(karaoke=True), UnavailableController())
    off = LyricsOverlay(LyricsState(), Config(karaoke=False), UnavailableController())
    on._on_frame(snapshot)
    off._on_frame(snapshot)

    assert on._current._word_mode is True
    assert off._current._word_mode is False, "the word-highlight setting did nothing"
    for overlay in (on, off):
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
            LyricsState(), Config(panel_width_mode=PanelWidthMode.FIT, font_size=font_size), UnavailableController()
        )
        monkeypatch.setattr(overlay, "_target_screen", lambda: WideScreen())
        width = overlay._window_size()[0]
        overlay.deleteLater()
        return width

    assert widths(20) == 1100, "the default font size lost its established width"
    assert widths(80) - 56 >= 2023, "a 2023px line still does not fit at font_size 80"
    qapp.processEvents()
