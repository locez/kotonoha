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
from overlay_helpers import (
    build_overlay as LyricsOverlay,
)
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QGuiApplication, QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget

from kotonoha.config import Config, PanelStyle
from kotonoha.platform.overlay_contracts import (
    DragMode,
    DragUpdateResult,
    Output,
    SurfaceResult,
    WindowRectangle,
)
from kotonoha.ui.overlay.geometry import OverlayGeometry
from kotonoha.ui.overlay.state import LyricsState


@pytest.mark.parametrize("event_type", (QEvent.Type.Move, QEvent.Type.Resize))
def test_container_geometry_change_schedules_surface_repaint(qapp, event_type):
    overlay = LyricsOverlay(
        LyricsState(),
        Config(passthrough=False, panel_style=PanelStyle.PILL),
        UnavailableController(),
    )

    with patch.object(overlay, "update") as update:
        overlay.eventFilter(overlay._container, QEvent(event_type))

    update.assert_called_once_with()
    overlay.deleteLater()
    qapp.processEvents()


def test_playback_frame_refreshes_do_not_repeat_the_same_input_region(qapp):
    # Smooth display frames change lyric progress, not the visible pill geometry.
    # Re-submitting the same region for every frame turns the 60 Hz display clock
    # into repeated toolkit/native surface work.
    overlay = LyricsOverlay(
        LyricsState(),
        Config(passthrough=True, panel_style=PanelStyle.PILL),
        UnavailableController(),
    )
    regions: list[object] = []
    with patch.object(
        overlay._platform,
        "set_input_region",
        side_effect=lambda region: regions.append(region) or _ok(),
    ):
        overlay.set_passthrough(False)
        qapp.processEvents()
        settled_count = len(regions)

        for _ in range(60):
            overlay._refresh_input_region()
            qapp.processEvents()

        assert len(regions) == settled_count
        assert settled_count >= 1
    overlay.deleteLater()
    qapp.processEvents()


def test_input_region_cache_tracks_lock_state_and_geometry(qapp):
    overlay = LyricsOverlay(
        LyricsState(),
        Config(passthrough=True, panel_style=PanelStyle.PILL),
        UnavailableController(),
    )
    regions: list[object] = []
    with patch.object(
        overlay._platform,
        "set_input_region",
        side_effect=lambda region: regions.append(region) or _ok(),
    ):
        overlay.set_passthrough(False)
        qapp.processEvents()
        first_region_count = len(regions)
        first_region = regions[-1]
        assert isinstance(first_region, WindowRectangle)

        overlay._surface.apply_input_region()
        assert len(regions) == first_region_count

        overlay.set_passthrough(True)
        qapp.processEvents()
        assert len(regions) == first_region_count + 1
        assert regions[-1] is None

        overlay.set_passthrough(True)
        qapp.processEvents()
        assert len(regions) == first_region_count + 1

        overlay.set_passthrough(False)
        qapp.processEvents()
        assert len(regions) == first_region_count + 2

        current = overlay._container.geometry()
        overlay._container.setGeometry(
            QRect(current.x(), current.y(), current.width() + 1, current.height())
        )
        overlay._surface.apply_input_region()
        assert len(regions) == first_region_count + 3
        assert isinstance(regions[-1], WindowRectangle)
        assert regions[-1] != first_region
    overlay.deleteLater()
    qapp.processEvents()


def test_drag_crosses_output_without_recreating_the_layer_surface(qapp):
    source = FakeScreen("HDMI-A-1", 0, 0, 2048, 1152)
    target = FakeScreen("DP-1", 2048, 0, 1920, 1080)
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._active_screen = source
    overlay._layer_pos = QPoint(1900, 100)
    with patch.object(QGuiApplication, "screens", return_value=[source, target]):
        overlay.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(20, 20),
                QPointF(20, 20),
                QPointF(1920, 120),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        overlay.mouseMoveEvent(
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(200, 20),
                QPointF(200, 20),
                QPointF(2100, 120),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

    assert overlay._layer_pos.x() == 2080
    assert overlay._active_screen is source
    assert OverlayGeometry.screen_for_global_point(QPoint(2100, 120), [source, target], source) is target
    overlay.deleteLater()
    qapp.processEvents()


def test_niri_right_edge_release_keeps_the_surface_on_its_bound_output(qapp):
    scaled = FakeScreen("DP-5", 0, 0, 2752, 1152)
    unscaled = FakeScreen("DP-1", 3440, 0, 3440, 1440)
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    overlay._active_screen = scaled
    overlay._layer_pos = QPoint(2252, 100)
    drag_port = overlay._surface._position._drag.platform
    emitted = []
    overlay.position_changed.connect(
        lambda change: emitted.append((change.margin_edge, change.margin_x, change.screen_name))
    )

    # Niri remains bound to the output selected when the Layer Shell surface was
    # created. The global pointer reading is not reliable for selecting another
    # Qt output on a fractional-scale layout.
    with (
        patch.object(type(drag_port), "can_rebind_output", property(lambda _self: False)),
        patch.object(QGuiApplication, "screens", return_value=[scaled, unscaled]),
        patch.object(overlay, "_window_size", return_value=(500, 140)),
        patch.object(overlay._surface._lifecycle, "rebind") as rebind,
    ):
        overlay._commit_drag_position(QPoint(1300, 40))

    assert overlay._layer_pos == QPoint(2252, 100)
    assert emitted == [(100, 1126, "DP-5")]
    rebind.assert_not_called()
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
    emitted = []
    overlay.position_changed.connect(
        lambda change: emitted.append((change.margin_edge, change.margin_x, change.screen_name))
    )

    with patch.object(QGuiApplication, "screens", return_value=[source, target]), patch.object(
        overlay, "_window_size", return_value=(500, 140)
    ):
        overlay._commit_drag_position(QPoint(100, 40))

    assert overlay._config.margin_x == 37
    assert overlay._config.screen_name == ""
    assert overlay._layer_pos == QPoint(52, 100)
    assert emitted == [(100, -658, "DP-1")]
    overlay.deleteLater()
    qapp.processEvents()


def test_release_at_horizontal_edge_keeps_the_configured_offset(qapp):
    screen = FakeScreen("HDMI-A-1", 0, 0, 2048, 1152)
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._active_screen = screen
    overlay._layer_pos = QPoint(-1100, 100)
    overlay._drag_local = QPoint(20, 40)
    emitted = []
    overlay.position_changed.connect(
        lambda change: emitted.append((change.margin_edge, change.margin_x, change.screen_name))
    )

    with patch.object(QGuiApplication, "screens", return_value=[screen]), patch.object(
        overlay, "_window_size", return_value=(1100, 140)
    ):
        overlay._commit_drag_position(QPoint(20, 40))

    assert overlay._layer_pos == QPoint(-1020, 100)
    assert emitted == [(100, -1494, "HDMI-A-1")]
    overlay.deleteLater()
    qapp.processEvents()


def test_drag_can_cross_the_vertical_output_edge(qapp):
    screen = FakeScreen("HDMI-A-1", 0, 0, 2048, 1152)
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    overlay._active_screen = screen
    overlay._layer_pos = QPoint(400, 1000)
    with patch.object(QGuiApplication, "screens", return_value=[screen]):
        overlay.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(20, 20),
                QPointF(20, 20),
                QPointF(420, 1020),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        overlay.mouseMoveEvent(
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(20, 200),
                QPointF(20, 200),
                QPointF(420, 1200),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

    assert overlay._layer_pos.y() == 1180
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
    overlay.deleteLater()
    qapp.processEvents()


def test_an_activated_surface_reports_a_rejected_placement(qapp, caplog):
    # Activation succeeding says the surface is mapped, not that the saved position
    # was applied. Dropping the placement result left the overlay at the compositor's
    # default anchor and said nothing about why it was not where the user put it.
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    layer_shell_platform(overlay)
    with patch.object(
        overlay._platform, "move_to", lambda position: SurfaceResult.rejected("margins rejected")
    ), caplog.at_level("WARNING"):
        activated = overlay.activate_layer_shell()

    assert activated is True, "the surface is mapped; only its position was refused"
    assert "margins rejected" in caplog.text
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
        overlay._platform, "activate", lambda: SurfaceResult.rejected("no window handle")
    ), patch.object(overlay, "_fallback_position", lambda: positioned.append(True)), caplog.at_level("WARNING"):
        overlay.activate_layer_shell()

    assert positioned == [True], "activation failed and nothing positioned the window"
    assert "no window handle" in caplog.text
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
    with patch.object(platform, "activate", lambda: SurfaceResult.rejected("no handle")), patch.object(
        platform, "move_to", lambda position: moves.append(("anchor", position)) or SurfaceResult.applied()
    ), patch.object(overlay._host, "move_window", lambda position: moves.append(("host", position))):
        overlay.activate_layer_shell()

    assert [kind for kind, _ in moves] == ["host"], f"positioned through the wrong path: {moves}"
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
    ), patch.object(
        type(overlay._platform), "client_positioning", property(lambda self: False)
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
    overlay.deleteLater()
    qapp.processEvents()


def test_a_drag_whose_update_failed_is_not_persisted(qapp):
    # The strategy fails when the window handle is gone or the native call raises.
    # Discarding that result meant the release still saved the new position while
    # the visible surface stayed where it was.
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    committed: list[object] = []

    def _fail(local, glob, geometry):
        del local, glob
        return DragUpdateResult(SurfaceResult.rejected("no window handle"), geometry.surface_position)

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
    overlay.deleteLater()
    qapp.processEvents()


def test_system_drag_press_skips_manual_updates_and_position_persistence(qapp):
    # startSystemMove gives the compositor ownership of the whole gesture. The
    # overlay must not feed later events into the client-side update path or save
    # coordinates reconstructed from those events.
    overlay = LyricsOverlay(LyricsState(), Config(), UnavailableController())
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(80, 10),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(80, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )

    with (
        patch.object(overlay._surface, "begin_drag", return_value=DragMode.SYSTEM) as begin_drag,
        patch.object(overlay._surface, "update_drag") as update_drag,
        patch.object(overlay._surface, "end_drag") as end_drag,
        patch.object(overlay, "_commit_drag_position") as commit,
    ):
        overlay.mousePressEvent(press)
        overlay.mouseMoveEvent(move)
        overlay.mouseReleaseEvent(release)

    begin_drag.assert_called_once()
    update_drag.assert_not_called()
    end_drag.assert_not_called()
    commit.assert_not_called()
    assert overlay._dragging is False
    overlay.deleteLater()
    qapp.processEvents()


def test_completed_drag_reapplies_the_visible_panel_input_region(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    overlay._dragging = True
    overlay._drag_moved = True

    with patch.object(overlay, "_commit_drag_position"), patch.object(
        overlay, "_apply_input_region"
    ) as apply_input_region:
        overlay.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(20, 20),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

    apply_input_region.assert_called_once_with()
    overlay.deleteLater()
    qapp.processEvents()


def test_drag_release_retargeted_to_lock_does_not_enable_passthrough(qapp):
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    requests: list[bool] = []
    overlay.passthrough_toggle_requested.connect(lambda: requests.append(True))
    overlay._dragging = True
    overlay._drag_moved = True

    with patch.object(overlay, "_commit_drag_position"), patch.object(overlay, "_apply_input_region"):
        overlay._on_lock_clicked()

    assert requests == []
    assert not overlay._dragging
    qapp.processEvents()
    overlay._on_lock_clicked()
    assert requests == [True]
    overlay.deleteLater()
    qapp.processEvents()


def test_saved_position_from_a_larger_output_stays_fully_visible(qapp):
    # A persisted margin on a wide output must not push the panel off its output
    # when the saved placement is reconstructed after a restart.
    screen = FakeScreen("HDMI-A-1", 0, 0, 4096, 1152)
    overlay = LyricsOverlay(
        LyricsState(), Config(margin_x=2518, margin_edge=1092, anchor_top=True), UnavailableController()
    )
    overlay._active_screen = screen

    with patch.object(QGuiApplication, "screens", return_value=[screen]), patch.object(
        overlay, "_window_size", return_value=(1100, 170)
    ):
        pos = overlay._surface.compute_layer_pos(1100, 170, screen)

    assert 0 <= pos.x() <= 4096 - 1100
    assert 0 <= pos.y() <= 1152 - 170
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
    ):
        overlay._commit_drag_position(QPoint(20, 40))
        parked = overlay._layer_pos
        reloaded = overlay._surface.compute_layer_pos(1100, 140, screen)

    assert overlay._config.screen_width == 0
    assert overlay._config.screen_height == 0
    assert reloaded == parked, f"the panel jumped from {parked} to {reloaded}"
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
        pos = overlay._surface.compute_layer_pos(1100, 140, other)

    assert 0 <= pos.x() <= 1920 - 1100, f"panel parked off screen at x={pos.x()}"
    overlay.deleteLater()
    qapp.processEvents()


def test_a_returning_output_is_matched_by_name_not_by_its_old_mode(qapp):
    # The geometry recorded when the screen appeared can be a mode Qt has since
    # replaced: screenAdded and geometryChanged are separate signals, and a mode
    # change does not fire the former again. Full Output equality therefore
    # rejected the very output the rebuild was waiting for, and the surface that
    # had already been destroyed was never rebuilt.
    live = FakeScreen("DP-1", 0, 0, 3840, 2160)
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    stale = Output("DP-1", WindowRectangle(0, 0, 1920, 1080))

    with patch.object(QGuiApplication, "screens", return_value=[live]), patch.object(
        overlay._surface, "bind_widget_screen"
    ), patch.object(overlay._platform, "activate", return_value=SurfaceResult.applied()), patch.object(
        overlay._platform, "move_to", return_value=SurfaceResult.applied()
    ):
        rebuilt = overlay._surface._rebuild_surface(stale)
        overlay._surface._complete_rebind(stale)

    assert rebuilt.succeeded, "the returning output was rejected for changing mode"
    assert overlay._active_screen is live
    overlay.deleteLater()
    qapp.processEvents()


def test_the_platform_learns_which_output_the_overlay_is_on(qapp):
    # The lifecycle owner records the output only after the platform has accepted
    # activation; selecting a screen during config application is not a commit.
    from kotonoha.platform.overlay_contracts import Output

    screen = FakeScreen("HDMI-A-1", 0, 0, 1920, 1080)
    overlay = LyricsOverlay(LyricsState(), Config(), LayerShellStub())
    with patch.object(QGuiApplication, "screens", return_value=[screen]), patch.object(
        overlay._surface, "target_screen", return_value=screen
    ), patch.object(
        overlay._platform, "activate", return_value=SurfaceResult.applied()
    ), patch.object(overlay._platform, "move_to", return_value=SurfaceResult.applied()), patch.object(
        overlay._platform, "set_input_region", return_value=SurfaceResult.applied()
    ), patch.object(overlay._platform, "set_blur_region", return_value=SurfaceResult.applied()):
        assert overlay.activate_layer_shell() is True

    assert overlay._surface.active_output == Output("HDMI-A-1", WindowRectangle(0, 0, 1920, 1080))
    overlay.deleteLater()
    qapp.processEvents()
