"""Own temporary overlay geometry freezing while the user interacts with controls."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer

DEFAULT_UNFREEZE_DELAY_MS = 400


class OverlayInteractionFreezeController:
    """Keep the overlay pill stationary while the pointer hovers or clicks controls.

    While frozen, FIT-mode pill width stays locked to the width captured at entry
    and bottom-anchored surfaces keep their top edge pinned so control buttons
    cannot move under the pointer during line changes or repeated offset clicks.
    """

    def __init__(
        self,
        timer_parent: QObject,
        *,
        on_state_changed: Callable[[bool, int | None], None],
        unfreeze_delay_ms: int = DEFAULT_UNFREEZE_DELAY_MS,
    ) -> None:
        """Create a freeze state owner backed by one parented single-shot timer."""
        self._on_state_changed = on_state_changed
        self._unfreeze_delay_ms = max(0, unfreeze_delay_ms)
        self._active = False
        self._pointer_inside = False
        self._dragging = False
        self._unfreeze_timer = QTimer(timer_parent)
        self._unfreeze_timer.setSingleShot(True)
        self._unfreeze_timer.timeout.connect(self._release_if_idle)

    @property
    def active(self) -> bool:
        """Whether interaction geometry freezing is currently active."""
        return self._active

    def enter(self, container_width: int) -> None:
        """Freeze current pill geometry when the pointer enters the overlay."""
        self._pointer_inside = True
        self._unfreeze_timer.stop()
        if not self._active:
            self._activate(container_width)

    def leave(self) -> None:
        """Schedule release after the pointer leaves the overlay."""
        self._pointer_inside = False
        if self._active and not self._dragging:
            self._unfreeze_timer.start(self._unfreeze_delay_ms)

    def keep_alive(self, container_width: int) -> None:
        """Keep geometry frozen across button clicks and auto-repeat ticks."""
        if not self._active:
            self._activate(container_width)
        if self._pointer_inside or self._dragging:
            self._unfreeze_timer.stop()
        else:
            self._unfreeze_timer.start(self._unfreeze_delay_ms)

    def begin_drag(self) -> None:
        """Hold any active freeze steady across a manual drag gesture."""
        self._dragging = True
        self._unfreeze_timer.stop()

    def end_drag(self) -> None:
        """Resume normal unfreeze scheduling after a manual drag finishes."""
        self._dragging = False
        if self._active and not self._pointer_inside:
            self._unfreeze_timer.start(self._unfreeze_delay_ms)

    def clear(self) -> None:
        """Immediately release geometry freeze and notify the owner."""
        was_active = self._reset_state()
        if was_active:
            self._on_state_changed(False, None)

    def stop(self) -> None:
        """Stop owned timers and reset state without emitting UI updates."""
        self._reset_state()

    def _activate(self, container_width: int) -> None:
        self._active = True
        frozen_width = container_width if container_width > 0 else None
        self._on_state_changed(True, frozen_width)

    def _release_if_idle(self) -> None:
        if not self._active or self._pointer_inside or self._dragging:
            return
        self._active = False
        self._on_state_changed(False, None)

    def _reset_state(self) -> bool:
        """Stop the release timer, clear interaction flags, and return prior active state."""
        was_active = self._active
        self._unfreeze_timer.stop()
        self._pointer_inside = False
        self._dragging = False
        self._active = False
        return was_active


__all__ = ["DEFAULT_UNFREEZE_DELAY_MS", "OverlayInteractionFreezeController"]
