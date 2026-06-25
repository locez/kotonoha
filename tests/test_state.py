import pytest

pytest.importorskip("PyQt6.QtCore")

from kotonoha.model import LyricsSnapshot  # noqa: E402
from kotonoha.state import LyricsState  # noqa: E402


def _collect(state):
    received = []
    state.snapshot_changed.connect(received.append)
    return received


def test_update_emits_on_change():
    state = LyricsState()
    received = _collect(state)

    changed = state.update(LyricsSnapshot(found=True, title="A"))

    assert changed is True
    assert len(received) == 1
    assert received[0].title == "A"
    assert state.snapshot.title == "A"


def test_update_does_not_emit_on_identical_snapshot():
    state = LyricsState()
    received = _collect(state)

    snap = LyricsSnapshot(found=True, title="A", current_time=1.0)
    assert state.update(snap) is True
    assert state.update(LyricsSnapshot(found=True, title="A", current_time=1.0)) is False

    assert len(received) == 1


def test_heartbeat_with_advanced_time_emits():
    state = LyricsState()
    received = _collect(state)

    state.update(LyricsSnapshot(found=True, title="A", current_time=1.0))
    state.update(LyricsSnapshot(found=True, title="A", current_time=1.5))

    assert len(received) == 2


def test_clear_resets_to_empty():
    state = LyricsState()
    state.update(LyricsSnapshot(found=True, title="A"))
    assert state.clear() is True
    assert state.snapshot.found is False


def test_tick_emits_time_without_touching_snapshot():
    state = LyricsState()
    got = []
    state.time_ticked.connect(lambda ct, ip: got.append((ct, ip)))
    state.update(LyricsSnapshot(found=True, title="A"))

    state.tick(12.5, True)
    state.tick(None, None)

    assert got == [(12.5, True), (None, None)]
    assert state.snapshot.title == "A"  # tick did not change lyric content
