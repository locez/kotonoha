"""Ordered overlay-platform provider selection and output lifecycle."""

from __future__ import annotations

from kotonoha.platform.layer_shell import LayerShellAnchorDragStrategy, LayerShellPlatform, NiriLayerShellDragStrategy
from kotonoha.platform.overlay_contracts import (
    DragGeometry,
    DragMode,
    Output,
    SurfaceResult,
    SurfaceState,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)
from kotonoha.platform.qt_window import OrdinaryWindowDragStrategy, QtWindowPlatform
from kotonoha.platform.surface_lifecycle import SurfaceLifecycleOwner
from kotonoha.platform.window_platform import DefaultOverlayPlatformFactory, _LayerShellProvider


class _FakeController:
    """Stands in for the native bridge, so a session can be described without ctypes."""

    def __init__(self, available: bool, blur_available: bool = False) -> None:
        self.available = available
        self.blur_available = blur_available
        self.disabled_reason = None if available else "Fake compositor rejected Layer Shell."
        self.blur_disabled_reason = None if blur_available else "protocol"
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    def make_overlay(self, window_ptr: int) -> None:
        self.calls.append(("make_overlay", (window_ptr,)))

    def set_passthrough(self, window_ptr: int, enabled: bool) -> None:
        self.calls.append(("set_passthrough", (window_ptr, int(enabled))))

    def set_input_rect(self, window_ptr: int, x: int, y: int, w: int, h: int) -> None:
        self.calls.append(("set_input_rect", (window_ptr, x, y, w, h)))

    def set_anchor_position(self, window_ptr: int, x: int, y: int) -> None:
        self.calls.append(("set_anchor_position", (window_ptr, x, y)))

    def set_blur_region(self, window_ptr: int, x: int, y: int, w: int, h: int, radius: int) -> None:
        self.calls.append(("set_blur_region", (window_ptr, x, y, w, h, radius)))

    def clear_blur(self, window_ptr: int) -> None:
        self.calls.append(("clear_blur", (window_ptr,)))


class _FakeHost:
    def __init__(self) -> None:
        self.masks: list[object] = []
        self.policies: list[WindowPolicy] = []
        self.lifecycle: list[str] = []
        self.alive = True
        self.system_move_started = False

    def is_alive(self) -> bool:
        return self.alive

    def apply_window_policy(self, policy: WindowPolicy) -> None:
        self.policies.append(policy)

    def set_input_mask(self, region: WindowRectangle) -> None:
        self.masks.append(region)

    def clear_input_mask(self) -> None:
        self.masks.append("cleared")

    def native_window_pointer(self) -> int | None:
        return 1

    def geometry(self) -> WindowRectangle:
        return WindowRectangle(0, 0, 100, 50)

    def window_position(self) -> WindowPoint | None:
        return WindowPoint(0, 0)

    def screen_geometry(self) -> WindowRectangle | None:
        return WindowRectangle(0, 0, 1920, 1080)

    def bind_output(self, output: WindowRectangle) -> None:
        del output

    def hide_window(self) -> None:
        self.lifecycle.append("hide")

    def destroy_surface(self) -> None:
        self.lifecycle.append("destroy")

    def move_window(self, position: WindowPoint) -> None:
        del position

    def start_system_move(self) -> bool:
        self.system_move_started = True
        return True

    def refresh(self) -> None:
        pass


class _MovingHost(_FakeHost):
    def __init__(self) -> None:
        self.position = WindowPoint(100, 200)
        self.moves: list[WindowPoint] = []

    def window_position(self) -> WindowPoint:
        return self.position

    def move_window(self, position: WindowPoint) -> None:
        self.position = position
        self.moves.append(position)


class _NoScreenGeometryHost(_FakeHost):
    def screen_geometry(self) -> WindowRectangle | None:
        return None


class _RetryPolicyHost(_FakeHost):
    """Fail one native setup call so the lifecycle retry path is observable."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_policy = True

    def apply_window_policy(self, policy: WindowPolicy) -> None:
        if self.fail_policy:
            raise RuntimeError("setup is temporarily unavailable")
        super().apply_window_policy(policy)


class _RetryReleaseHost(_FakeHost):
    """Fail the first surface destruction while allowing a later retry."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_destroy = True

    def destroy_surface(self) -> None:
        if self.fail_destroy:
            self.fail_destroy = False
            raise RuntimeError("surface is temporarily busy")
        super().destroy_surface()


def _drag_geometry(position: WindowPoint | None = None) -> DragGeometry:
    return DragGeometry(
        position if position is not None else WindowPoint(0, 0),
        WindowRectangle(0, 0, 100, 50),
    )


def _assert_measures_global_pointer(platform, controller) -> None:
    """The niri model: the surface follows the global pointer reading.

    The two Layer Shell strategies differ in exactly which reading they measure the
    displacement from, and that is observable — hold the local position still and
    move the global one, and only this model commits a new anchor. Asserting the
    concrete strategy object would tie the test to a private field instead.
    """
    geometry = _drag_geometry()
    platform.begin_drag(WindowPoint(10, 10), WindowPoint(110, 210), geometry)
    platform.update_drag(WindowPoint(10, 10), WindowPoint(115, 213), geometry)
    anchors = [call for call in controller.calls if call[0] == "set_anchor_position"]
    assert anchors and anchors[-1][1][1:] == (5, 3), f"global displacement was not applied: {anchors}"


def _assert_measures_local_pointer(platform, controller) -> None:
    """The default model: the surface follows the press-relative local reading."""
    geometry = _drag_geometry()
    platform.begin_drag(WindowPoint(10, 10), WindowPoint(110, 210), geometry)
    platform.update_drag(WindowPoint(10, 10), WindowPoint(115, 213), geometry)
    anchors = [call for call in controller.calls if call[0] == "set_anchor_position"]
    assert not anchors or anchors[-1][1][1:] == (0, 0), f"a still pointer moved the surface: {anchors}"


def test_provider_order_selects_layer_shell_before_fallbacks() -> None:
    platform = DefaultOverlayPlatformFactory(
        _FakeController(available=True, blur_available=True), platform_name="wayland", current_desktop="KDE"
    )(_FakeHost())

    assert isinstance(platform.surface, LayerShellPlatform)
    assert platform.capabilities.layer_shell
    assert platform.capabilities.blur


def test_x11_provider_claims_without_layer_shell() -> None:
    platform = DefaultOverlayPlatformFactory(_FakeController(False), platform_name="xcb")(_FakeHost())

    assert isinstance(platform.surface, QtWindowPlatform)
    assert not platform.capabilities.layer_shell
    assert platform.capabilities.layer_shell_reason == "X11 has no Layer Shell overlay capability."


def test_wayland_fallback_explains_rejected_layer_shell() -> None:
    platform = DefaultOverlayPlatformFactory(
        _FakeController(False), platform_name="wayland", current_desktop="GNOME"
    )(_FakeHost())

    assert isinstance(platform.surface, QtWindowPlatform)
    assert platform.capabilities.layer_shell_reason == "Wayland compositor does not provide Layer Shell."
    # Blur is a separate capability, so the reason comes from the bridge rather
    # than from the window being an ordinary one.
    assert platform.capabilities.blur is False
    assert platform.capabilities.blur_reason


def test_a_wayland_fallback_keeps_blur_when_the_compositor_offers_it() -> None:
    # Mutter has no Layer Shell and does speak a blur protocol. Hardcoding blur off
    # in the fallback dropped the frosted panel on exactly that compositor.
    controller = _FakeController(False, blur_available=True)
    platform = DefaultOverlayPlatformFactory(
        controller, platform_name="wayland", current_desktop="GNOME"
    )(_FakeHost())

    assert isinstance(platform.surface, QtWindowPlatform)
    assert platform.capabilities.blur is True
    assert platform.capabilities.blur_reason is None

    assert platform.blur is not None
    result = platform.blur.set_blur_region(WindowRectangle(0, 0, 10, 10), 4)

    assert result.succeeded, result.reason
    assert any(call[0] == "set_blur_region" for call in controller.calls)


def test_generic_provider_claims_unknown_platform_with_reason() -> None:
    platform = DefaultOverlayPlatformFactory(_FakeController(False), platform_name="offscreen")(_FakeHost())

    assert isinstance(platform.surface, QtWindowPlatform)
    assert platform.capabilities.layer_shell_reason == "Layer Shell is unavailable on this platform."


def test_the_fallback_shapes_its_input_region_to_the_rectangle() -> None:
    # Only the whole-window pass-through switch was applied before, so an unlocked
    # ordinary window kept accepting clicks across its whole transparent area and
    # swallowed input meant for the window behind it.
    host = _FakeHost()
    platform = QtWindowPlatform(host, reason="no Layer Shell here")

    assert platform.set_input_region(WindowRectangle(4, 6, 40, 20)).succeeded

    # Unlocked: input is confined to the rectangle, and the window is not made
    # transparent to the pointer.
    assert host.masks == [WindowRectangle(4, 6, 40, 20)]
    assert host.policies[-1].mouse_events_transparent is False

    assert platform.set_input_region(None).succeeded

    # Locked: click-through is carried by the policy flag, and the shaping is
    # cleared rather than set to nothing — the two must not disagree.
    assert host.masks[-1] == "cleared"
    assert host.policies[-1].mouse_events_transparent is True


def test_layer_shell_operations_report_failure_when_the_capability_is_off() -> None:
    # The bridge no-ops silently when Layer Shell is unavailable, so reporting
    # success told the caller an update had happened that had not.
    platform = LayerShellPlatform(_FakeHost(), _FakeController(available=False))

    for result in (
        platform.set_input_region(WindowRectangle(0, 0, 10, 10)),
        platform.move_to(WindowPoint(1, 2)),
    ):
        assert not result.succeeded
        assert result.reason


def test_a_wayland_fallback_reports_that_it_cannot_place_its_own_window() -> None:
    # Wayland gives a client no way to place its own toplevel, and no readback can
    # tell: measured on KWin, Qt reports the requested position whether or not the
    # compositor applied it. So this is stated from the protocol. Reporting success
    # let the caller persist a position the visible window never took.
    platform = DefaultOverlayPlatformFactory(
        _FakeController(False), platform_name="wayland", current_desktop="GNOME"
    )(_FakeHost())

    assert platform.capabilities.client_positioning is False
    assert platform.placement is None
    assert platform.capabilities.system_move is True
    assert platform.capabilities.system_move_reason is None


def test_a_wayland_fallback_uses_the_compositor_system_move_contract() -> None:
    host = _FakeHost()
    platform = DefaultOverlayPlatformFactory(
        _FakeController(False), platform_name="wayland", current_desktop="GNOME"
    )(host)
    result = platform.drag.begin_drag(WindowPoint(10, 10), WindowPoint(100, 100), _drag_geometry())
    assert result.mode is DragMode.SYSTEM
    assert host.system_move_started is True
    assert platform.drag.system_move is True


def test_x11_keeps_manual_window_drag_contract() -> None:
    host = _FakeHost()
    platform = DefaultOverlayPlatformFactory(_FakeController(False), platform_name="xcb")(host)
    result = platform.drag.begin_drag(WindowPoint(10, 10), WindowPoint(100, 100), _drag_geometry())
    assert result.mode is DragMode.MANUAL
    assert host.system_move_started is False
    assert platform.drag.system_move is False


def test_an_x11_fallback_can_place_its_own_window() -> None:
    # A window manager honours a client move on X11, so the same adapter reports
    # the opposite there.
    platform = DefaultOverlayPlatformFactory(
        _FakeController(False), platform_name="xcb", current_desktop="KDE"
    )(_FakeHost())

    assert platform.capabilities.client_positioning is True
    assert platform.placement is not None
    assert platform.placement.move_to(WindowPoint(120, 40)).succeeded
def test_layer_shell_registry_selects_and_exercises_anchor_strategy() -> None:
    host = _MovingHost()
    controller = _FakeController(available=True)
    platform = DefaultOverlayPlatformFactory(controller, platform_name="wayland", current_desktop="KDE")(host)

    assert isinstance(platform.surface, LayerShellPlatform)
    # The anchor call below is what distinguishes this strategy from the ordinary
    # one, which moves the window instead. Asserting the concrete strategy object
    # would only restate the selection the behaviour already proves.
    geometry = _drag_geometry()
    assert platform.drag.begin_drag(WindowPoint(10, 10), WindowPoint(110, 210), geometry).mode is DragMode.MANUAL
    assert platform.drag.update_drag(WindowPoint(15, 13), WindowPoint(115, 213), geometry).succeeded
    assert controller.calls[-1] == ("set_anchor_position", (1, 5, 3))
    platform.drag.end_drag()


def test_layer_shell_registry_selects_niri_strategy() -> None:
    host = _MovingHost()
    controller = _FakeController(available=True)
    platform = DefaultOverlayPlatformFactory(controller, platform_name="wayland", current_desktop="niri")(host)

    assert isinstance(platform.surface, LayerShellPlatform)
    assert platform.drag.can_rebind_output is False
    _assert_measures_global_pointer(platform.drag, controller)


def test_layer_shell_registry_keeps_default_strategy_for_kde() -> None:
    host = _MovingHost()
    controller = _FakeController(available=True)
    # The session is stated, not inherited: with NIRI_SOCKET exported by whoever
    # launched the suite, this used to select niri's model and fail.
    platform = DefaultOverlayPlatformFactory(
        controller, platform_name="wayland", current_desktop="KDE", niri_socket_present=False
    )(host)

    assert isinstance(platform.surface, LayerShellPlatform)
    assert platform.drag.can_rebind_output is True
    _assert_measures_local_pointer(platform.drag, controller)


def test_layer_shell_registry_selects_niri_from_session_desktop(monkeypatch) -> None:
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    monkeypatch.setenv("XDG_SESSION_DESKTOP", "niri")
    controller = _FakeController(available=True)
    platform = DefaultOverlayPlatformFactory(controller, platform_name="wayland")(_MovingHost())

    assert isinstance(platform.surface, LayerShellPlatform)
    _assert_measures_global_pointer(platform.drag, controller)


def test_niri_strategy_integrates_global_pointer_displacement() -> None:
    host = _MovingHost()
    controller = _FakeController(available=True)
    strategy = NiriLayerShellDragStrategy(host, controller)
    strategy.set_position(WindowPoint(100, 200))

    geometry = _drag_geometry(WindowPoint(100, 200))
    assert strategy.begin_drag(WindowPoint(10, 10), WindowPoint(110, 210), geometry).mode is DragMode.MANUAL
    first = strategy.update_drag(WindowPoint(10, 10), WindowPoint(115, 213), geometry)
    assert first.succeeded
    assert controller.calls[-1] == ("set_anchor_position", (1, 105, 203))
    second_geometry = _drag_geometry(first.position)
    assert strategy.update_drag(WindowPoint(99, 99), WindowPoint(108, 205), second_geometry).succeeded
    assert controller.calls[-1] == ("set_anchor_position", (1, 98, 195))
    strategy.end_drag()


def test_niri_drag_result_keeps_persisted_position_in_sync_with_the_surface() -> None:
    host = _MovingHost()
    controller = _FakeController(available=True)
    strategy = NiriLayerShellDragStrategy(host, controller)
    geometry = DragGeometry(
        WindowPoint(100, 100),
        WindowRectangle(400, 20, 200, 100),
    )

    strategy.begin_drag(WindowPoint(10, 10), WindowPoint(100, 100), geometry)
    first = strategy.update_drag(WindowPoint(20, 10), WindowPoint(110, 100), geometry)
    second_geometry = DragGeometry(first.position, geometry.panel)
    second = strategy.update_drag(WindowPoint(30, 10), WindowPoint(120, 100), second_geometry)

    assert first.position == WindowPoint(110, 100)
    assert second.position == WindowPoint(120, 100)
    assert controller.calls[-1] == ("set_anchor_position", (1, 120, 100))


def test_niri_drag_tracks_the_visible_panel_when_the_surface_shrinks() -> None:
    host = _MovingHost()
    controller = _FakeController(available=True)
    strategy = NiriLayerShellDragStrategy(host, controller)
    initial = DragGeometry(
        WindowPoint(100, 100),
        WindowRectangle(400, 20, 200, 100),
    )

    strategy.begin_drag(WindowPoint(500, 60), WindowPoint(1000, 500), initial)
    configured = DragGeometry(
        initial.surface_position,
        WindowRectangle(300, 20, 200, 100),
    )
    result = strategy.update_drag(WindowPoint(530, 60), WindowPoint(1030, 500), configured)

    assert result.position == WindowPoint(230, 100)
    assert result.position.x + configured.panel.x == 530
    assert controller.calls[-1] == ("set_anchor_position", (1, 230, 100))


def test_niri_drag_stays_inside_the_bound_output() -> None:
    host = _MovingHost()
    controller = _FakeController(available=True)
    strategy = NiriLayerShellDragStrategy(host, controller)
    initial = DragGeometry(
        WindowPoint(1900, 1030),
        WindowRectangle(0, 0, 100, 50),
    )

    strategy.begin_drag(WindowPoint(10, 10), WindowPoint(1910, 1040), initial)
    result = strategy.update_drag(
        WindowPoint(20, 10), WindowPoint(2060, 1140), initial
    )

    assert result.position == WindowPoint(1820, 1030)
    assert controller.calls[-1] == ("set_anchor_position", (1, 1820, 1030))


def test_niri_drag_requires_current_output_geometry() -> None:
    host = _NoScreenGeometryHost()
    controller = _FakeController(available=True)
    strategy = NiriLayerShellDragStrategy(host, controller)

    result = strategy.begin_drag(
        WindowPoint(10, 10),
        WindowPoint(110, 110),
        _drag_geometry(WindowPoint(100, 100)),
    )

    assert result.mode is DragMode.UNAVAILABLE
    assert result.reason == "Niri output geometry is unavailable; dragging is disabled."
    assert controller.calls == []


def test_niri_drag_reverses_immediately_after_hitting_an_output_edge() -> None:
    host = _MovingHost()
    controller = _FakeController(available=True)
    strategy = NiriLayerShellDragStrategy(host, controller)
    geometry = DragGeometry(WindowPoint(1900, 100), WindowRectangle(0, 0, 100, 50))

    strategy.begin_drag(WindowPoint(10, 10), WindowPoint(1910, 110), geometry)
    strategy.update_drag(WindowPoint(20, 10), WindowPoint(2060, 110), geometry)
    result = strategy.update_drag(WindowPoint(30, 10), WindowPoint(2050, 110), geometry)

    assert result.position == WindowPoint(1810, 100)
    assert controller.calls[-1] == ("set_anchor_position", (1, 1810, 100))


def test_default_layer_shell_drag_remains_unrestricted_at_an_output_edge() -> None:
    host = _MovingHost()
    controller = _FakeController(available=True)
    strategy = LayerShellAnchorDragStrategy(host, controller)
    geometry = DragGeometry(WindowPoint(1900, 100), WindowRectangle(0, 0, 100, 50))

    strategy.begin_drag(WindowPoint(10, 10), WindowPoint(1910, 110), geometry)
    result = strategy.update_drag(WindowPoint(160, 10), WindowPoint(2060, 110), geometry)

    assert result.position == WindowPoint(2050, 100)
    assert controller.calls[-1] == ("set_anchor_position", (1, 2050, 100))


def test_ordinary_window_strategy_moves_from_local_anchor() -> None:
    host = _MovingHost()
    strategy = OrdinaryWindowDragStrategy(host)

    geometry = _drag_geometry(WindowPoint(100, 200))
    assert strategy.begin_drag(WindowPoint(10, 10), WindowPoint(110, 210), geometry).mode is DragMode.MANUAL
    assert strategy.update_drag(WindowPoint(25, 17), WindowPoint(125, 217), geometry).succeeded
    assert host.moves == [WindowPoint(115, 207)]
    strategy.end_drag()


def test_anchor_drag_does_not_oscillate_when_the_surface_follows_the_pointer() -> None:
    # On a compositor that applies the move immediately, the surface follows the
    # pointer, so the pointer's local position re-settles to where the press
    # landed. The anchor must stay at that press point: advancing it makes the
    # next settled report read as an equal and opposite delta, which is the
    # jitter-then-runaway drag #7 and #9 were about.
    controller = _FakeController(available=True)
    strategy = LayerShellAnchorDragStrategy(_FakeHost(), controller)
    strategy.set_position(WindowPoint(100, 100))
    geometry = _drag_geometry(WindowPoint(100, 100))
    strategy.begin_drag(WindowPoint(10, 10), WindowPoint(0, 0), geometry)

    result = strategy.update_drag(WindowPoint(30, 10), WindowPoint(0, 0), geometry)   # pointer moves right
    for _ in range(3):                                             # surface caught up
        geometry = _drag_geometry(result.position)
        result = strategy.update_drag(WindowPoint(10, 10), WindowPoint(0, 0), geometry)

    moves = [(x, y) for name, (_ptr, x, y) in controller.calls if name == "set_anchor_position"]
    assert moves[0] == (120, 100), "the first delta should move the surface"
    assert all(move == (120, 100) for move in moves[1:]), f"surface oscillated: {moves}"


def test_the_ordinary_window_drag_measures_every_delta_from_the_press_point() -> None:
    # The window follows the pointer, so the pointer's local position re-settles
    # toward where the press landed. Advancing that anchor counts the settling
    # twice: after one move the window snapped back to where it started.
    host = _RecordingHost()
    strategy = OrdinaryWindowDragStrategy(host)
    strategy.set_position(WindowPoint(100, 100))
    geometry = _drag_geometry(WindowPoint(100, 100))
    strategy.begin_drag(WindowPoint(10, 10), WindowPoint(0, 0), geometry)

    result = strategy.update_drag(WindowPoint(30, 10), WindowPoint(0, 0), geometry)   # pointer moves right
    for _ in range(3):                                            # window caught up
        geometry = _drag_geometry(result.position)
        result = strategy.update_drag(WindowPoint(10, 10), WindowPoint(0, 0), geometry)

    assert host.moves[0] == WindowPoint(120, 100), "the first delta should move the window"
    assert all(move == WindowPoint(120, 100) for move in host.moves[1:]), f"window oscillated: {host.moves}"


class _RecordingHost(_FakeHost):
    def __init__(self, position: WindowPoint | None = None) -> None:
        super().__init__()
        self.moves: list[WindowPoint] = []
        self._position = position or WindowPoint(100, 100)

    def window_position(self) -> WindowPoint | None:
        return self._position

    def move_window(self, position: WindowPoint) -> None:
        self.moves.append(position)


def test_a_wayland_fallback_drag_reports_that_nothing_moved() -> None:
    # Reported success on a compositor that ignores the move is the same defect as
    # move_to reporting it, and the drag path had its own route to the host.
    host = _RecordingHost()
    platform = QtWindowPlatform(host, client_positioning=False)

    geometry = _drag_geometry(WindowPoint(100, 100))
    platform.begin_drag(WindowPoint(10, 10), WindowPoint(0, 0), geometry)
    result = platform.update_drag(WindowPoint(30, 10), WindowPoint(0, 0), geometry)

    assert not result.succeeded
    assert result.reason == platform.capabilities.client_positioning_reason
    assert host.moves == [], "the window must not be moved when the compositor ignores it"


def test_lifecycle_retries_prepare_before_activation_after_setup_failure(qapp) -> None:
    host = _RetryPolicyHost()
    platform = LayerShellPlatform(host, _FakeController(available=True))
    owner = SurfaceLifecycleOwner(
        platform,
        output_binding=platform,
        timer_parent=qapp,
        rebuild_surface=lambda _output: SurfaceResult.applied(),
    )
    active = _output("HDMI-A-1")

    assert not owner.prepare().succeeded
    assert owner.state is SurfaceState.DEGRADED

    host.fail_policy = False
    assert owner.activate(active).succeeded
    assert owner.state is SurfaceState.ACTIVE


def test_new_output_retries_a_release_that_failed_during_output_removal(qapp) -> None:
    host = _RetryReleaseHost()
    owner, _platform = _make_lifecycle_owner(
        host, _FakeController(available=True), qapp, lambda _output: SurfaceResult.applied()
    )
    active = _output("HDMI-A-1")
    target = _output("DP-1")
    assert owner.activate(active).succeeded

    owner.output_removed(active, target)
    assert owner.state is SurfaceState.DEGRADED
    assert owner.pending_output == target

    owner.output_added(target)
    assert owner.retry_pending().succeeded
    assert owner.state is SurfaceState.ACTIVE


def test_close_remains_retryable_when_surface_release_fails(qapp) -> None:
    host = _RetryReleaseHost()
    platform = LayerShellPlatform(host, _FakeController(available=True))
    owner = SurfaceLifecycleOwner(
        platform,
        output_binding=platform,
        timer_parent=qapp,
        rebuild_surface=lambda _output: SurfaceResult.applied(),
    )
    assert owner.prepare().succeeded
    assert owner.activate(_output("HDMI-A-1")).succeeded

    first = owner.close()
    assert not first.succeeded
    assert owner.state is SurfaceState.CLOSING

    assert owner.close().succeeded
    assert owner.state is SurfaceState.CLOSED

def _output(name: str, width: int = 1920) -> Output:
    return Output(name, WindowRectangle(0, 0, width, 1080))


def _make_lifecycle_owner(host: _FakeHost, controller: _FakeController, qapp, rebuild):
    """Create the explicit owner used by output lifecycle tests."""
    platform = LayerShellPlatform(host, controller)
    owner = SurfaceLifecycleOwner(
        platform,
        output_binding=platform,
        timer_parent=qapp,
        rebuild_surface=rebuild,
    )
    assert owner.prepare().succeeded
    return owner, platform


def test_layer_shell_ignores_vanishing_output_that_is_not_active(qapp) -> None:
    host = _FakeHost()
    owner, _platform = _make_lifecycle_owner(
        host, _FakeController(available=True), qapp, lambda _output: SurfaceResult.applied()
    )
    active = _output("HDMI-A-1")
    assert owner.activate(active).succeeded

    owner.output_removed(_output("DP-1"), None)

    assert host.lifecycle == []


def test_layer_shell_rebuilds_on_returning_output_after_release(qapp) -> None:
    host = _FakeHost()
    restored: list[Output] = []

    def rebuild(output: Output) -> SurfaceResult:
        restored.append(output)
        return SurfaceResult.applied()

    owner, _platform = _make_lifecycle_owner(host, _FakeController(available=True), qapp, rebuild)
    active = _output("HDMI-A-1")
    assert owner.activate(active).succeeded
    owner.output_removed(active, None)
    owner.output_added(active)
    assert owner.retry_pending().succeeded

    assert host.lifecycle == ["hide", "destroy"]
    assert restored == [active]


def test_lifecycle_owner_accepts_the_output_selected_by_the_application(qapp) -> None:
    host = _FakeHost()
    restored: list[Output] = []

    def rebuild(output: Output) -> SurfaceResult:
        restored.append(output)
        return SurfaceResult.applied()

    owner, _platform = _make_lifecycle_owner(host, _FakeController(available=True), qapp, rebuild)
    active = _output("HDMI-A-1")
    wanted = _output("DP-2", 5120)
    assert owner.activate(active).succeeded
    owner.output_removed(active, None)
    owner.output_added(wanted)
    assert owner.retry_pending().succeeded

    assert restored == [wanted]


def test_layer_shell_falls_back_to_output_still_connected(qapp) -> None:
    host = _FakeHost()
    restored: list[Output] = []

    def rebuild(output: Output) -> SurfaceResult:
        restored.append(output)
        return SurfaceResult.applied()

    owner, _platform = _make_lifecycle_owner(host, _FakeController(available=True), qapp, rebuild)
    lost = _output("DP-2")
    live = _output("HDMI-A-1")
    assert owner.activate(lost).succeeded
    owner.output_removed(lost, live)
    assert owner.retry_pending().succeeded

    assert restored == [live]


def test_qt_window_factory_has_no_output_binding_port() -> None:
    platform = DefaultOverlayPlatformFactory(_FakeController(False), platform_name="offscreen")(_FakeHost())

    assert platform.output_binding is None


def test_the_blur_object_is_released_before_its_surface_is_destroyed(qapp) -> None:
    host = _FakeHost()
    controller = _FakeController(available=True, blur_available=True)
    owner, _platform = _make_lifecycle_owner(
        host, controller, qapp, lambda _output: SurfaceResult.applied()
    )
    active = _output("HDMI-A-1")
    assert owner.activate(active).succeeded

    owner.output_removed(active, None)

    cleared = [call for call in controller.calls if call[0] == "clear_blur"]
    assert cleared, f"the surface was destroyed with its effect still registered: {controller.calls}"
    assert host.lifecycle.index("destroy") > 0


def test_moving_to_another_output_rebuilds_the_surface(qapp) -> None:
    host = _FakeHost()
    restored: list[Output] = []

    def rebuild(output: Output) -> SurfaceResult:
        restored.append(output)
        return SurfaceResult.applied()

    owner, _platform = _make_lifecycle_owner(host, _FakeController(available=True), qapp, rebuild)
    active = _output("HDMI-A-1")
    target = _output("DP-1", 2560)
    assert owner.activate(active).succeeded
    result = owner.rebind(target)

    assert result.succeeded
    assert host.lifecycle == ["hide", "destroy"]
    assert restored == [target]


def test_a_returning_output_does_not_rebuild_a_closed_overlay(qapp) -> None:
    host = _FakeHost()
    restored: list[Output] = []

    def rebuild(output: Output) -> SurfaceResult:
        restored.append(output)
        return SurfaceResult.applied()

    owner, _platform = _make_lifecycle_owner(host, _FakeController(available=True), qapp, rebuild)
    active = _output("HDMI-A-1")
    assert owner.activate(active).succeeded
    owner.output_removed(active, None)
    owner.output_added(active)
    assert owner.close().succeeded
    assert not owner.retry_pending().succeeded

    assert restored == []
    assert owner.state is SurfaceState.CLOSED


def test_a_second_output_vanishing_before_the_rebuild_leaves_one_owed(qapp) -> None:
    host = _FakeHost()
    restored: list[Output] = []

    def rebuild(output: Output) -> SurfaceResult:
        restored.append(output)
        return SurfaceResult.applied()

    owner, _platform = _make_lifecycle_owner(host, _FakeController(available=True), qapp, rebuild)
    active = _output("HDMI-A-1")
    survivor = _output("DP-1")
    assert owner.activate(active).succeeded
    owner.output_removed(active, survivor)
    owner.output_removed(survivor, None)
    assert not owner.retry_pending().succeeded
    assert restored == []

    owner.output_added(active)
    assert owner.retry_pending().succeeded
    assert restored == [active]


def test_a_returning_output_that_cannot_be_rebuilt_stays_owed(qapp) -> None:
    host = _FakeHost()
    should_succeed = False

    def rebuild(_output: Output) -> SurfaceResult:
        if should_succeed:
            return SurfaceResult.applied()
        return SurfaceResult.rejected("surface was not ready")

    owner, _platform = _make_lifecycle_owner(host, _FakeController(available=True), qapp, rebuild)
    active = _output("HDMI-A-1")
    assert owner.activate(active).succeeded
    owner.output_removed(active, None)
    owner.output_added(active)
    assert not owner.retry_pending().succeeded
    assert owner.pending_output == active

    should_succeed = True
    owner.output_added(active)
    assert owner.retry_pending().succeeded
    assert owner.pending_output is None


def test_the_blur_object_is_released_even_when_blur_arrived_after_startup(qapp) -> None:
    host = _FakeHost()
    controller = _FakeController(available=True, blur_available=False)
    owner, _platform = _make_lifecycle_owner(
        host, controller, qapp, lambda _output: SurfaceResult.applied()
    )
    active = _output("HDMI-A-1")
    assert owner.activate(active).succeeded
    controller.blur_available = True

    owner.output_removed(active, None)

    assert [call for call in controller.calls if call[0] == "clear_blur"], (
        f"the effect outlived the surface it was keyed on: {controller.calls}"
    )


def test_a_failed_output_move_stays_owed_so_a_later_event_retries(qapp) -> None:
    host = _FakeHost()
    should_succeed = False

    def rebuild(_output: Output) -> SurfaceResult:
        if should_succeed:
            return SurfaceResult.applied()
        return SurfaceResult.rejected("rebuild refused")

    owner, _platform = _make_lifecycle_owner(host, _FakeController(available=True), qapp, rebuild)
    active = _output("HDMI-A-1")
    target = _output("DP-1")
    assert owner.activate(active).succeeded
    result = owner.rebind(target)

    assert not result.succeeded
    assert owner.pending_output == target
    assert host.lifecycle == ["hide", "destroy"]

    should_succeed = True
    owner.output_added(target)
    assert owner.retry_pending().succeeded


def test_a_wayland_session_reports_that_window_opacity_does_nothing() -> None:
    # Wayland has no client-side window-opacity protocol, so setting it only logs
    # "plugin does not support setting window opacity" once per frame. The settings
    # window used to decide that from the Qt platform name itself.
    layer_shell = DefaultOverlayPlatformFactory(
        _FakeController(available=True), platform_name="wayland", current_desktop="KDE"
    )(_FakeHost())
    fallback = DefaultOverlayPlatformFactory(
        _FakeController(False), platform_name="wayland", current_desktop="GNOME"
    )(_FakeHost())
    x11 = DefaultOverlayPlatformFactory(_FakeController(False), platform_name="xcb")(_FakeHost())

    assert layer_shell.capabilities.window_opacity is False
    assert fallback.capabilities.window_opacity is False
    assert layer_shell.capabilities.window_opacity_reason
    assert x11.capabilities.window_opacity is True
    assert x11.capabilities.window_opacity_reason is None


def test_the_settings_window_gets_the_same_adapter_the_session_selects() -> None:
    # Settings shares the session's capability facts, but it is a normal window:
    # Layer Shell and top-most stacking belong only to the lyrics overlay.
    controller = _FakeController(available=False)
    factory = DefaultOverlayPlatformFactory(controller, platform_name="xcb")

    settings = factory.for_regular_window(_FakeHost())

    assert isinstance(settings.surface, QtWindowPlatform)
    assert settings.capabilities.window_opacity is True


def test_a_settings_window_never_uses_layer_shell_even_when_overlay_can() -> None:
    factory = DefaultOverlayPlatformFactory(
        _FakeController(available=True), platform_name="wayland", current_desktop="KDE"
    )

    settings = factory.for_regular_window(_FakeHost())

    assert isinstance(settings.surface, QtWindowPlatform)
    assert settings.capabilities.layer_shell is False


def test_layer_shell_registry_selects_niri_from_its_socket() -> None:
    # niri sets XDG_CURRENT_DESKTOP=niri only when it runs as a session; started
    # nested or without the session wrapper it leaves the parent's value, so a real
    # niri can present itself as KDE. It always exports NIRI_SOCKET to its clients.
    controller = _FakeController(available=True)
    host = _FakeHost()

    platform = DefaultOverlayPlatformFactory(
        controller, platform_name="wayland", current_desktop="KDE", niri_socket_present=True
    )(host)

    assert isinstance(platform.surface, LayerShellPlatform)
    _assert_measures_global_pointer(platform.drag, controller)


def test_an_empty_drag_provider_tuple_is_not_a_missing_one() -> None:
    # `drag_providers or (...)` reinstalled the defaults when a caller passed an
    # empty tuple, so a test that meant to isolate the platform from every provider
    # silently got niri's back and depended on the ambient session again.
    controller = _FakeController(available=True)
    provider = _LayerShellProvider(controller, drag_providers=())

    # A niri desktop, so a reinstalled niri provider would be selected and measure
    # the global reading instead.
    platform = provider.select("wayland", "niri", _MovingHost())

    assert platform is not None
    assert isinstance(platform.surface, LayerShellPlatform)
    _assert_measures_local_pointer(platform.drag, controller)


def test_a_deleted_widget_reports_no_handle_rather_than_raising() -> None:
    # Every platform operation keyed on this pointer reports an unavailable handle
    # as a failed result. Letting the deleted-widget RuntimeError escape turned that
    # into an exception the callers do not catch, on a path — a deferred lifecycle
    # callback arriving after teardown — that exists precisely to happen late.
    from PyQt6 import sip
    from PyQt6.QtWidgets import QApplication, QWidget

    from kotonoha.platform.qt_host import QtWindowHost

    assert QApplication.instance() is not None
    widget = QWidget()
    host = QtWindowHost(widget)
    assert isinstance(host.native_window_pointer(), int)

    sip.delete(widget)

    assert host.native_window_pointer() is None
