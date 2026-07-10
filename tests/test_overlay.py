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
