from kotonoha.clock import MediaClock, estimate_media_time


def test_estimate_advances_while_playing():
    assert estimate_media_time(10.0, 100.0, 102.0, playing=True) == 12.0


def test_estimate_frozen_while_paused():
    assert estimate_media_time(10.0, 100.0, 105.0, playing=False) == 10.0


def test_estimate_never_runs_backwards():
    assert estimate_media_time(10.0, 100.0, 99.0, playing=True) == 10.0


class FakeMonotonic:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_clock_interpolates_between_syncs():
    fake = FakeMonotonic()
    clock = MediaClock(monotonic=fake)
    assert clock.now() is None  # never synced

    clock.sync(media_time=30.0, playing=True)
    assert clock.now() == 30.0
    fake.t += 0.5
    assert clock.now() == 30.5
    fake.t += 0.5
    assert clock.now() == 31.0


def test_clock_pause_freezes_estimate():
    fake = FakeMonotonic()
    clock = MediaClock(monotonic=fake)
    clock.sync(media_time=30.0, playing=False)
    fake.t += 5.0
    assert clock.now() == 30.0


def test_resync_corrects_large_drift():
    fake = FakeMonotonic()
    clock = MediaClock(monotonic=fake)
    clock.sync(media_time=30.0, playing=True)
    fake.t += 2.0
    # Player reports 33.0 (1.0s gap > threshold -> a seek); snap to it.
    clock.sync(media_time=33.0, playing=True)
    assert clock.now() == 33.0


def test_small_drift_does_not_jump():
    fake = FakeMonotonic()
    clock = MediaClock(monotonic=fake)
    clock.sync(media_time=30.0, playing=True)
    fake.t += 0.5  # estimate is now 30.5
    # Heartbeat reports 30.4 (0.1s drift, under threshold) -> absorbed smoothly.
    clock.sync(media_time=30.4, playing=True)
    assert clock.now() == 30.5  # stayed continuous, did not jump back to 30.4
    fake.t += 0.5
    assert clock.now() == 31.0  # keeps advancing smoothly


def test_advances_even_when_playing_flag_is_false():
    # The real bug: Cider's isPlaying arrived as False while the song played.
    # The clock must still interpolate from the advancing reported time.
    fake = FakeMonotonic()
    clock = MediaClock(monotonic=fake)
    clock.sync(media_time=10.0, playing=False)
    fake.t += 1.0
    clock.sync(media_time=11.0, playing=False)  # time advanced 1.0 -> playing
    assert clock.playing is True
    fake.t += 0.5
    assert clock.now() == 11.5  # interpolating, not frozen


def test_pause_detected_when_time_stops_advancing():
    fake = FakeMonotonic()
    clock = MediaClock(monotonic=fake)
    clock.sync(media_time=30.0, playing=True)
    fake.t += 1.0
    clock.sync(media_time=31.0, playing=True)
    # A real pause reports Paused; the clock freezes once the stall (while not
    # playing) exceeds the grace window.
    fake.t += 2.0
    clock.sync(media_time=31.0, playing=False)
    assert clock.playing is False
    frozen = clock.now()
    fake.t += 5.0
    assert clock.now() == frozen  # stays put once paused


def test_coarse_position_stall_keeps_flowing_while_playing():
    # Browser MPRIS repeats the same Position value for several polls — sometimes
    # for seconds — while PlaybackStatus stays "Playing". The sweep must keep
    # advancing forward the whole time and never freeze or jump back.
    fake = FakeMonotonic()
    clock = MediaClock(monotonic=fake)
    clock.sync(media_time=10.0, playing=True)
    previous = clock.now()
    for _ in range(15):  # ~3s of a stalled Position report, well past the grace window
        fake.t += 0.2
        clock.sync(media_time=10.0, playing=True)
        current = clock.now()
        assert current >= previous  # never rolls backward
        previous = current
    assert clock.now() > 12.0  # kept interpolating forward the whole stall
    assert clock.playing is True  # a stall while Playing is never treated as a pause


def test_backward_seek_while_paused_is_followed():
    # Seeking backward while paused reports the new (smaller) time with
    # playing=False. The clock must follow it, not stay stuck at the old position.
    fake = FakeMonotonic()
    clock = MediaClock(monotonic=fake)
    clock.sync(media_time=100.0, playing=True)
    fake.t += 2.0
    clock.sync(media_time=102.0, playing=True)
    fake.t += 2.0
    clock.sync(media_time=102.0, playing=False)  # sustained stall while paused -> paused
    fake.t += 0.5
    clock.sync(media_time=20.0, playing=False)  # scrub back to 20s while still paused

    assert clock.now() == 20.0  # followed the seek, not stuck near 104
    fake.t += 0.2
    clock.sync(media_time=20.2, playing=True)  # resume
    fake.t += 0.5
    assert 20.0 <= clock.now() <= 21.5  # plays forward from the seeked position


def test_lagging_report_does_not_roll_the_sweep_back():
    fake = FakeMonotonic()
    clock = MediaClock(monotonic=fake)
    clock.sync(media_time=10.0, playing=True)
    fake.t += 0.5  # estimate ~10.5
    clock.sync(media_time=10.2, playing=True)  # advanced, but still behind estimate
    assert clock.now() >= 10.5  # stayed forward, did not snap back to 10.2


def test_sync_without_media_time_is_noop():
    fake = FakeMonotonic()
    clock = MediaClock(monotonic=fake)
    clock.sync(media_time=10.0, playing=False)
    fake.t += 1.0
    clock.sync(media_time=11.0, playing=False)  # advancing -> playing
    clock.sync(media_time=None, playing=False)  # no time -> ignored, keeps going
    fake.t += 1.0
    assert clock.now() == 12.0
