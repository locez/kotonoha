"""What the overlay asks of the platform, and what it does with the answer.

Placement, outputs, input regions and drags are the adapter's contract: the overlay
asks for a capability and the adapter answers, including when the answer is no. The
panel's own appearance is described in test_overlay.py.
"""

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from overlay_helpers import (
    FakeScreen,
    LayerShellStub,
    UnavailableController,
    _ok,
    layer_shell_platform,
)
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QGuiApplication, QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget

from kotonoha.config import Config
from kotonoha.overlay import LyricsOverlay
from kotonoha.platform.overlay_contracts import Output, OverlayOperationResult, WindowRectangle
from kotonoha.state import LyricsState


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


def test_drag_crosses_output_without_recreating_the_layer_surface(qapp):
    source = FakeScreen("HDMI-A-1", 0, 0, 2048, 1152)
    target = FakeScreen("DP-1", 2048, 0, 1920, 1080)
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._active_screen = source
    overlay._layer_pos = QPoint(1900, 100)
    overlay._dragging = True
    overlay._drag_local = QPoint(20, 20)

    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(200, 20),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    with patch.object(QGuiApplication, "screens", return_value=[source, target]):
        overlay.mouseMoveEvent(event)

    assert overlay._layer_pos == QPoint(2080, 100)
    assert overlay._active_screen is source
    assert LyricsOverlay._screen_for_global_point(QPoint(2280, 120), [source, target], source) is target
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_released_cross_output_keeps_margin_x_and_records_output(qapp):
    source = FakeScreen("HDMI-A-1", 0, 0, 2048, 1152)
    target = FakeScreen("DP-1", 2048, 0, 1920, 1080)
    overlay = LyricsOverlay(
        LyricsState(), Config(margin_x=37), UnavailableController()
    )
    overlay._active_screen = source
    overlay._layer_pos = QPoint(2100, 100)  # global x = 2100, on DP-1
    overlay._drag_local = QPoint(100, 40)
    emitted: list[tuple[int, int, str]] = []
    overlay.position_changed.connect(lambda edge, margin_x, name: emitted.append((edge, margin_x, name)))

    with patch.object(QGuiApplication, "screens", return_value=[source, target]), patch.object(
        overlay, "_window_size", return_value=(500, 140)
    ):
        overlay._commit_drag_position(QPoint(100, 40))

    assert overlay._config.margin_x == -658
    assert overlay._config.screen_name == "DP-1"
    assert overlay._layer_pos == QPoint(52, 100)
    assert emitted == [(100, -658, "DP-1")]
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_release_at_horizontal_edge_keeps_the_configured_offset(qapp):
    screen = FakeScreen("HDMI-A-1", 0, 0, 2048, 1152)
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._active_screen = screen
    overlay._layer_pos = QPoint(-1100, 100)
    overlay._drag_local = QPoint(20, 40)

    with patch.object(QGuiApplication, "screens", return_value=[screen]), patch.object(
        overlay, "_window_size", return_value=(1100, 140)
    ):
        overlay._commit_drag_position(QPoint(20, 40))

    assert overlay._layer_pos == QPoint(-1020, 100)
    assert overlay._config.margin_x == -1494
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_drag_keeps_the_original_vertical_bottom_range(qapp):
    screen = FakeScreen("HDMI-A-1", 0, 0, 2048, 1152)
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._active_screen = screen
    overlay._layer_pos = QPoint(400, 1000)
    overlay._dragging = True
    overlay._drag_local = QPoint(20, 20)

    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(20, 200),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    with patch.object(QGuiApplication, "screens", return_value=[screen]):
        overlay.mouseMoveEvent(event)

    assert overlay._layer_pos == QPoint(400, 1180)
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_placeholder_screen_is_never_adopted_while_every_output_is_gone(qapp):
    # Qt stands in a placeholder screen with empty geometry between the last output
    # leaving and the first one returning; binding to it sizes the surface to 0x0.
    placeholder = FakeScreen("", 0, 0, 0, 0)
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())

    with patch.object(QGuiApplication, "screens", return_value=[placeholder]), patch.object(
        overlay, "screen", return_value=placeholder
    ), patch.object(QApplication, "primaryScreen", return_value=placeholder):
        assert overlay._target_screen() is None

    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_a_locked_overlay_is_click_through_on_the_fallback_platform(qapp):
    # The ordinary-window path only positioned the window, so set_input_region was
    # never called and a config with passthrough on stayed clickable — the locked
    # overlay swallowed the pointer.
    overlay = LyricsOverlay(LyricsState(), Config(passthrough=True), UnavailableController())
    regions: list[object] = []
    with patch.object(overlay._platform, "set_input_region", lambda region: regions.append(region) or _ok()):
        overlay.activate_layer_shell()

    assert regions == [None], "the locked overlay never asked for a click-through region"
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_an_activated_surface_reports_a_rejected_placement(qapp, caplog):
    # Activation succeeding says the surface is mapped, not that the saved position
    # was applied. Dropping the placement result left the overlay at the compositor's
    # default anchor and said nothing about why it was not where the user put it.
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    layer_shell_platform(overlay)
    with patch.object(
        overlay._platform, "move_to", lambda position: OverlayOperationResult.failure("margins rejected")
    ), caplog.at_level("WARNING"):
        activated = overlay.activate_layer_shell()

    assert activated is True, "the surface is mapped; only its position was refused"
    assert "margins rejected" in caplog.text
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_a_failed_activation_falls_back_and_says_why(qapp, caplog):
    # The capability is there but activation fails — a missing handle, or the bridge
    # raising. Falling through silently left an already-mapped window unpositioned
    # with no input region and no diagnostic.
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    layer_shell_platform(overlay)
    positioned: list[bool] = []
    with patch.object(
        overlay._platform, "activate", lambda: OverlayOperationResult.failure("no window handle")
    ), patch.object(overlay, "_fallback_position", lambda: positioned.append(True)), caplog.at_level("WARNING"):
        overlay.activate_layer_shell()

    assert positioned == [True], "activation failed and nothing positioned the window"
    assert "no window handle" in caplog.text
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_the_qt_host_shapes_and_clears_the_real_input_mask(qapp):
    # The production host has to implement the shaping the contract describes, or
    # the ordinary-window path calls a method nothing provides.
    from kotonoha.platform.overlay_contracts import WindowRectangle
    from kotonoha.platform.qt_host import QtWindowHost

    widget = QWidget()
    host = QtWindowHost(widget)

    host.set_input_mask(WindowRectangle(3, 4, 20, 10))
    assert widget.mask().boundingRect() == QRect(3, 4, 20, 10)

    host.clear_input_mask()
    assert widget.mask().isEmpty()
    widget.deleteLater()
    qapp.processEvents()


def test_the_qt_host_implements_every_method_the_contract_names():
    # The host used to inherit the Protocol, so a method it forgot became a silent
    # no-op: the adapter reported success while nothing happened.
    from kotonoha.platform.overlay_contracts import WindowHost
    from kotonoha.platform.qt_host import QtWindowHost

    required = {name for name in vars(WindowHost) if not name.startswith("_")}
    missing = {name for name in required if not callable(getattr(QtWindowHost, name, None))}
    assert not missing, f"QtWindowHost does not implement: {sorted(missing)}"


def test_a_failed_activation_positions_as_an_ordinary_window(qapp):
    # The Layer Shell adapter is still in place when activation fails, so asking it
    # to move set a native anchor on a surface that was never promoted — no real
    # fallback happened.
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    platform = layer_shell_platform(overlay)
    moves: list[tuple[str, object]] = []
    with patch.object(platform, "activate", lambda: OverlayOperationResult.failure("no handle")), patch.object(
        platform, "move_to", lambda position: moves.append(("anchor", position)) or OverlayOperationResult.success()
    ), patch.object(overlay._host, "move_window", lambda position: moves.append(("host", position))):
        overlay.activate_layer_shell()

    assert [kind for kind, _ in moves] == ["host"], f"positioned through the wrong path: {moves}"
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_a_drag_is_not_persisted_where_the_window_cannot_be_placed(qapp):
    # Wayland without Layer Shell ignores a client-side move, so saving the dragged
    # position would leave the config describing somewhere the window never went.
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    committed: list[object] = []
    unplaceable = replace(
        overlay._platform.capabilities, client_positioning=False, client_positioning_reason="no"
    )
    with patch.object(
        type(overlay._platform), "capabilities", property(lambda self: unplaceable)
    ), patch.object(overlay, "_commit_drag_position", lambda cursor=None: committed.append(cursor)):
        overlay._dragging = True
        overlay._drag_moved = True
        overlay.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(10, 10),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

    assert committed == [], "a position the window never took was saved"
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_a_drag_whose_update_failed_is_not_persisted(qapp):
    # The strategy fails when the window handle is gone or the native call raises.
    # Discarding that result meant the release still saved the new position while
    # the visible surface stayed where it was.
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    committed: list[object] = []

    def _fail(local, glob):
        from kotonoha.platform.overlay_contracts import OverlayOperationResult

        return OverlayOperationResult.failure("no window handle")

    with patch.object(overlay._platform, "update_drag", _fail), patch.object(
        overlay, "_commit_drag_position", lambda cursor=None: committed.append(cursor)
    ), patch.object(overlay, "_target_screen", return_value=qapp.primaryScreen()):
        overlay.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(10, 10),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        overlay.mouseMoveEvent(
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(40, 10),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        overlay.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(40, 10),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

    assert committed == [], "a drag that never took effect was saved"
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_saved_position_from_a_larger_output_stays_fully_visible(qapp):
    # A margin dragged on a wide output must not push the panel off a smaller one.
    # The partial bounds a drag uses would keep only 80x60 px of it on screen.
    screen = FakeScreen("HDMI-A-1", 0, 0, 4096, 1152)
    overlay = LyricsOverlay(
        LyricsState(), Config(margin_x=2518, margin_edge=1092, anchor_top=True), UnavailableController()
    )
    overlay._active_screen = screen

    with patch.object(QGuiApplication, "screens", return_value=[screen]), patch.object(
        overlay, "_window_size", return_value=(1100, 170)
    ):
        pos = overlay._compute_layer_pos(1100, 170)

    assert 0 <= pos.x() <= 4096 - 1100
    assert 0 <= pos.y() <= 1152 - 170
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_a_parked_position_survives_the_next_geometry_pass(qapp):
    # Releasing at the right-hand edge is stored as a large negative x, because the
    # surface is wider than the visible pill. Re-applying the geometry — a settings
    # apply, a re-show, a restart — must leave the panel where it was released;
    # clamping it fully on screen there teleports it, which is what a user sees as
    # the panel flying away after a drag.
    screen = FakeScreen("HDMI-A-1", 0, 0, 2048, 1152)
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._active_screen = screen
    overlay._layer_pos = QPoint(-1100, 100)
    overlay._drag_local = QPoint(20, 40)

    with patch.object(QGuiApplication, "screens", return_value=[screen]), patch.object(
        overlay, "_window_size", return_value=(1100, 140)
    ), patch.object(overlay._platform, "move_to_output"):
        overlay._commit_drag_position(QPoint(20, 40))
        parked = overlay._layer_pos
        reloaded = overlay._compute_layer_pos(1100, 140)

    assert overlay._config.screen_width == 2048
    assert overlay._config.screen_height == 1152
    assert reloaded == parked, f"the panel jumped from {parked} to {reloaded}"
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_a_parked_position_is_not_trusted_on_a_different_output_of_the_same_size(qapp):
    # Two monitors of the same model have the same geometry, so size alone cannot
    # say the saved offset was measured here. Honouring it on the other one puts
    # the panel off screen, which is the failure the clamp exists to prevent.
    other = FakeScreen("DP-1", 0, 0, 1920, 1080)
    overlay = LyricsOverlay(
        LyricsState(),
        Config(
            screen_name="HDMI-A-1",
            screen_width=1920,
            screen_height=1080,
            margin_x=-1800,
            margin_edge=100,
        ),
        UnavailableController(),
    )
    overlay._active_screen = other

    with patch.object(QGuiApplication, "screens", return_value=[other]), patch.object(
        overlay, "_window_size", return_value=(1100, 140)
    ):
        pos = overlay._compute_layer_pos(1100, 140)

    assert 0 <= pos.x() <= 1920 - 1100, f"panel parked off screen at x={pos.x()}"
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_a_returning_output_is_matched_by_name_not_by_its_old_mode(qapp):
    # The geometry recorded when the screen appeared can be a mode Qt has since
    # replaced: screenAdded and geometryChanged are separate signals, and a mode
    # change does not fire the former again. Full Output equality therefore
    # rejected the very output the rebuild was waiting for, and the surface that
    # had already been destroyed was never rebuilt.
    live = FakeScreen("DP-1", 0, 0, 3840, 2160)
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    stale = Output("DP-1", WindowRectangle(0, 0, 1920, 1080))

    with patch.object(QGuiApplication, "screens", return_value=[live]), patch.object(
        overlay, "_bind_widget_screen"
    ), patch.object(overlay, "activate_layer_shell", return_value=True), patch.object(overlay, "show"):
        rebuilt = overlay._restore_output(stale)

    assert rebuilt is True, "the returning output was rejected for changing mode"
    assert overlay._active_screen is live
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()


def test_the_platform_learns_which_output_the_overlay_is_on(qapp):
    # apply_config set the attribute directly and ran before _target_screen ever
    # did, so the early return there meant the adapter was never told. Its
    # _active_output stayed None for the session, and the output lifecycle keyed
    # on it — noticing the active monitor go away, choosing where to rebuild —
    # could not fire at all.
    from kotonoha.platform.overlay_contracts import Output

    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    told: list[Output | None] = []

    def record(output: Output | None) -> None:
        told.append(output)

    with patch.object(overlay._platform, "set_active_output", record):
        overlay.apply_config(Config())

    assert told, "the platform was never told which output the overlay is on"
    overlay._render_timer.stop()
    overlay.deleteLater()
    qapp.processEvents()
