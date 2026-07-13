import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QApplication

from kotonoha.config import Config
from kotonoha.overlay import LyricsOverlay
from kotonoha.state import LyricsState


class UnavailableController:
    available = False


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


def test_window_opacity_split_between_pill_and_text(qapp):
    # Pill mode: opacity is the panel's fill, so the window stays fully opaque
    # (text crisp). Text-only mode: the whole window carries the opacity.
    pill = LyricsOverlay(LyricsState(), Config(panel_style="pill", opacity=0.5), UnavailableController())
    assert pill.windowOpacity() == pytest.approx(1.0, abs=0.01)
    text = LyricsOverlay(LyricsState(), Config(panel_style="text", opacity=0.5), UnavailableController())
    # Qt quantizes window opacity to a /255 step, so allow a small tolerance.
    assert text.windowOpacity() == pytest.approx(0.5, abs=0.01)
    for overlay in (pill, text):
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
