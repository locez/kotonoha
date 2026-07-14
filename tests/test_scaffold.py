from kotonoha import __version__


def test_version_is_defined() -> None:
    assert __version__


def test_single_instance_lock(tmp_path) -> None:
    from kotonoha.main import _single_instance_lock

    path = str(tmp_path / "kotonoha.lock")
    lock = _single_instance_lock(path)
    assert lock is not None and lock.isLocked()  # first launch acquires it
    lock.unlock()
    again = _single_instance_lock(path)  # released -> a later launch can acquire
    assert again is not None
    again.unlock()
